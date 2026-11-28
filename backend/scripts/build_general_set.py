"""Router v2: build the general-task set (everyday requests that are not about a paper).

    python scripts/build_general_set.py                    # ~600 items -> data/general.jsonl
    python scripts/build_general_set.py --mmlu 200 --arc 100 --gsm8k 150 --open 150

Sources (Hugging Face, downloaded on Kaggle or the server, never on the laptop):
  cais/mmlu (all, test)                    multiple choice, 57 subjects      MIT
  allenai/ai2_arc (ARC-Challenge, test)    multiple choice, science          CC BY-SA 4.0
  openai/gsm8k (main, test)                grade-school maths, numeric       MIT
  databricks/databricks-dolly-15k          open requests without context     CC BY-SA 3.0

Multiple-choice and numeric items are scored automatically (they also feed the
calibration bank); open items are graded by the judges. Items are split 60/20/20 at
random within each source; the test split is only used for the final evaluation (E5).
Each line has the same fields as workload.jsonl, with doc_id None and a "kind".
"""

import argparse
import json
import random
import re
import sys

import _common

LETTERS = "ABCDEFGH"
MC_SUFFIX = "\n\nAnswer with the letter of the correct option."
NUM_SUFFIX = "\n\nSolve it and give the final answer as a single number."
OPEN_CATEGORIES = {"open_qa", "general_qa", "brainstorming", "creative_writing", "classification"}


def _load(name, config=None, split="test"):
    from datasets import load_dataset

    return load_dataset(name, config, split=split) if config else load_dataset(name, split=split)


def _mc_prompt(question: str, choices: list[str]) -> str:
    lines = [question.strip(), ""] + [f"{LETTERS[i]}) {c.strip()}" for i, c in enumerate(choices)]
    return "\n".join(lines) + MC_SUFFIX


def mmlu_items(n: int, rng: random.Random) -> list[dict]:
    rows = list(_load("cais/mmlu", "all"))
    try:
        rows = [r for r in rows if len(r["choices"]) <= len(LETTERS)]
        picked = rng.sample(rows, n)
        return [{"source": "mmlu", "category": "general_mc", "kind": "mc",
                 "prompt": _mc_prompt(r["question"], r["choices"]), "golds": [LETTERS[int(r["answer"])]],
                 "subject": r.get("subject", "")} for r in picked]
    except (KeyError, TypeError, ValueError) as exc:
        sys.exit(f"Unexpected cais/mmlu layout ({exc!r}); inspect one record and adjust mmlu_items().")


def arc_items(n: int, rng: random.Random) -> list[dict]:
    rows = list(_load("allenai/ai2_arc", "ARC-Challenge"))
    try:
        picked = rng.sample(rows, n)
        out = []
        for r in picked:
            labels = list(r["choices"]["label"])
            texts = list(r["choices"]["text"])
            gold = LETTERS[labels.index(r["answerKey"])]
            out.append({"source": "arc", "category": "general_mc", "kind": "mc",
                        "prompt": _mc_prompt(r["question"], texts), "golds": [gold]})
        return out
    except (KeyError, TypeError, ValueError) as exc:
        sys.exit(f"Unexpected allenai/ai2_arc layout ({exc!r}); inspect one record and adjust arc_items().")


def gsm8k_items(n: int, rng: random.Random) -> list[dict]:
    rows = list(_load("openai/gsm8k", "main"))
    try:
        picked = rng.sample(rows, n)
        out = []
        for r in picked:
            m = re.search(r"####\s*([-\d,\.]+)", r["answer"])
            if not m:
                continue
            out.append({"source": "gsm8k", "category": "general_math", "kind": "numeric",
                        "prompt": r["question"].strip() + NUM_SUFFIX, "golds": [m.group(1).replace(",", "")]})
        return out
    except (KeyError, TypeError) as exc:
        sys.exit(f"Unexpected openai/gsm8k layout ({exc!r}); inspect one record and adjust gsm8k_items().")


def open_items(n: int, rng: random.Random) -> list[dict]:
    rows = list(_load("databricks/databricks-dolly-15k", split="train"))
    try:
        rows = [r for r in rows if r["category"] in OPEN_CATEGORIES and not (r.get("context") or "").strip()
                and 20 <= len(r["instruction"]) <= 600 and r["response"].strip()]
        picked = rng.sample(rows, n)
        return [{"source": "dolly", "category": "general_open", "kind": "open", "prompt": r["instruction"].strip(),
                 "golds": [r["response"].strip()]} for r in picked]
    except (KeyError, TypeError) as exc:
        sys.exit(f"Unexpected dolly layout ({exc!r}); inspect one record and adjust open_items().")


def split_items(items: list[dict], rng: random.Random) -> list[dict]:
    """60/20/20 within each source, so every split has every kind of request."""
    by_source: dict[str, list[dict]] = {}
    for it in items:
        by_source.setdefault(it["source"], []).append(it)
    out = []
    for source in sorted(by_source):
        group = by_source[source]
        rng.shuffle(group)
        n_train, n_val = int(0.6 * len(group)), int(0.2 * len(group))
        for i, it in enumerate(group):
            it["split"] = "train" if i < n_train else "validation" if i < n_train + n_val else "test"
            out.append(it)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mmlu", type=int, default=200)
    parser.add_argument("--arc", type=int, default=100)
    parser.add_argument("--gsm8k", type=int, default=150)
    parser.add_argument("--open", type=int, default=150)
    parser.add_argument("--seed", type=int, default=21)
    parser.add_argument("--out", default=_common.data_path("general.jsonl"))
    args = parser.parse_args()
    rng = random.Random(args.seed)

    items = mmlu_items(args.mmlu, rng) + arc_items(args.arc, rng) + gsm8k_items(args.gsm8k, rng) + open_items(args.open, rng)
    items = split_items(items, rng)
    with open(args.out, "w", encoding="utf-8") as fh:
        for i, it in enumerate(items, start=1):
            row = {"item_id": f"{it['category']}-{i:04d}", "doc_id": None, "split": it["split"],
                   "category": it["category"], "task": "chat", "prompt": it["prompt"], "golds": it["golds"],
                   "unanswerable": False, "mode": "none", "kind": it["kind"], "source": it["source"]}
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    counts: dict[str, int] = {}
    for it in items:
        key = f"{it['source']}/{it['split']}"
        counts[key] = counts.get(key, 0) + 1
    print(f"{len(items)} items -> {args.out}")
    for key in sorted(counts):
        print(f"  {key:22} {counts[key]}")


if __name__ == "__main__":
    main()
