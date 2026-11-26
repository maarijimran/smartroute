"""Freeze the reward calibration (C_ref, L_ref) chosen from pilot data.

    python scripts/set_reward_calibration.py --c-ref 0.0075 --l-ref 10

Saves through the normal policy path (recorded in the policy change history as the
superadmin) and writes data/policy.json for scripts/evaluate.py --policy-json.
Do not change these values after outcome collection starts.
"""

import argparse
import json

import _common
from sqlalchemy import select

from app.bootstrap import bootstrap
from app.core.policy_config import load_policy, save_policy
from app.db import SessionLocal, create_all
from app.models import ROLE_SUPERADMIN, User


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--c-ref", type=float, required=True, help="USD, near the strong model's median request cost")
    parser.add_argument("--l-ref", type=float, required=True, help="seconds, near the slowest acceptable answer")
    args = parser.parse_args()

    create_all()
    with SessionLocal() as db:
        bootstrap(db)
        actor = db.execute(select(User).where(User.role == ROLE_SUPERADMIN)).scalars().first()
        cfg = load_policy(db).model_copy(update={"c_ref_usd": args.c_ref, "l_ref_s": args.l_ref})
        cfg = save_policy(db, cfg, actor)
        with open(_common.data_path("policy.json"), "w", encoding="utf-8") as fh:
            json.dump(cfg.model_dump(), fh, indent=2)
        print(f"C_ref=${cfg.c_ref_usd}  L_ref={cfg.l_ref_s}s  reward_mode={cfg.reward_mode}  "
              f"weights={cfg.weights.model_dump()}  -> data/policy.json")


if __name__ == "__main__":
    main()
