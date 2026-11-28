"""Grade every collected answer for correctness with a local judge model.

    python scripts/judge_outcomes.py --judge gemma4:26b
    python scripts/judge_outcomes.py --judge gemma4:26b --limit 30      # quick look first
    python scripts/judge_outcomes.py --judge gemma4:26b --summary-only

Reads data/outcomes.jsonl and the reference answers in data/workload.jsonl, writes
data/judgements.jsonl (one line per answer). Resumable: answers already graded by the
same judge model and JUDGE_VERSION are skipped. Answers that failed (status != ok) are
not graded; they get the failure reward anyway.

Use a judge from a different model family than every model being graded (see
app/evaluation/judge.py). Then train and evaluate with --judgements data/judgements.jsonl.

At the end it prints mean correctness per model and task, agreement with the word-overlap
score, and a self-consistency check (a sample graded twice).
"""

import argparse
import json
import os
import random
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np

import _common
from app.evaluation.judge import JUDGE_VERSION, OllamaJudge
from app.evaluation.workload import append_jsonl, load_jsonl


def summarise(outcomes: list[dict], judged: dict, judge: OllamaJudge | None, items: dict, recheck: int) -> None:
    rows = [r for r in outcomes if (r["item_id"], r["model"]) in judged]
    if not rows:
        print("Nothing graded yet.")
        return
    print(f"\n{len(rows)} answers graded by {judged[(rows[0]['item_id'], rows[0]['model'])]['judge_model']} "
          f"({JUDGE_VERSION})")
    cats = sorted({r["category"] for r in rows})
    print(f"{'model':14}" + "".join(f"{c[:12]:>13}" for c in cats) + f"{'all':>8}{'word-overlap':>14}")
    for model in sorted({r["model"] for r in rows}):
        rs = [r for r in rows if r["model"] == model]
        line = f"{model:14}"
        for c in cats:
            v = [judged[(r["item_id"], model)]["normalised"] for r in rs if r["category"] == c]
            line += f"{np.mean(v):>13.2f}" if v else f"{'-':>13}"
        allv = [judged[(r["item_id"], model)]["normalised"] for r in rs]
        line += f"{np.mean(allv):>8.2f}{np.mean([r['quality'] for r in rs]):>14.2f}"
        print(line)
    grades = defaultdict(int)
    for r in rows:
        grades[judged[(r["item_id"], r["model"])]["score"]] += 1
    print("Grade distribution:", {g: grades[g] for g in sorted(grades)})
    j = np.array([judged[(r["item_id"], r["model"])]["normalised"] for r in rows])
    f = np.array([r["quality"] for r in rows])
    rank = lambda a: np.argsort(np.argsort(a))  # noqa: E731
    print(f"Agreement with word overlap: Pearson {np.corrcoef(j, f)[0, 1]:.2f}, "
          f"Spearman {np.corrcoef(rank(j), rank(f))[0, 1]:.2f} (low = the judge sees something overlap misses)")

    if judge and recheck:
        sample = random.Random(7).sample(rows, min(recheck, len(rows)))
        same, within1 = 0, 0
        for r in sample:
            it = items[r["item_id"]]
            again = judge.grade(it["task"], it["prompt"], it["golds"], r["answer"], it["unanswerable"],
                                temperature=0.5, seed=1).score
            first = judged[(r["item_id"], r["model"])]["score"]
            same += again == first
            within1 += abs(again - first) <= 1
        print(f"Stability on {len(sample)} answers re-graded with another seed at temperature 0.5: "
              f"identical {same / len(sample):.0%}, within one grade {within1 / len(sample):.0%}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--judge", required=True, help="Ollama model tag of the judge, e.g. gemma4:26b")
    parser.add_argument("--outcomes", default=_common.data_path("outcomes.jsonl"))
    parser.add_argument("--workload", nargs="+", default=[_common.data_path("workload.jsonl")],
                        help="one or more workload files with the reference answers (e.g. workload.jsonl general.jsonl)")
    parser.add_argument("--out", default=_common.data_path("judgements.jsonl"))
    parser.add_argument("--base-url", default="http://127.0.0.1:11434")
    parser.add_argument("--num-ctx", type=int, default=8192)
    parser.add_argument("--think", default="false", help="false | true | low | medium | high | none (omit)")
    parser.add_argument("--limit", type=int, default=None, help="grade at most N new answers")
    parser.add_argument("--workers", type=int, default=1,
                        help="parallel requests; match OLLAMA_NUM_PARALLEL on the Ollama server")
    parser.add_argument("--recheck", type=int, default=50, help="answers to grade twice for self-consistency")
    parser.add_argument("--summary-only", action="store_true")
    parser.add_argument("--only", default=None, help="comma-separated item_id:model pairs (audits)")
    parser.add_argument("--max-minutes", type=float, default=None,
                        help="stop cleanly after this long (Kaggle sessions end at 12 h); rerun to resume")
    parser.add_argument("--sample", type=float, default=1.0,
                        help="grade only this fraction of the answers (fixed by item and model, so a rerun picks the same ones);"
                             " a second judge on a sample is enough to measure agreement")
    parser.add_argument("--skip-auto", action="store_true",
                        help="do not grade answers that are scored exactly (multiple choice, numeric, yes/no, unanswerable)")
    args = parser.parse_args()
    deadline = time.time() + 60 * args.max_minutes if args.max_minutes else None

    think = {"false": False, "true": True, "none": None}.get(args.think.lower(), args.think)
    items = {it["item_id"]: it for path in args.workload for it in load_jsonl(path)}
    outcomes = load_jsonl(args.outcomes)
    judged: dict[tuple[str, str], dict] = {}
    if os.path.exists(args.out):
        for j in load_jsonl(args.out):
            if j["judge_model"] == args.judge and j["judge_version"] == JUDGE_VERSION:
                judged[(j["item_id"], j["model"])] = j

    judge = OllamaJudge(args.judge, args.base_url, args.num_ctx, think)
    todo = [r for r in outcomes if r["status"] == "ok" and (r["item_id"], r["model"]) not in judged]
    if args.only:
        wanted = {tuple(pair.split(":", 1)) for pair in args.only.split(",")}
        todo = [r for r in todo if (r["item_id"], r["model"]) in wanted]
    if args.skip_auto:
        from app.evaluation.router_v2_training import AUTO_KINDS, item_kind

        todo = [r for r in todo if r["item_id"] in items and item_kind(items[r["item_id"]]) not in AUTO_KINDS]
    if args.sample < 1.0:
        import hashlib

        def in_sample(r) -> bool:
            h = hashlib.sha256(f"{r['item_id']}|{r['model']}".encode()).digest()
            return int.from_bytes(h[:4], "big") / 2**32 < args.sample

        todo = [r for r in todo if in_sample(r)]
    random.Random(13).shuffle(todo)  # blind to model and order: answers of all models interleaved
    todo = todo[: args.limit] if args.limit else todo
    if not args.summary_only:
        print(f"{len(todo)} answers to grade with {args.judge} ({args.workers} in parallel); "
              f"{len(judged)} already graded")
        start, errors, n = time.time(), 0, 0

        def grade(r):
            it = items[r["item_id"]]
            return r, judge.grade(it["task"], it["prompt"], it["golds"], r["answer"], it["unanswerable"])

        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = [pool.submit(grade, r) for r in todo]
            for future in as_completed(futures):  # only this thread writes the file
                if deadline and time.time() > deadline:
                    for f in futures:
                        f.cancel()
                    print(f"Time limit of {args.max_minutes} min reached after {n} grades. Re-run to resume.")
                    break
                n += 1
                try:
                    r, g = future.result()
                except Exception as exc:  # keep going; a rerun retries what is missing
                    errors += 1
                    print(f"  grading failed: {exc}")
                    continue
                row = {"item_id": r["item_id"], "model": r["model"], "category": r["category"],
                       "judge_model": args.judge, "judge_version": JUDGE_VERSION,
                       "score": g.score, "normalised": g.normalised, "reason": g.reason,
                       "judge_score": g.judge_score, "contradicts": g.contradicts, "key_points": g.key_points}
                append_jsonl(args.out, row)
                judged[(r["item_id"], r["model"])] = row
                if n % 100 == 0 or n == len(todo):
                    rate = n / (time.time() - start) * 60
                    eta = (len(todo) - n) / rate if rate else 0
                    print(f"  {n}/{len(todo)} graded, {rate:.1f}/min, ~{eta:.0f} min left", flush=True)
        if errors:
            print(f"{errors} answers could not be graded; rerun to retry them.")
    summarise(outcomes, judged, judge, items, 0 if args.summary_only else args.recheck)


if __name__ == "__main__":
    main()
