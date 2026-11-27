"""Load exported frozen-router weights into this gateway's database.

    python scripts/import_frozen_router.py artifacts/frozen_router_v3.json
    python scripts/import_frozen_router.py artifacts/frozen_router_v3.json --warm-start

For teammates who pull the repository: the gateway loads the router from its database,
which is not in git, so the exported JSON (written by scripts/train_frozen.py) is
imported here. The weights only make sense with the feature artifact they were trained
with (artifacts/features.json); that is checked before anything is saved.

Weights belong to tiers, not to particular models: each trained arm is attached to the
current local, cheap or strong slot, whatever model the superadmin has put there and
whatever the slot is called on this machine (see app/core/tiers.py).
"""

import argparse
import json

import _common  # noqa: F401
from sqlalchemy import select

from app.bootstrap import bootstrap
from app.core.features import get_extractor
from app.core.routing import state as learner_state
from app.core.routing.arms import ArmSet
from app.db import SessionLocal, create_all
from app.core.tiers import TierError, remap_arms_to_slots
from app.models import ModelEntry


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("path", help="artifacts/frozen_router_vN.json")
    parser.add_argument("--warm-start", action="store_true", help="also initialise the bandits from it")
    args = parser.parse_args()

    with open(args.path, encoding="utf-8") as fh:
        export = json.load(fh)
    extractor = get_extractor()
    if export["feature_version"] != extractor.version or export["feature_dim"] != extractor.dim:
        raise SystemExit(
            f"Feature mismatch: the weights expect features v{export['feature_version']} "
            f"(dim {export['feature_dim']}), this gateway has v{extractor.version} (dim {extractor.dim}). "
            "Use the artifacts/features.json committed with these weights and set "
            "SMARTROUTE_EMBEDDINGS_ENABLED=true."
        )
    create_all()
    with SessionLocal() as db:
        bootstrap(db)
        tiers = export.get("tiers")
        if not tiers:
            # Older exports have no tier map; use the registry entries of the same names.
            entries = {m.name: m.tier for m in db.execute(select(ModelEntry)).scalars()}
            missing = [m for m in export["models"] if m not in entries]
            if missing:
                raise SystemExit(f"{args.path} has no tier map and {missing} are not in the registry.")
            tiers = {m: entries[m] for m in export["models"]}
        state = dict(export["arms"])
        try:
            state["arms"], renames = remap_arms_to_slots(db, state["arms"], tiers)
        except TierError as exc:
            raise SystemExit(str(exc))
        for old, new in renames.items():
            print(f"  {tiers[old]:6} weights trained as {old} -> slot {new}")
        arms = ArmSet.from_json(state)
        version = learner_state.save_arms(
            db, "frozen", arms,
            note=f"imported from {args.path} (trained v{export['version']}, quality={export.get('quality_source')})"[:255],
        )
        db.commit()
        print(f"Imported as frozen router v{version}: tiers {sorted(set(tiers.values()))}, "
              f"quality target {export.get('quality_source')}")
        print("Reward settings it was trained with (set the same in Settings -> Policy):", export["reward"])
        if args.warm_start:
            print("Warm-started:", learner_state.warm_start(db))


if __name__ == "__main__":
    main()
