"""Step 4 (server): train the frozen supervised router and store it in the database.

    python scripts/train_frozen.py                # train on the train split
    python scripts/train_frozen.py --warm-start   # also initialise the online bandits from it

Fits one ridge regressor per model on the TRAIN split of data/outcomes.jsonl, using
the reward settings currently saved in the policy (weights, C_ref, L_ref, reward
mode). Set those from pilot data first, and do not change them afterwards.
"""

import argparse

import _common  # noqa: F401
from app.bootstrap import bootstrap
from app.core.features import get_extractor
from app.core.policy_config import load_policy
from app.core.routing import state as learner_state
from app.db import SessionLocal, create_all
from app.evaluation.analysis import fit_arms, load_outcomes


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--outcomes", default=_common.data_path("outcomes.jsonl"))
    parser.add_argument("--warm-start", action="store_true")
    args = parser.parse_args()

    table = load_outcomes(args.outcomes)
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
            db, "frozen", arms, note=f"trained on {len(train)} train requests, reward_mode={cfg.reward_mode}"
        )
        db.commit()
        print(f"Saved frozen router v{version}: {len(train)} requests x {len(train.models)} models "
              f"({table.dropped} incomplete requests ignored)")
        if args.warm_start:
            print("Warm-started:", learner_state.warm_start(db))
    print("Select it in the Policy page (routing policy = frozen or bandit).")


if __name__ == "__main__":
    main()
