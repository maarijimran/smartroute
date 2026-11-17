"""Generate and run the 200-case synthetic privacy suite.

    python scripts/run_privacy_suite.py                 # regex detectors only (laptop)
    SMARTROUTE_PII_PRESIDIO=true SMARTROUTE_PII_GLINER=true \
        python scripts/run_privacy_suite.py             # full detector ensemble (server)

Uses a throwaway in-memory database and mock models: nothing is sent anywhere and
your real database is not touched. Exit code 1 if any enforcement failure occurs.
"""

import argparse
import json
import os
import sys

# Must be set before the app is imported.
os.environ["SMARTROUTE_ENV"] = "development"
os.environ["SMARTROUTE_DATABASE_URL"] = "sqlite://"
os.environ["SMARTROUTE_SEED_MOCK_MODELS"] = "true"
os.environ.setdefault("SMARTROUTE_BOOTSTRAP_ADMIN_PASSWORD", "suite-only-password")

import _common  # noqa: E402,F401
from app.bootstrap import bootstrap  # noqa: E402
from app.db import SessionLocal, create_all  # noqa: E402
from app.evaluation.privacy_suite import build_suite, run_suite  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--cases-out", default=_common.data_path("privacy_suite.jsonl"))
    parser.add_argument("--report-out", default=_common.data_path("privacy_report.json"))
    args = parser.parse_args()

    cases = build_suite(args.seed)
    with open(args.cases_out, "w", encoding="utf-8") as fh:
        for case in cases:
            fh.write(json.dumps(case, ensure_ascii=False) + "\n")

    create_all()
    with SessionLocal() as db:
        bootstrap(db)
    report = run_suite(cases)
    with open(args.report_out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)

    e, d = report["enforcement"], report["detector"]
    print(f"Privacy suite: {report['cases']} cases")
    print(f"  Enforcement failures (unauthorized dispatches): {e['unauthorized_dispatches']} "
          f"of {e['expected_blocked']} cases that must be blocked   <- target is 0")
    print(f"  Leaks caused by a missed detection:             {e['leaks_from_missed_detection']}")
    print(f"  Over-blocked harmless requests:                 {e['over_blocked']} of {e['expected_allowed']}")
    for label, key in [("all detector cases", "all"), ("pattern-detectable", "pattern_detectable_only"),
                       ("needs ML detector (names)", "needs_ml_detector")]:
        m = d[key]
        fmt = lambda v: "n/a" if v is None else f"{v:.3f}"  # noqa: E731
        print(f"  Detector, {label}: precision {fmt(m['precision'])}, recall {fmt(m['recall'])} "
              f"(tp {m['tp']}, fp {m['fp']}, fn {m['fn']}, tn {m['tn']})")
    print(f"  Report: {args.report_out}")
    return 1 if e["unauthorized_dispatches"] else 0


if __name__ == "__main__":
    sys.exit(main())
