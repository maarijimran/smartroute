"""Step 1 (server): build the 600-request academic workload from QASPER.

    python scripts/build_workload.py

Needs `pip install -r requirements-ml.txt` and internet access to Hugging Face.
Writes data/docs/<paper>.txt, data/workload.jsonl and data/workload_manifest.json.

Composition (proposal Table I):
  360  document questions          3 answerable questions on each of 120 papers
  120  summaries and explanations  one per paper; the abstract is the reference and is
                                   removed from the document the models see
  120  context and failure stress  40 full-paper prompts (context window), 40 unanswerable
                                   questions, 40 questions reserved for failure injection
Papers are split 60/20/20 into train/validation/test BEFORE any request is created, so
every request about a paper lands in the same split.

NOT YET RUN: this script was written without access to the dataset. If the QASPER
field layout differs from what `_answers` expects, it stops with a clear message.
"""

import argparse
import json
import os
import random
import sys

import _common

SUMMARY_PROMPT = "Summarise the main contribution and findings of this paper in about 120 words."
EXPLAIN_PROMPT = "Explain in simple terms what problem this paper addresses and why it matters."


def load_qasper():
    from datasets import load_dataset

    try:
        ds = load_dataset("allenai/qasper")
    except Exception as first:  # newer `datasets` releases refuse script-based datasets
        try:
            ds = load_dataset("allenai/qasper", revision="refs/convert/parquet")
        except Exception as second:
            sys.exit(f"Could not load allenai/qasper.\n  default: {first}\n  parquet: {second}\nSee SETUP.md.")
    return [paper for split in ("train", "validation") if split in ds for paper in ds[split]]


def paper_text(paper: dict) -> str:
    full = paper["full_text"]
    sections = []
    for name, paragraphs in zip(full["section_name"], full["paragraphs"]):
        body = "\n".join(p for p in paragraphs if p and p.strip())
        if body:
            sections.append(f"{name or 'Section'}\n{body}")
    return f"{paper['title']}\n\n" + "\n\n".join(sections)


def _answers(paper: dict) -> list[dict]:
    """Returns [{question, golds, unanswerable}] for one paper."""
    qas = paper["qas"]
    out = []
    for question, answer_group in zip(qas["question"], qas["answers"]):
        golds, unanswerable_votes, annotators = [], 0, answer_group["answer"]
        for a in annotators:
            if a.get("unanswerable"):
                unanswerable_votes += 1
            elif a.get("yes_no") is not None:
                golds.append("Yes" if a["yes_no"] else "No")
            elif a.get("free_form_answer"):
                golds.append(a["free_form_answer"].strip())
            elif a.get("extractive_spans"):
                golds.append(", ".join(s.strip() for s in a["extractive_spans"]))
        unanswerable = bool(annotators) and unanswerable_votes > len(annotators) / 2
        if unanswerable or golds:
            out.append({"question": question, "golds": sorted(set(golds)), "unanswerable": unanswerable})
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--papers", type=int, default=120)
    parser.add_argument("--seed", type=int, default=13)
    parser.add_argument("--min-chars", type=int, default=8000)
    parser.add_argument("--max-chars", type=int, default=60000)
    args = parser.parse_args()
    rng = random.Random(args.seed)

    usable = []
    for paper in load_qasper():
        try:
            text, qa = paper_text(paper), _answers(paper)
        except (KeyError, TypeError) as exc:
            sys.exit(f"Unexpected QASPER record layout ({exc!r}). Inspect one record and adjust _answers().")
        answerable = [q for q in qa if not q["unanswerable"]]
        if args.min_chars <= len(text) <= args.max_chars and len(answerable) >= 3 and paper.get("abstract"):
            usable.append({"id": paper["id"], "text": text, "abstract": paper["abstract"].strip(),
                           "answerable": answerable, "unanswerable": [q for q in qa if q["unanswerable"]]})
    if len(usable) < args.papers:
        sys.exit(f"Only {len(usable)} usable papers; lower --papers or relax the length limits.")
    usable.sort(key=lambda p: p["id"])
    papers = rng.sample(usable, args.papers)

    # Document-level split first.
    order = papers[:]
    rng.shuffle(order)
    n_train, n_val = int(0.6 * len(order)), int(0.2 * len(order))
    split = {p["id"]: ("train" if i < n_train else "validation" if i < n_train + n_val else "test")
             for i, p in enumerate(order)}

    docs_dir = _common.data_path("docs", "x")
    docs_dir = os.path.dirname(docs_dir)
    items: list[dict] = []

    def add(paper, category, task, prompt, golds, unanswerable=False, mode="retrieval"):
        items.append({
            "item_id": f"{category}-{len(items) + 1:04d}", "doc_id": paper["id"], "split": split[paper["id"]],
            "category": category, "task": task, "prompt": prompt, "golds": golds,
            "unanswerable": unanswerable, "mode": mode,
        })

    for paper in papers:
        with open(os.path.join(docs_dir, f"{paper['id']}.txt"), "w", encoding="utf-8") as fh:
            fh.write(paper["text"])
        rng.shuffle(paper["answerable"])
        for q in paper["answerable"][:3]:
            add(paper, "doc_qa", "doc_qa", q["question"], q["golds"])
    for i, paper in enumerate(papers):
        if i % 2 == 0:
            add(paper, "summary", "summary", SUMMARY_PROMPT, [paper["abstract"]])
        else:
            add(paper, "explain", "explain", EXPLAIN_PROMPT, [paper["abstract"]])

    # Stress cases reuse questions that were NOT used above where possible.
    spare = [(p, q) for p in papers for q in p["answerable"][3:]]
    rng.shuffle(spare)
    longest = sorted(papers, key=lambda p: len(p["text"]), reverse=True)[:40]
    for paper in longest:
        q = paper["answerable"][3] if len(paper["answerable"]) > 3 else paper["answerable"][0]
        add(paper, "stress_long", "doc_qa", q["question"], q["golds"], mode="full_text")
    unanswerable = [(p, q) for p in papers for q in p["unanswerable"]]
    rng.shuffle(unanswerable)
    for paper, q in unanswerable[:40]:
        add(paper, "stress_unanswerable", "doc_qa", q["question"], [], unanswerable=True)
    for paper, q in (spare + [(p, p["answerable"][0]) for p in papers])[:40]:
        add(paper, "stress_failure", "doc_qa", q["question"], q["golds"])

    with open(_common.data_path("workload.jsonl"), "w", encoding="utf-8") as fh:
        for item in items:
            fh.write(json.dumps(item, ensure_ascii=False) + "\n")
    counts: dict[str, int] = {}
    for item in items:
        counts[item["category"]] = counts.get(item["category"], 0) + 1
    manifest = {
        "source": "allenai/qasper", "seed": args.seed, "papers": sorted(split),
        "split_sizes": {s: sum(1 for v in split.values() if v == s) for s in ("train", "validation", "test")},
        "category_counts": counts, "total_requests": len(items),
        "note": "Paper ids and question selection only; paper text is not redistributed.",
    }
    with open(_common.data_path("workload_manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)
    print(f"Wrote {len(items)} requests over {len(papers)} papers: {counts}")
    if counts.get("stress_unanswerable", 0) < 40:
        print("WARNING: fewer than 40 unanswerable questions were available in the selected papers.")


if __name__ == "__main__":
    main()
