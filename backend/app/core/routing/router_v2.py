"""Router v2 runtime: the trained query model and the model cards.

The query model is trained on Kaggle (scripts/train_router_v2.py) and exported to
artifacts/router_v2.json together with the cards of the models it was trained on. Cards
for other models come from calibration (scripts/calibrate_tier.py, or the Calibrate
button) and from ratings, and live in the `model_cards` table.

Card lookup for a model, by "<vendor>:<model_id>":
  1. a card in the database fitted for this query model version
  2. a card from the artifact (the model was part of training)
  3. the prior: the average training model, with wide uncertainty ("uncalibrated")
"""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...config import get_settings
from ...models import ModelCardRow, utcnow
from . import qfeatures
from .irt import ModelCard, QueryModel

log = logging.getLogger(__name__)
ARTIFACT_NAME = "router_v2.json"

STATUS_TRAINED = "trained"  # part of the query model's training data
STATUS_CALIBRATED = "calibrated"
STATUS_CALIBRATING = "calibrating"
STATUS_LEARNING = "learning"  # updated from ratings only
STATUS_UNCALIBRATED = "uncalibrated"


def model_key(vendor: str, model_id: str) -> str:
    return f"{vendor}:{model_id}"


@dataclass
class RouterV2:
    version: str
    qm: QueryModel
    embedding_dim: int
    feature_version: str  # the features.json version whose PCA the embedding dimensions come from
    cards: dict[str, ModelCard] = field(default_factory=dict)  # trained models, by model key
    meta: dict = field(default_factory=dict)

    def compatible(self, extractor) -> bool:
        """The live feature extractor produces what this query model was trained on."""
        if self.embedding_dim != extractor.embedding_dim:
            return False
        if self.embedding_dim and self.feature_version != extractor.version:
            return False
        return len(self.qm.names) == len(qfeatures.NAMES) + self.embedding_dim

    def vector(self, base: list[float], baseline_x) -> list[float]:
        """v2 features: qfeatures values plus the embedding dimensions of the baseline vector."""
        tail = list(baseline_x[-self.embedding_dim:]) if self.embedding_dim else []
        return [float(v) for v in base] + [float(v) for v in tail]

    @classmethod
    def from_json(cls, d: dict) -> "RouterV2":
        return cls(
            version=str(d["version"]),
            qm=QueryModel.from_json(d["query_model"]),
            embedding_dim=int(d.get("embedding_dim", 0)),
            feature_version=str(d.get("feature_version", "default")),
            cards={k: ModelCard.from_json(v) for k, v in d.get("cards", {}).items()},
            meta=d.get("meta", {}),
        )

    def to_json(self) -> dict:
        return {
            "version": self.version, "query_model": self.qm.to_json(), "embedding_dim": self.embedding_dim,
            "feature_version": self.feature_version, "cards": {k: c.to_json() for k, c in self.cards.items()},
            "meta": self.meta,
        }


_lock = threading.Lock()
_loaded: tuple[float, RouterV2 | None] | None = None
_override: RouterV2 | None = None
_override_set = False


def artifact_path() -> str:
    settings = get_settings()
    return os.path.join(settings.artifacts_dir, ARTIFACT_NAME)


def get_router_v2() -> RouterV2 | None:
    """The trained Router v2, or None if it has not been trained yet. Reloads when the
    artifact file changes, so a new export takes effect without a restart."""
    global _loaded
    if _override_set:
        return _override
    path = artifact_path()
    if not os.path.exists(path):
        return None
    mtime = os.path.getmtime(path)
    with _lock:
        if _loaded is None or _loaded[0] != mtime:
            try:
                with open(path, encoding="utf-8") as fh:
                    _loaded = (mtime, RouterV2.from_json(json.load(fh)))
            except Exception:
                log.exception("could not load %s; Router v2 is unavailable", path)
                _loaded = (mtime, None)
        return _loaded[1]


def set_router_v2(router: RouterV2 | None, *, clear: bool = False) -> None:
    """Tests: use this router instead of the artifact (clear=True goes back to the file)."""
    global _override, _override_set
    _override, _override_set = router, not clear


def load_card(db: Session, router: RouterV2, key: str) -> tuple[ModelCard, str]:
    row = _row(db, router, key)
    if row is not None:
        return ModelCard.from_json(row.card), row.status
    if key in router.cards:
        return router.cards[key], STATUS_TRAINED
    return ModelCard.prior(router.qm), STATUS_UNCALIBRATED


def save_card(
    db: Session, router: RouterV2, key: str, card: ModelCard, status: str, calibration: dict | None = None
) -> ModelCardRow:
    row = _row(db, router, key)
    if row is None:
        row = ModelCardRow(model_key=key, query_model_version=router.version, card=card.to_json(), status=status,
                           calibration=calibration or {})
        db.add(row)
    else:
        row.card, row.status, row.updated_at = card.to_json(), status, utcnow()
        if calibration is not None:
            row.calibration = calibration
    db.flush()
    return row


def card_info(db: Session, router: RouterV2 | None, key: str) -> dict:
    """What the interface shows about a model's card."""
    if router is None:
        return {"status": "no_router"}
    card, status = load_card(db, router, key)
    row = _row(db, router, key)
    calib = dict(row.calibration) if row is not None else {}
    return {
        "status": status,
        "n": card.n,
        "level": round(float(card.theta[-1]), 3),
        "abilities": [round(float(v), 3) for v in card.theta[:-1]],
        "level_sd": round(float(card.cov[-1, -1]) ** 0.5, 3),
        "calibration": calib,
        "router_version": router.version,
    }


def _row(db: Session, router: RouterV2, key: str) -> ModelCardRow | None:
    return db.execute(
        select(ModelCardRow).where(
            ModelCardRow.model_key == key, ModelCardRow.query_model_version == router.version
        )
    ).scalars().first()
