"""Blinded human-rating workflow (proposal 5g: two raters, stratified sample of 120).

    python scripts/ratings.py export                       # writes the blank rating sheet
    python scripts/ratings.py import rater1.csv rater2.csv # merges, reports agreement

`export` draws a sample stratified by task and model from the TEST split of
data/outcomes.jsonl and writes:
  data/ratings_sheet.csv  what raters fill in; model names are hidden and rows shuffled
  data/ratings_key.json   which answer each row is; keep it away from the raters

Each rater scores correctness, relevance, completeness and usefulness from 1 to 5.
`import` writes data/ratings.json for `scripts/evaluate.py --ratings` and reports
inter-rater agreement.
"""

import argparse
import csv
import json
import random

import numpy as np

import _common
from app.core.reward import human_score
from app.evaluation.workload import load_jsonl

DIMENSIONS = ["correctness", "relevance", "completeness", "usefulness"]


def export(args) -> None:
    rows = [r for r in load_jsonl(args.outcomes) if r["split"] == "test" and r["status"] == "ok"]
    rng = random.Random(args.seed)
    strata: dict[tuple[str, str], list[dict]] = {}
    for r in rows:
        strata.setdefault((r["task"], r["model"]), []).append(r)
    per_stratum = max(args.sample // max(len(strata), 1), 1)
    picked = []
    for key in sorted(strata):
        rng.shuffle(strata[key])
        picked += strata[key][:per_stratum]
    rng.shuffle(picked)
    picked = picked[: args.sample]
    key = {}
    with open(_common.data_path("ratings_sheet.csv"), "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["rating_id", "question", "answer", *DIMENSIONS])
        for n, r in enumerate(picked, start=1):
            rating_id = f"R{n:03d}"
            key[rating_id] = {"item_id": r["item_id"], "model": r["model"]}
            writer.writerow([rating_id, r["prompt"], r["answer"], "", "", "", ""])
    with open(_common.data_path("ratings_key.json"), "w", encoding="utf-8") as fh:
        json.dump(key, fh, indent=2)
    print(f"Exported {len(picked)} blinded answers across {len(strata)} task/model strata.")


def _read(path: str) -> dict[str, list[int]]:
    out = {}
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            try:
                scores = [int(row[d]) for d in DIMENSIONS]
            except (ValueError, KeyError):
                continue  # unrated row
            if all(1 <= s <= 5 for s in scores):
                out[row["rating_id"]] = scores
    return out


def quadratic_kappa(a: np.ndarray, b: np.ndarray, levels: int = 5) -> float:
    """Cohen's kappa with quadratic weights for ordinal 1..levels ratings."""
    observed = np.zeros((levels, levels))
    for x, y in zip(a, b):
        observed[x - 1, y - 1] += 1
    observed /= observed.sum()
    expected = np.outer(observed.sum(axis=1), observed.sum(axis=0))
    idx = np.arange(levels)
    weights = (idx[:, None] - idx[None, :]) ** 2 / (levels - 1) ** 2
    denominator = (weights * expected).sum()
    return float(1 - (weights * observed).sum() / denominator) if denominator > 0 else float("nan")


def import_(args) -> None:
    with open(_common.data_path("ratings_key.json"), encoding="utf-8") as fh:
        key = json.load(fh)
    raters = [_read(path) for path in args.files]
    shared = sorted(set.intersection(*(set(r) for r in raters)))
    if not shared:
        raise SystemExit("No rating_id was rated by every rater.")
    merged = {}
    for rating_id in shared:
        per_rater = [human_score(*r[rating_id]) for r in raters]
        k = key[rating_id]
        merged[f"{k['item_id']}|{k['model']}"] = float(np.mean(per_rater))
    with open(_common.data_path("ratings.json"), "w", encoding="utf-8") as fh:
        json.dump(merged, fh, indent=2)
    print(f"Merged {len(shared)} answers rated by all {len(raters)} raters.")
    if len(raters) >= 2:
        a = np.array([raters[0][i] for i in shared])
        b = np.array([raters[1][i] for i in shared])
        for d, name in enumerate(DIMENSIONS):
            print(f"  {name:13s} quadratic kappa {quadratic_kappa(a[:, d], b[:, d]):.3f}, "
                  f"mean |difference| {np.abs(a[:, d] - b[:, d]).mean():.2f}")
        overall = np.corrcoef(a.mean(axis=1), b.mean(axis=1))[0, 1]
        print(f"  overall score correlation between raters: {overall:.3f}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    ex = sub.add_parser("export")
    ex.add_argument("--outcomes", default=_common.data_path("outcomes.jsonl"))
    ex.add_argument("--sample", type=int, default=120)
    ex.add_argument("--seed", type=int, default=5)
    ex.set_defaults(func=export)
    im = sub.add_parser("import")
    im.add_argument("files", nargs="+")
    im.set_defaults(func=import_)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
