"""Superadmin policy controls, learner management and the confidential audit log."""

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.policy_config import ENTITY_TYPES, PolicyConfig, load_policy, save_policy
from ..core.routing import state as learner_state
from ..db import get_db
from ..deps import require_admin, require_superadmin
from ..models import ConfidentialEvent, PolicyChange, PolicyState, User, utcnow

router = APIRouter(prefix="/api", tags=["policy"])


@router.get("/policy", response_model=PolicyConfig)
def get_policy(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    return load_policy(db)


@router.put("/policy", response_model=PolicyConfig)
def put_policy(body: PolicyConfig, actor: User = Depends(require_superadmin), db: Session = Depends(get_db)):
    unknown = set(body.blocking_entity_types) - set(ENTITY_TYPES)
    if unknown:
        raise HTTPException(422, f"Unknown entity types: {sorted(unknown)}")
    if body.eps_end > body.eps_start:
        raise HTTPException(422, "eps_end must not exceed eps_start")
    total = body.weights.quality + body.weights.cost + body.weights.latency
    if abs(total - 1.0) > 1e-6:
        raise HTTPException(422, "Reward weights must sum to 1")
    return save_policy(db, body, actor)


@router.get("/policy/history")
def policy_history(limit: int = Query(100, le=500), _: User = Depends(require_admin), db: Session = Depends(get_db)):
    rows = db.execute(select(PolicyChange).order_by(PolicyChange.created_at.desc()).limit(limit)).scalars().all()
    return [
        {"id": r.id, "created_at": r.created_at, "actor": r.actor_email, "target": r.target, "changes": r.changes}
        for r in rows
    ]


# ---------------------------------------------------------------- learner state


@router.get("/policy/learner")
def learner_versions(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    rows = db.execute(
        select(PolicyState).order_by(PolicyState.name, PolicyState.version.desc()).limit(200)
    ).scalars().all()
    return [
        {
            "name": r.name,
            "version": r.version,
            "active": r.active,
            "note": r.note,
            "created_at": r.created_at,
            "n_scored": r.state.get("n_scored", 0),
            "feature_dim": r.state.get("d"),
            "arms": {name: arm.get("n", 0) for name, arm in r.state.get("arms", {}).items()},
        }
        for r in rows
    ]


class RollbackIn(BaseModel):
    name: str
    version: int


@router.post("/policy/learner/rollback")
def learner_rollback(body: RollbackIn, _: User = Depends(require_superadmin), db: Session = Depends(get_db)):
    if not learner_state.rollback(db, body.name, body.version):
        raise HTTPException(404, "No such learner version")
    return {"ok": True}


@router.post("/policy/learner/warm-start")
def learner_warm_start(_: User = Depends(require_superadmin), db: Session = Depends(get_db)):
    done = learner_state.warm_start(db)
    if not done:
        raise HTTPException(409, "No frozen router has been trained yet (run scripts/train_frozen.py)")
    return {"initialised": done}


@router.post("/policy/learner/apply")
def learner_apply(_: User = Depends(require_superadmin), db: Session = Depends(get_db)):
    """Apply scored outcomes now instead of waiting for a full batch."""
    return {"applied": learner_state.apply_pending_updates(db, load_policy(db), force=True)}


# ------------------------------------------------------------------- audit log


@router.get("/audit/confidential")
def confidential_audit(
    days: int = Query(30, ge=1, le=365),
    decision: str | None = None,
    user_email: str | None = None,
    left_boundary: bool | None = None,
    limit: int = Query(200, le=1000),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    q = select(ConfidentialEvent).where(ConfidentialEvent.created_at >= utcnow() - timedelta(days=days))
    if decision:
        q = q.where(ConfidentialEvent.decision == decision)
    if user_email:
        q = q.where(ConfidentialEvent.user_email == user_email.lower().strip())
    if left_boundary is not None:
        q = q.where(ConfidentialEvent.left_trusted_boundary.is_(left_boundary))
    rows = db.execute(q.order_by(ConfidentialEvent.created_at.desc()).limit(limit)).scalars().all()
    return [
        {
            "id": r.id,
            "created_at": r.created_at,
            "user_email": r.user_email,
            "source": r.source,
            "privacy_mode": r.privacy_mode,
            "triggers": r.triggers,
            "entity_types": r.entity_types,
            "decision": r.decision,
            "decision_reason": r.decision_reason,
            "consent_given": r.consent_given,
            "destination_model": r.destination_model,
            "left_trusted_boundary": r.left_trusted_boundary,
            "payload_sha256": r.payload_sha256,
            "masked_preview": r.masked_preview,
            "routing_event_id": r.routing_event_id,
        }
        for r in rows
    ]
