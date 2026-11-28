"""Freeze the results of a run into results/<date>_<name>/ so later runs can be compared to it.

    python scripts/snapshot_results.py --name baseline_per_tier_ridge
    python scripts/snapshot_results.py --name baseline_per_tier_ridge --include-raw

Copies the small result files from data/ (evaluation reports, privacy report, policy,
outcome and judge summaries) and writes manifest.json with everything needed to say
exactly what produced them: git commit, the model in each tier, the active learner
versions, reward settings, detector flags, package versions and SHA-256 fingerprints
of the trained weights and of every input file.

--include-raw also stores the large per-request files (workload, outcomes, judgements)
gzip-compressed, so the evaluation can be re-run later without the server.

Never copied: the database (user accounts, encrypted provider keys), .env files, and
data/ratings_key.json (it would unblind the human raters).
"""

import argparse
import datetime as dt
import gzip
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
from importlib import metadata

import _common  # noqa: F401
from sqlalchemy import select

from app.config import get_settings
from app.core import tiers
from app.core.policy_config import load_policy
from app.db import SessionLocal, create_all
from app.models import PolicyState

REPO = os.path.dirname(_common.BACKEND_DIR)  # backend/ -> repo root
SMALL = [  # copied as they are when present
    "evaluation_report.json", "evaluation_report_judge.json", "evaluation_report_wordoverlap.json",
    "privacy_report.json", "policy.json", "pilot_summary.json",
]
RAW = ["workload.jsonl", "outcomes.jsonl", "judgements.jsonl", "privacy_suite.jsonl", "ratings_sheet.csv"]
NEVER = {"ratings_key.json", "smartroute.db"}


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def git(*args: str) -> str:
    try:
        return subprocess.run(["git", "-C", REPO, *args], capture_output=True, text=True, check=True).stdout.strip()
    except Exception:
        return ""


def version(pkg: str) -> str | None:
    try:
        return metadata.version(pkg)
    except metadata.PackageNotFoundError:
        return None


def jsonl_summary(path: str) -> dict:
    """Row counts per model and split; enough to check a later run used the same data."""
    rows, per_model, per_split = 0, {}, {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            row = json.loads(line)
            rows += 1
            if "model" in row:
                per_model[row["model"]] = per_model.get(row["model"], 0) + 1
            if "split" in row:
                per_split[row["split"]] = per_split.get(row["split"], 0) + 1
    return {"rows": rows, "per_model": per_model, "per_split": per_split}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--name", required=True, help="short label, e.g. baseline_per_tier_ridge")
    parser.add_argument("--date", default=dt.date.today().isoformat(), help="date of the run (default: today)")
    parser.add_argument("--include-raw", action="store_true", help="also store workload/outcomes/judgements (gzip)")
    parser.add_argument("--note", default="", help="one line about what this run is")
    args = parser.parse_args()

    data_dir = os.path.dirname(_common.data_path("x"))
    out = os.path.join(REPO, "results", f"{args.date}_{args.name}")
    os.makedirs(out, exist_ok=True)
    settings = get_settings()

    files = {}
    for name in SMALL:
        src = os.path.join(data_dir, name)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(out, name))
            files[name] = {"sha256": sha256(src), "bytes": os.path.getsize(src), "stored": name}
    for name in RAW:
        src = os.path.join(data_dir, name)
        if not os.path.exists(src) or name in NEVER:
            continue
        entry = {"sha256": sha256(src), "bytes": os.path.getsize(src)}
        if name.endswith(".jsonl"):
            entry["summary"] = jsonl_summary(src)
        if args.include_raw:
            with open(src, "rb") as fin, gzip.open(os.path.join(out, name + ".gz"), "wb") as fout:
                shutil.copyfileobj(fin, fout)
            entry["stored"] = name + ".gz"
        files[name] = entry

    artifacts = {}
    art_dir = settings.artifacts_dir if os.path.isabs(settings.artifacts_dir) else os.path.join(_common.BACKEND_DIR, settings.artifacts_dir)
    if os.path.isdir(art_dir):
        for name in sorted(os.listdir(art_dir)):
            if name.endswith(".json"):
                artifacts[name] = sha256(os.path.join(art_dir, name))

    create_all()
    with SessionLocal() as db:
        cfg = load_policy(db)
        tier_rows = {}
        for t in tiers.TIERS:
            m = tiers.slot(db, t)
            if m is not None:
                tier_rows[t] = {
                    "slot": m.name, "vendor": m.vendor, "model_id": m.model_id, "enabled": m.enabled,
                    "is_local": m.is_local, "context_window": m.context_window,
                    "price_in_per_mtok": m.price_in_per_mtok, "price_out_per_mtok": m.price_out_per_mtok,
                    "price_updated_at": m.price_updated_at.isoformat() if m.price_updated_at else None,
                    "params": m.params,
                }
        learners = [
            {"name": s.name, "version": s.version, "note": s.note, "created_at": s.created_at.isoformat()}
            for s in db.execute(select(PolicyState).where(PolicyState.active.is_(True))).scalars()
        ]

    manifest = {
        "name": args.name,
        "date": args.date,
        "note": args.note,
        "snapshot_created": dt.datetime.now().isoformat(timespec="seconds"),
        "git": {"commit": git("rev-parse", "HEAD"), "describe": git("describe", "--tags", "--always", "--dirty")},
        "machine": {"platform": platform.platform(), "python": sys.version.split()[0]},
        "packages": {p: version(p) for p in ("numpy", "scikit-learn", "sentence-transformers", "torch",
                                             "gliner", "presidio-analyzer", "spacy", "fastapi")},
        "settings": {
            "embeddings_enabled": settings.embeddings_enabled, "embedding_model": settings.embedding_model,
            "pii_presidio": settings.pii_presidio, "pii_gliner": settings.pii_gliner,
            "pii_gliner_model": settings.pii_gliner_model, "pii_gliner_threshold": settings.pii_gliner_threshold,
            "ocr_backend": settings.ocr_backend,
        },
        "policy": {
            "routing_policy": cfg.routing_policy, "reward_mode": cfg.reward_mode,
            "weights": cfg.weights.model_dump(), "c_ref_usd": cfg.c_ref_usd, "l_ref_s": cfg.l_ref_s,
            "ridge_lambda": cfg.ridge_lambda, "linucb_alpha": cfg.linucb_alpha, "linucb_gamma": cfg.linucb_gamma,
            "eps_start": cfg.eps_start, "eps_end": cfg.eps_end, "eps_decay_steps": cfg.eps_decay_steps,
            "update_batch_size": cfg.update_batch_size,
        },
        "tiers": tier_rows,
        "active_learners": learners,
        "artifacts_sha256": artifacts,
        "files": files,
    }
    with open(os.path.join(out, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)
    print(f"Snapshot written to {out}")
    for name, entry in files.items():
        print(f"  {name:36} {entry['bytes']:>12,} bytes  {'stored' if 'stored' in entry else 'fingerprint only'}")
    if not files:
        print("  (no result files found in data/; only the configuration was recorded)")


if __name__ == "__main__":
    main()
