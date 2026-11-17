"""Analytics for the dashboard.

Measured values (tokens, cost, latency from real responses) are reported separately
from estimates (what the same traffic would have cost on the strongest model).
"""

from collections import defaultdict
from datetime import timedelta

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..models import ROLE_USER, ConfidentialEvent, ModelEntry, RoutingEvent, User, utcnow

router = APIRouter(prefix="/api/analytics", tags=["analytics"])
ANSWERED = ("ok", "truncated")


def _scope(user: User, scope: str) -> str | None:
    """Returns the user id to filter by, or None for organisation-wide."""
    if scope == "all":
        if user.role == ROLE_USER:
            raise HTTPException(403, "Organisation-wide analytics need an admin role")
        return None
    return user.id


@router.get("/summary")
def summary(
    days: int = Query(30, ge=1, le=365),
    scope: str = Query("mine", pattern="^(mine|all)$"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    owner = _scope(user, scope)
    since = utcnow() - timedelta(days=days)
    q = select(RoutingEvent).where(RoutingEvent.created_at >= since, RoutingEvent.status != "attempt_failed")
    if owner:
        q = q.where(RoutingEvent.user_id == owner)
    events = db.execute(q).scalars().all()

    models = {m.name: m for m in db.execute(select(ModelEntry)).scalars()}
    strong = [m for m in models.values() if m.tier == "strong" and m.enabled]
    reference = max(strong, key=lambda m: m.price_in_per_mtok + m.price_out_per_mtok) if strong else None

    by_status: dict[str, int] = defaultdict(int)
    by_model: dict[str, dict] = {}
    daily: dict[str, dict] = {}
    latencies, overheads = [], []
    measured_cost = est_strong_cost = 0.0
    answered = local_answers = 0

    for e in events:
        by_status[e.status] += 1
        day = e.created_at.strftime("%Y-%m-%d")
        d = daily.setdefault(day, {"date": day, "requests": 0, "cost_usd": 0.0, "est_strong_only_usd": 0.0})
        d["requests"] += 1
        d["cost_usd"] += e.cost_usd
        measured_cost += e.cost_usd
        overheads.append(e.routing_overhead_ms)
        if e.status not in ANSWERED or not e.chosen_model:
            continue
        answered += 1
        latencies.append(e.latency_ms)
        m = by_model.setdefault(
            e.chosen_model,
            {"model": e.chosen_model, "requests": 0, "cost_usd": 0.0, "latency_sum": 0.0, "quality_sum": 0.0, "rated": 0},
        )
        m["requests"] += 1
        m["cost_usd"] += e.cost_usd
        m["latency_sum"] += e.latency_ms
        if e.quality is not None:
            m["quality_sum"] += e.quality
            m["rated"] += 1
        entry = models.get(e.chosen_model)
        if entry is not None and entry.is_local:
            local_answers += 1
        if reference is not None:
            est = (e.in_tokens * reference.price_in_per_mtok + e.out_tokens * reference.price_out_per_mtok) / 1e6
            est_strong_cost += est
            d["est_strong_only_usd"] += est

    model_rows = []
    for m in by_model.values():
        entry = models.get(m["model"])
        model_rows.append(
            {
                "model": m["model"],
                "tier": entry.tier if entry else None,
                "requests": m["requests"],
                "cost_usd": round(m["cost_usd"], 6),
                "avg_latency_ms": round(m["latency_sum"] / m["requests"], 1),
                "avg_quality": round(m["quality_sum"] / m["rated"], 3) if m["rated"] else None,
                "rated": m["rated"],
            }
        )

    cq = select(ConfidentialEvent).where(ConfidentialEvent.created_at >= since)
    if owner:
        cq = cq.where(ConfidentialEvent.user_id == owner)
    confidential = db.execute(cq).scalars().all()

    return {
        "days": days,
        "scope": scope,
        "measured": {
            "requests": len(events),
            "answered": answered,
            "by_status": dict(by_status),
            "cost_usd": round(measured_cost, 6),
            "latency_p50_ms": round(float(np.percentile(latencies, 50)), 1) if latencies else None,
            "latency_p95_ms": round(float(np.percentile(latencies, 95)), 1) if latencies else None,
            "routing_overhead_p50_ms": round(float(np.percentile(overheads, 50)), 2) if overheads else None,
            "local_share": round(local_answers / answered, 4) if answered else None,
            "cache_hits": by_status.get("cache_hit", 0),
        },
        "estimated": {
            "reference_model": reference.name if reference else None,
            "strong_only_cost_usd": round(est_strong_cost, 6) if reference else None,
            "saving_vs_strong_only": round(1 - measured_cost / est_strong_cost, 4) if est_strong_cost > 0 else None,
            "note": "Estimate: the same measured token counts priced at the reference model. "
            "It ignores that a stronger model may write answers of a different length.",
        },
        "privacy": {
            "confidential_requests": len(confidential),
            "cloud_blocked": sum(1 for c in confidential if c.decision == "cloud_blocked"),
            "sent_to_cloud_with_consent": sum(1 for c in confidential if c.left_trusted_boundary),
        },
        "by_model": sorted(model_rows, key=lambda r: r["requests"], reverse=True),
        "daily": [
            {**d, "cost_usd": round(d["cost_usd"], 6), "est_strong_only_usd": round(d["est_strong_only_usd"], 6)}
            for d in sorted(daily.values(), key=lambda d: d["date"])
        ],
    }


@router.get("/events")
def events(
    limit: int = Query(50, ge=1, le=500),
    scope: str = Query("mine", pattern="^(mine|all)$"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    owner = _scope(user, scope)
    q = select(RoutingEvent).where(RoutingEvent.status != "attempt_failed")
    if owner:
        q = q.where(RoutingEvent.user_id == owner)
    rows = db.execute(q.order_by(RoutingEvent.created_at.desc()).limit(limit)).scalars().all()
    return [
        {
            "id": e.id,
            "created_at": e.created_at,
            "source": e.source,
            "task": e.task,
            "privacy_mode": e.privacy_mode,
            "sensitive": e.sensitive,
            "status": e.status,
            "model": e.chosen_model,
            "policy": e.policy_name,
            "policy_version": e.policy_version,
            "propensity": e.propensity,
            "explored": e.explored,
            "explanation": e.explanation,
            "eligible": e.eligible,
            "exclusions": e.exclusions,
            "in_tokens": e.in_tokens,
            "out_tokens": e.out_tokens,
            "cost_usd": e.cost_usd,
            "latency_ms": e.latency_ms,
            "ttft_ms": e.ttft_ms,
            "routing_overhead_ms": e.routing_overhead_ms,
            "attempts": e.attempts,
            "fallback_from": e.fallback_from,
            "quality": e.quality,
            "reward": e.reward,
        }
        for e in rows
    ]
