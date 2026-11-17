"""Bounded retention (proposal 5d).

- Chat content and uploaded documents expire after a period of inactivity unless
  the user opted in to keeping them.
- Routing metadata and the cost ledger are kept for a limited number of days.
- The confidential audit log has its own, longer retention.
- Evaluation runs (source "eval") are never purged automatically, because the
  experiments need them until the analysis is finished.
"""

import logging
from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..models import (
    Attempt,
    ChatMessage,
    ChatSession,
    ConfidentialEvent,
    Document,
    DocumentChunk,
    Feedback,
    RoutingEvent,
    utcnow,
)
from .policy_config import load_policy

log = logging.getLogger(__name__)


def run_retention(db: Session) -> dict[str, int]:
    cfg = load_policy(db)
    now = utcnow()
    content_cutoff = now - timedelta(minutes=cfg.session_expiry_minutes)
    metadata_cutoff = now - timedelta(days=cfg.metadata_retention_days)
    audit_cutoff = now - timedelta(days=cfg.audit_retention_days)
    removed = {}

    sessions = db.execute(
        select(ChatSession.id).where(ChatSession.persist.is_(False), ChatSession.last_active_at < content_cutoff)
    ).scalars().all()
    if sessions:
        db.execute(delete(ChatMessage).where(ChatMessage.session_id.in_(sessions)))
        db.execute(delete(ChatSession).where(ChatSession.id.in_(sessions)))
    removed["sessions"] = len(sessions)

    documents = db.execute(
        select(Document.id).where(Document.persist.is_(False), Document.last_used_at < content_cutoff)
    ).scalars().all()
    if documents:
        db.execute(delete(DocumentChunk).where(DocumentChunk.document_id.in_(documents)))
        db.execute(delete(Document).where(Document.id.in_(documents)))
    removed["documents"] = len(documents)

    old_events = db.execute(
        select(RoutingEvent.id).where(RoutingEvent.created_at < metadata_cutoff, RoutingEvent.source != "eval")
    ).scalars().all()
    if old_events:
        db.execute(delete(Attempt).where(Attempt.event_id.in_(old_events)))
        db.execute(delete(Feedback).where(Feedback.event_id.in_(old_events)))
        db.execute(delete(RoutingEvent).where(RoutingEvent.id.in_(old_events)))
    removed["routing_events"] = len(old_events)

    result = db.execute(delete(ConfidentialEvent).where(ConfidentialEvent.created_at < audit_cutoff))
    removed["audit_events"] = result.rowcount or 0
    db.commit()
    if any(removed.values()):
        log.info("retention removed %s", removed)
    return removed
