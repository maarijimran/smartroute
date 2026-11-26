"""Per-model summary of collected outcomes, for calibrating C_ref and L_ref from a pilot.

    python scripts/outcome_summary.py                    # data/outcomes.jsonl
    python scripts/outcome_summary.py --split train

Prints status counts and the median / 90th percentile of cost, latency, tokens and
automatic quality for each model. C_ref should sit near the strong model's typical
(median) request cost, L_ref near the slowest acceptable answer time.
"""

import argparse
from collections import defaultdict

import numpy as np

import _common
from app.evaluation.workload import load_jsonl


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--outcomes", default=_common.data_path("outcomes.jsonl"))
    parser.add_argument("--split", default=None)
    args = parser.parse_args()

    rows = [r for r in load_jsonl(args.outcomes) if args.split in (None, r["split"])]
    by_model: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_model[r["model"]].append(r)

    def q(values, p):
        return float(np.percentile(values, p)) if values else float("nan")

    print(f"{len(rows)} outcomes")
    for model, rs in by_model.items():
        statuses: dict[str, int] = defaultdict(int)
        for r in rs:
            statuses[r["status"]] += 1
        ok = [r for r in rs if r["status"] == "ok"]
        cost = [r["cost_usd"] for r in ok]
        lat = [r["latency_ms"] / 1000 for r in ok]
        print(f"\n{model} ({rs[0]['tier']}): {len(rs)} calls, status {dict(statuses)}")
        if not ok:
            continue
        print(f"  quality   mean {np.mean([r['quality'] for r in ok]):.3f}")
        print(f"  cost $    median {q(cost, 50):.5f}  p90 {q(cost, 90):.5f}  total {sum(cost):.4f}")
        print(f"  latency s median {q(lat, 50):.1f}  p90 {q(lat, 90):.1f}  max {max(lat):.1f}")
        print(f"  tokens    in median {q([r['in_tokens'] for r in ok], 50):.0f}  "
              f"out median {q([r['out_tokens'] for r in ok], 50):.0f}  p90 {q([r['out_tokens'] for r in ok], 90):.0f}")
        errors = {r["error"] for r in rs if r["status"] != "ok" and r.get("error")}
        for e in list(errors)[:3]:
            print(f"  error: {e[:160]}")


if __name__ == "__main__":
    main()
