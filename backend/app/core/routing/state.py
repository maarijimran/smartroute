"""Versioned persistence of learner state and the batched online update.

Updates are applied in batches of `update_batch_size` scored outcomes and use only
the outcome of the model that was actually selected (bandit feedback). Every update
writes a new version; earlier versions stay in the table so the superadmin can roll
back, and the fixed rules remain available as a separate policy at all times.
"""

from __future__ import annotations

import logging
import threading

import numpy as np
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ...models import PolicyState, RoutingEvent
from ..policy_config import PolicyConfig
from ..reward import FAILURE_REWARD
from .arms import ArmSet

log = logging.getLogger(__name__)

LEARNERS = ("bandit", "linucb")
_cache: dict[str, tuple[int, ArmSet]] = {}
_lock = threading.Lock()


def _active_row(db: Session, name: str) -> PolicyState | None:
    return db.execute(
        select(PolicyState).where(PolicyState.name == name, PolicyState.active.is_(True)).order_by(
            PolicyState.version.desc()
        )
    ).scalars().first()


def load_arms(db: Session, name: str, d: int, lam: float, feature_version: str = "default") -> tuple[ArmSet, int]:
    """Returns (arms, version). Version 0 means nothing has been stored yet.
    A stored state whose feature dimension no longer matches is ignored (cold start)."""
    row = _active_row(db, name)
    if row is None:
        return ArmSet(d, lam, feature_version), 0
    with _lock:
        cached = _cache.get(name)
        if cached and cached[0] == row.version:
            arms = cached[1]
        else:
            arms = ArmSet.from_json(row.state)
            _cache[name] = (row.version, arms)
    if arms.d != d:
        log.warning("Stored %s state has d=%s but features have d=%s; cold start", name, arms.d, d)
        return ArmSet(d, lam, feature_version), row.version
    return arms, row.version


def save_arms(db: Session, name: str, arms: ArmSet, note: str = "") -> int:
    latest = db.execute(
        select(PolicyState.version).where(PolicyState.name == name).order_by(PolicyState.version.desc())
    ).scalars().first()
    version = (latest or 0) + 1
    db.execute(update(PolicyState).where(PolicyState.name == name).values(active=False))
    db.add(PolicyState(name=name, version=version, active=True, state=arms.to_json(), note=note))
    db.flush()
    with _lock:
        _cache[name] = (version, arms)
    return version


def rollback(db: Session, name: str, version: int) -> bool:
    row = db.execute(
        select(PolicyState).where(PolicyState.name == name, PolicyState.version == version)
    ).scalars().first()
    if row is None:
        return False
    db.execute(update(PolicyState).where(PolicyState.name == name).values(active=False))
    row.active = True
    db.commit()
    with _lock:
        _cache.pop(name, None)
    return True


def warm_start(db: Session, source: str = "frozen", targets: tuple[str, ...] = LEARNERS) -> list[str]:
    """Initialise the online learners from the frozen router's weights (OrcaRouter recipe)."""
    row = _active_row(db, source)
    if row is None:
        return []
    done = []
    for name in targets:
        arms = ArmSet.from_json(row.state)
        arms.n_scored = 0
        save_arms(db, name, arms, note=f"warm start from {source} v{row.version}")
        done.append(name)
    db.commit()
    return done


def learner_target(event: RoutingEvent, cfg: PolicyConfig) -> float | None:
    """What the arm regresses on. Failures enter as -1 in both modes so unreliable
    arms are penalised even though they produced no quality score."""
    if event.reward is None:
        return None
    if event.reward <= FAILURE_REWARD:
        return FAILURE_REWARD
    return event.quality if cfg.reward_mode == "split" else event.reward


def apply_pending_updates(db: Session, cfg: PolicyConfig, force: bool = False) -> int:
    """Feeds scored, not-yet-applied outcomes to the learners once a full batch exists."""
    events = db.execute(
        select(RoutingEvent)
        .where(
            RoutingEvent.reward.is_not(None),
            RoutingEvent.reward_applied.is_(False),
            RoutingEvent.chosen_model.is_not(None),
            # Benchmark runs must never train the live learner: they include the
            # held-out test split, and the learner is evaluated on it by replay.
            RoutingEvent.source != "eval",
        )
        .order_by(RoutingEvent.created_at)
        .limit(2000)
        .with_for_update()
    ).scalars().all()
    if not events or (len(events) < cfg.update_batch_size and not force):
        return 0
    usable = [(e, learner_target(e, cfg)) for e in events if e.features]
    usable = [(e, y) for e, y in usable if y is not None]
    if usable:
        d = len(usable[0][0].features)
        for name in LEARNERS:
            arms, _ = load_arms(db, name, d, cfg.ridge_lambda)
            arms = arms.copy()  # never mutate the instance other requests are reading
            gamma = cfg.linucb_gamma if name == "linucb" else 1.0
            applied = 0
            for event, y in usable:
                if len(event.features) != arms.d:
                    continue
                arms.arm(event.chosen_model).update(np.array(event.features, dtype=float), y, gamma)
                applied += 1
            arms.n_scored += applied
            save_arms(db, name, arms, note=f"batch update with {applied} scored outcomes")
    _update_model_cards(db, cfg, [e for e in events if e.reward is not None])
    for event in events:
        event.reward_applied = True
    db.commit()
    return len(events)


def _update_model_cards(db: Session, cfg: PolicyConfig, events: list[RoutingEvent]) -> None:
    """Router v2: the answering model's card learns from each scored answer.

    Target: the answer's quality in [0, 1]; a failure counts as 0. Only features recorded
    under the current query model are used (an older query model's features differ)."""
    from ...models import EventQueryFeatures
    from .router_v2 import STATUS_CALIBRATED, STATUS_LEARNING, get_router_v2, load_card, save_card

    router = get_router_v2()
    if router is None or not events:
        return
    by_id = {e.id: e for e in events}
    rows = db.execute(
        select(EventQueryFeatures).where(
            EventQueryFeatures.event_id.in_(list(by_id)),
            EventQueryFeatures.card_applied.is_(False),
            EventQueryFeatures.query_model_version == router.version,
        )
    ).scalars().all()
    grouped: dict[str, list[tuple[list[float], float]]] = {}
    for row in rows:
        event = by_id[row.event_id]
        if not row.model_key:
            continue
        failed = event.reward is not None and event.reward <= FAILURE_REWARD
        y = 0.0 if failed else event.quality
        if y is None:
            continue
        grouped.setdefault(row.model_key, []).append((row.xq, float(min(max(y, 0.0), 1.0))))
        row.card_applied = True
    for key, items in grouped.items():
        card, status = load_card(db, router, key)
        card = card.update(router.qm, np.array([x for x, _ in items]), np.array([y for _, y in items]))
        save_card(db, router, key, card, STATUS_CALIBRATED if status == STATUS_CALIBRATED else STATUS_LEARNING)
