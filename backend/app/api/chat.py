"""Phase 1: the chat interface API. Answers stream as server-sent events."""

import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..core import pipeline
from ..core.policy_config import load_policy
from ..core.reward import human_score
from ..db import get_db, session_scope
from ..deps import get_current_user
from ..models import ROLE_USER, ChatMessage, ChatSession, Document, Feedback, RoutingEvent, User, utcnow
from ..schemas import ChatIn, FeedbackIn, MessageOut, SessionIn, SessionOut, SessionUpdate

router = APIRouter(prefix="/api", tags=["chat"])


def _own_session(db: Session, session_id: str, user: User) -> ChatSession:
    session = db.get(ChatSession, session_id)
    if session is None or session.user_id != user.id:
        raise HTTPException(404, "Chat not found")
    return session


def _own_documents(db: Session, ids: list[str], user: User) -> list[str]:
    if not ids:
        return []
    owned = set(
        db.execute(select(Document.id).where(Document.id.in_(ids), Document.user_id == user.id)).scalars().all()
    )
    missing = [i for i in ids if i not in owned]
    if missing:
        raise HTTPException(404, "One or more documents were not found (they may have expired)")
    return ids


@router.get("/chat/sessions", response_model=list[SessionOut])
def list_sessions(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.execute(
        select(ChatSession).where(ChatSession.user_id == user.id).order_by(ChatSession.last_active_at.desc()).limit(100)
    ).scalars().all()


@router.post("/chat/sessions", response_model=SessionOut, status_code=201)
def create_session(body: SessionIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    session = ChatSession(
        user_id=user.id,
        title=body.title[:255],
        privacy_mode=body.privacy_mode,
        document_ids=_own_documents(db, body.document_ids, user),
        persist=body.persist,
    )
    db.add(session)
    db.commit()
    return session


@router.patch("/chat/sessions/{session_id}", response_model=SessionOut)
def update_session(
    session_id: str, body: SessionUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    session = _own_session(db, session_id, user)
    if body.title is not None:
        session.title = body.title[:255]
    if body.privacy_mode is not None:
        session.privacy_mode = body.privacy_mode
    if body.document_ids is not None:
        session.document_ids = _own_documents(db, body.document_ids, user)
    if body.persist is not None:
        session.persist = body.persist
    db.commit()
    return session


@router.get("/chat/sessions/{session_id}/messages", response_model=list[MessageOut])
def list_messages(session_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _own_session(db, session_id, user)
    return db.execute(
        select(ChatMessage).where(ChatMessage.session_id == session_id).order_by(ChatMessage.created_at)
    ).scalars().all()


@router.delete("/chat/sessions/{session_id}", status_code=204)
def delete_session(session_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    session = _own_session(db, session_id, user)
    db.execute(delete(ChatMessage).where(ChatMessage.session_id == session.id))
    db.delete(session)
    db.commit()


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"


@router.post("/chat/sessions/{session_id}/messages")
def send_message(session_id: str, body: ChatIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    session = _own_session(db, session_id, user)
    cfg = load_policy(db)
    if body.model and user.role == ROLE_USER and not cfg.users_may_pin_model:
        raise HTTPException(403, "Choosing a specific model is disabled by your administrator")

    stored = db.execute(
        select(ChatMessage).where(ChatMessage.session_id == session.id).order_by(ChatMessage.created_at)
    ).scalars().all()
    # Refusals and failed answers are shown in the chat but never replayed to a model.
    history = [
        {"role": m.role, "content": m.content}
        for m in stored
        if m.role == "user" or (m.role == "assistant" and m.meta.get("status") in ("ok", "cache_hit"))
    ]
    messages = history + [{"role": "user", "content": body.content}]
    # Passages behind the previous answer, so a follow-up can keep using them.
    last_answer = next(
        (m for m in reversed(stored) if m.role == "assistant" and m.meta.get("status") in ("ok", "cache_hit")), None
    )
    prior_chunks = (
        [s["chunk_id"] for s in (last_answer.meta.get("sources") or []) if s.get("chunk_id")] if last_answer else []
    )

    db.add(ChatMessage(session_id=session.id, role="user", content=body.content))
    if not stored and session.title == "New chat":
        session.title = body.content.strip()[:60]
    session.last_active_at = utcnow()
    db.commit()

    request = pipeline.RouteRequest.for_user(
        user,
        messages,
        source="chat",
        privacy_mode=session.privacy_mode,
        consent=body.consent,
        confidential_label=body.confidential,
        session_confidential=session.confidential,
        document_ids=list(session.document_ids or []),
        prior_chunk_ids=prior_chunks,
        pinned_model=body.model,
        session_id=session.id,
    )
    plan = pipeline.prepare(db, request)
    if plan.assessment.sensitive and not session.confidential:
        session.confidential = True  # the label propagates to everything derived later
        db.commit()

    def stream():
        yield _sse(
            {
                "type": "route",
                "event_id": plan.event_id,
                "model": plan.decision.arm if plan.decision else None,
                "policy": plan.policy_name,
                "explanation": plan.decision.explanation if plan.decision else plan.abstain_reason,
                "sensitive": plan.assessment.sensitive,
                "entity_types": plan.assessment.entity_types,
            }
        )
        outcome = None
        for kind, item in pipeline.run(plan):
            if kind == "delta":
                yield _sse({"type": "delta", "text": item})
            else:
                outcome = item
        meta = outcome.public()
        text = outcome.text or plan.abstain_reason or outcome.error or "The request could not be completed."
        with session_scope() as own:
            own.add(
                ChatMessage(session_id=plan.req.session_id, role="assistant", content=text, event_id=outcome.event_id, meta=meta)
            )
            live = own.get(ChatSession, plan.req.session_id)
            if live is not None:
                live.last_active_at = utcnow()
        yield _sse({"type": "done", "text": text, "meta": meta})

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/feedback")
def give_feedback(body: FeedbackIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    event = db.get(RoutingEvent, body.event_id)
    if event is None or (event.user_id != user.id and user.role == ROLE_USER):
        raise HTTPException(404, "Response not found")
    if event.status != "ok":
        raise HTTPException(409, "Only completed answers can be rated")
    db.add(Feedback(user_id=user.id, **body.model_dump()))
    score = human_score(body.correctness, body.relevance, body.completeness, body.usefulness)
    updated = pipeline.record_quality(db, body.event_id, human=score)
    return {"quality": updated.quality, "reward": updated.reward, "quality_source": updated.quality_source}
