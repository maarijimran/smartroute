"""Step 4 (server): train the frozen supervised router and store it in the database.

    python scripts/train_frozen.py                # train on the train split
    python scripts/train_frozen.py --warm-start   # also initialise the online bandits from it
    python scripts/train_frozen.py --judgements data/judgements.jsonl   # quality = judge correctness

Fits one ridge regressor per model on the TRAIN split of data/outcomes.jsonl, using
the reward settings currently saved in the policy (weights, C_ref, L_ref, reward
mode). Set those from pilot data first, and do not change them afterwards.

Without --judgements the quality target is the word-overlap score; with it, the local
judge's correctness grade (scripts/judge_outcomes.py).
"""

import argparse
import json
import os

import _common  # noqa: F401
from sqlalchemy import select

from app.bootstrap import bootstrap
from app.config import get_settings
from app.core.features import get_extractor
from app.core.policy_config import load_policy
from app.core.routing import state as learner_state
from app.db import SessionLocal, create_all
from app.evaluation.analysis import fit_arms, load_outcomes
from app.evaluation.judge import JUDGE_VERSION, load_judgements
from app.models import ModelEntry


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--outcomes", default=_common.data_path("outcomes.jsonl"))
    parser.add_argument("--warm-start", action="store_true")
    parser.add_argument("--judgements", default=None, help="data/judgements.jsonl: train on judge correctness")
    parser.add_argument("--judge-model", default=None, help="only use grades from this judge model")
    args = parser.parse_args()

    judgements = load_judgements(args.judgements, args.judge_model) if args.judgements else None
    quality_source = f"judge:{args.judge_model or 'any'}:{JUDGE_VERSION}" if judgements is not None else "word_overlap"
    table = load_outcomes(args.outcomes, judgements=judgements)
    train = table.split("train")
    if len(train) == 0:
        raise SystemExit("No complete training rows. Every model must have answered a request for it to count.")
    extractor = get_extractor()
    if train.X.shape[1] != extractor.dim:
        raise SystemExit(
            f"Outcomes were collected with feature dimension {train.X.shape[1]} but the gateway now uses "
            f"{extractor.dim}. Collect outcomes again with the current artifacts/features.json."
        )
    create_all()
    with SessionLocal() as db:
        bootstrap(db)
        cfg = load_policy(db)
        arms = fit_arms(train, cfg, extractor.version)
        version = learner_state.save_arms(
            db, "frozen", arms, note=f"trained on {len(train)} train requests, quality={quality_source}, reward_mode={cfg.reward_mode}"[:255]
        )
        db.commit()
        print(f"Saved frozen router v{version}: {len(train)} requests x {len(train.models)} models "
              f"({table.dropped} incomplete requests ignored), quality target: {quality_source}")
        # A file copy of the weights with everything needed to interpret them; the
        # database row stays the one the gateway loads.
        export = {
            "policy": "frozen", "version": version, "trained_on_requests": len(train),
            "quality_source": quality_source,
            "models": list(train.models),
            # Lets import_frozen_router.py attach each arm to the right tier on any machine.
            "tiers": {m.name: m.tier for m in db.execute(select(ModelEntry)).scalars() if m.name in train.models},
            "feature_version": extractor.version,
            "feature_names": extractor.names(), "feature_dim": extractor.dim,
            "reward": {"mode": cfg.reward_mode, "weights": cfg.weights.model_dump(),
                       "c_ref_usd": cfg.c_ref_usd, "l_ref_s": cfg.l_ref_s, "ridge_lambda": cfg.ridge_lambda},
            "arms": arms.to_json(),
        }
        os.makedirs(get_settings().artifacts_dir, exist_ok=True)
        path = os.path.join(get_settings().artifacts_dir, f"frozen_router_v{version}.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(export, fh, indent=1)
        print(f"Weights exported to {path}")
        if args.warm_start:
            print("Warm-started:", learner_state.warm_start(db))
    print("Select it in the Policy page (routing policy = frozen or bandit).")


if __name__ == "__main__":
    main()
