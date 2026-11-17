"""Step 2 (server): fit the feature scaler and the PCA projection on the TRAINING split.

    python scripts/fit_features.py                  # scaler + MiniLM/PCA embedding block
    python scripts/fit_features.py --no-embeddings  # scaler only (runs anywhere)

Writes artifacts/features.json. Restart the gateway afterwards, and set
SMARTROUTE_EMBEDDINGS_ENABLED=true if you fitted the embedding block.

No model is called: each training request goes through `prepare()` only, which
does local retrieval and token estimation and stops before dispatch.
"""

import argparse
import hashlib
import json
import math
import os

import numpy as np

import _common  # noqa: F401
from app.bootstrap import bootstrap
from app.config import get_settings
from app.core import pipeline
from app.core.analysis import TASKS
from app.core.features import ARTIFACT_NAME, DEFAULT_MEAN, DEFAULT_STD, NUMERIC_NAMES, FeatureExtractor, set_extractor
from app.db import SessionLocal, create_all
from app.evaluation.workload import ensure_documents, ensure_eval_user, load_jsonl, request_for


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--workload", default=_common.data_path("workload.jsonl"))
    parser.add_argument("--docs-dir", default=os.path.dirname(_common.data_path("docs", "x")))
    parser.add_argument("--no-embeddings", action="store_true")
    parser.add_argument("--pca-dim", type=int, default=16)
    args = parser.parse_args()
    settings = get_settings()

    train = [item for item in load_jsonl(args.workload) if item["split"] == "train"]
    if not train:
        raise SystemExit("No training items in the workload.")
    set_extractor(FeatureExtractor())  # default scaling while raw values are collected
    create_all()
    raw = []
    with SessionLocal() as db:
        bootstrap(db)
        user = ensure_eval_user(db)
        doc_map = ensure_documents(db, user, {i["doc_id"] for i in train}, args.docs_dir)
        for n, item in enumerate(train, start=1):
            plan = pipeline.prepare(db, request_for(item, user, doc_map, args.docs_dir, policy_override="rules"))
            raw.append([math.log1p(plan.est_in_tokens), math.log1p(plan.est_out_tokens), plan.info.complexity, 0.0, 0.0])
            if n % 50 == 0:
                print(f"  prepared {n}/{len(train)}")
    raw = np.array(raw)
    mean, std = raw.mean(axis=0), raw.std(axis=0)
    # Local load and conversation history are live signals: the single-turn
    # training workload says nothing about them, so they keep default scaling.
    for i, name in enumerate(NUMERIC_NAMES):
        if name in ("local_load", "log_history_tokens") or std[i] < 1e-8:
            mean[i], std[i] = DEFAULT_MEAN[i], DEFAULT_STD[i]
    artifact = {
        "numeric_names": NUMERIC_NAMES,
        "numeric_mean": mean.tolist(),
        "numeric_std": [float(s) if s > 1e-8 else 1.0 for s in std],
        "fitted_on": {"split": "train", "requests": len(train)},
    }

    if not args.no_embeddings:
        from sentence_transformers import SentenceTransformer

        encoder = SentenceTransformer(settings.embedding_model)
        emb = np.asarray(encoder.encode([i["prompt"] for i in train], normalize_embeddings=True, batch_size=64))
        k = min(args.pca_dim, emb.shape[0] - 1, emb.shape[1])
        center = emb.mean(axis=0)
        _, singular, vt = np.linalg.svd(emb - center, full_matrices=False)
        explained = float((singular[:k] ** 2).sum() / (singular**2).sum())
        artifact.update({
            "embedding_model": settings.embedding_model,
            "pca_mean": center.tolist(),
            "pca_components": vt[:k].tolist(),
            "pca_explained_variance": explained,
        })
        print(f"PCA: {k} dimensions keep {explained:.1%} of the embedding variance")

    artifact["version"] = hashlib.sha256(json.dumps(artifact, sort_keys=True).encode()).hexdigest()[:12]
    os.makedirs(settings.artifacts_dir, exist_ok=True)
    path = os.path.join(settings.artifacts_dir, ARTIFACT_NAME)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(artifact, fh)
    dim = len(NUMERIC_NAMES) + 2 + len(TASKS) + 1 + len(artifact.get("pca_components", []))
    print(f"Wrote {path} (version {artifact['version']}, feature dimension {dim})")


if __name__ == "__main__":
    main()
