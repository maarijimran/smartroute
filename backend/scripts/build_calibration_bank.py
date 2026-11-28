"""Router v2: build the calibration bank from the VALIDATION split (on Kaggle).

    python scripts/build_calibration_bank.py --workload data/workload.jsonl data/general.jsonl

Keeps only questions that can be scored without a judge: yes/no, unanswerable and short
extractive QASPER questions, and the multiple-choice and numeric general items. Each
item goes through the real pipeline (retrieval, prompt, features) without calling a
model, so calibration sends exactly what live routing would see. Writes
artifacts/calibration_bank.json with the messages, reference answers and v2 features.

Run it with the same features.json and embedding setting as train_router_v2.py.
"""

import argparse
import json
import os

import _common  # noqa: F401
from sqlalchemy import select

from app.bootstrap import bootstrap
from app.config import get_settings
from app.core import pipeline
from app.core.features import get_extractor
from app.core.routing import qfeatures
from app.core.routing.calibration import BANK_NAME
from app.db import SessionLocal, create_all
from app.evaluation import router_v2_training as T
from app.evaluation.workload import ensure_documents, ensure_eval_user, request_for

BANK_KINDS = {"yes_no", "unanswerable", "extractive", "mc", "numeric"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--workload", nargs="+", required=True)
    parser.add_argument("--docs-dir", default=os.path.dirname(_common.data_path("docs", "x")))
    parser.add_argument("--max-items", type=int, default=400, help="cap on bank size")
    args = parser.parse_args()

    extractor = get_extractor()
    emb = extractor.embedding_dim
    names = list(qfeatures.NAMES) + [f"emb_{i}" for i in range(emb)]
    items = [it for path in args.workload for it in T.load_jsonl(path)
             if it["split"] == "validation" and T.item_kind(it) in BANK_KINDS and it.get("mode") != "full_text"]
    items = items[: args.max_items]
    create_all()
    bank_items = []
    with SessionLocal() as db:
        bootstrap(db)
        user = ensure_eval_user(db)
        doc_map = ensure_documents(db, user, {i["doc_id"] for i in items if i.get("doc_id")}, args.docs_dir)
        for n, item in enumerate(items):
            plan = pipeline.prepare(db, request_for(item, user, doc_map, args.docs_dir))
            xq = list(plan.qf) + (list(plan.x[-emb:]) if emb else [])
            bank_items.append({
                "id": item["item_id"], "kind": T.item_kind(item), "golds": item.get("golds", []),
                "unanswerable": bool(item.get("unanswerable")), "source": item.get("source", "qasper"),
                "messages": plan.draft.render(), "xq": xq, "reference": n % 3 == 0,
            })
    bank = {"names": names, "feature_version": extractor.version, "items": bank_items}
    path = os.path.join(get_settings().artifacts_dir, BANK_NAME)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(bank, fh)
    kinds: dict[str, int] = {}
    for it in bank_items:
        kinds[it["kind"]] = kinds.get(it["kind"], 0) + 1
    print(f"{len(bank_items)} calibration questions -> {path}: {kinds}")


if __name__ == "__main__":
    main()
