"""Write a SYNTHETIC outcomes file so the evaluation script can be tried with no
model, no dataset and no API key.

    python scripts/simulate_outcomes.py
    python scripts/evaluate.py --outcomes data/outcomes_synthetic.jsonl

The numbers are invented (see app/evaluation/synthetic.py). They exist to check that
the code runs. They are not results and must not appear in the report.
"""

import argparse

import _common
from app.evaluation.synthetic import write_synthetic

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", default=_common.data_path("outcomes_synthetic.jsonl"))
    parser.add_argument("--docs", type=int, default=200)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    n = write_synthetic(args.out, n_docs=args.docs, per_doc=3, seed=args.seed)
    print(f"Wrote {n} SYNTHETIC rows to {args.out}")
