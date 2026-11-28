"""Router v2: train the query model and the cards of the collected models (on Kaggle).

    python scripts/train_router_v2.py \\
        --run data/outcomes_r1.jsonl data/judgements_r1.jsonl \\
        --run data/outcomes_r2.jsonl data/judgements_r2.jsonl \\
        --workload data/workload.jsonl data/general.jsonl \\
        --judges gemma4:26b mistral-small:24b

Each --run is one collection round: its outcome file, then its judgement file(s).
Settings are chosen on the validation split; the report compares Router v2 with the
baseline router's form (one ridge per model) and with a difficulty-blind predictor on
the same validation rows. Writes artifacts/router_v2.json and
data/router_v2_training_report.json. The test split is not read.

Uses the committed artifacts/features.json (do not refit it: the baseline weights and
this router must share the same embedding projection).
"""

import argparse
import json
import os

import _common  # noqa: F401

from app.config import get_settings
from app.core.features import get_extractor
from app.core.routing import qfeatures
from app.core.routing.router_v2 import ARTIFACT_NAME, RouterV2
from app.evaluation import router_v2_training as T


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run", nargs="+", action="append", required=True, metavar="FILE",
                        help="an outcomes file followed by its judgement file(s); repeat per round")
    parser.add_argument("--workload", nargs="+", required=True, help="workload files with the items")
    parser.add_argument("--judges", nargs="*", default=None, help="judge models to average (default: all)")
    parser.add_argument("--steps", type=int, default=3000)
    parser.add_argument("--k", type=int, nargs="+", default=[1, 2, 3])
    parser.add_argument("--l2", type=float, nargs="+", default=[1e-3, 1e-2, 1e-1])
    args = parser.parse_args()

    extractor = get_extractor()
    emb = extractor.embedding_dim
    if not emb:
        print("Note: embeddings are off (SMARTROUTE_EMBEDDINGS_ENABLED=false); training on the base features only.")
    names = list(qfeatures.NAMES) + [f"emb_{i}" for i in range(emb)]
    items = {it["item_id"]: it for path in args.workload for it in T.load_jsonl(path)}
    runs = [(r[0], r[1:]) for r in args.run]
    rows, stats = T.build_rows(runs, items, emb, args.judges)
    print(f"{stats.rows} training rows from {len(runs)} rounds: {stats.by_source}")
    print(f"  left out: {stats.skipped_no_grade} without a judge grade, {stats.skipped_abstained} abstained, "
          f"{stats.skipped_no_identity} without a model identity, {stats.skipped_features} without v2 features")
    if stats.judge_pairs:
        print(f"  judges: {stats.judge_pairs} answers graded by two judges, exact agreement "
              f"{stats.judge_exact_agreement:.2f}, correlation {stats.judge_correlation}")

    qm, cards, report = T.train(rows, names, ks=tuple(args.k), l2s=tuple(args.l2), steps=args.steps)
    report["row_stats"] = stats.__dict__
    version = T.version_for(report, names)
    router = RouterV2(version=version, qm=qm, embedding_dim=emb, feature_version=extractor.version,
                      cards=cards, meta={"report": report["validation"], "chosen": report["chosen"],
                                         "models": report["models"], "judges": args.judges})
    settings = get_settings()
    os.makedirs(settings.artifacts_dir, exist_ok=True)
    path = os.path.join(settings.artifacts_dir, ARTIFACT_NAME)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(router.to_json(), fh)
    with open(_common.data_path("router_v2_training_report.json"), "w", encoding="utf-8") as fh:
        json.dump({"version": version, **report}, fh, indent=2)

    v = report["validation"]
    print(f"\nRouter v2 {version}: k={report['chosen']['k']}, l2={report['chosen']['l2']}")
    print(f"{'validation':28} {'log loss':>9} {'Brier':>7} {'AUC':>6}")
    for name, m in v.items():
        print(f"{name:28} {m['log_loss']:9.4f} {m['brier']:7.4f} {m['auc']:6.3f}")
    print(f"\nWrote {path} ({len(cards)} model cards) and data/router_v2_training_report.json")


if __name__ == "__main__":
    main()
