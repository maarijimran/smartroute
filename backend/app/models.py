"""Database tables.

All timestamps are naive UTC so behaviour is identical on SQLite (tests) and PostgreSQL.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base

ROLE_SUPERADMIN = "superadmin"
ROLE_ADMIN = "admin"
ROLE_USER = "user"
ROLES = (ROLE_SUPERADMIN, ROLE_ADMIN, ROLE_USER)


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def new_id() -> str:
    return uuid.uuid4().hex


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), default="")
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), default=ROLE_USER)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # None = inherit the organisation default set by the superadmin.
    allow_confidential_cloud: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=None)
    monthly_budget_usd: Mapped[float | None] = mapped_column(Float, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class PolicySettings(Base):
    """Single row (id=1) holding the organisation-wide PolicyConfig as JSON."""

    __tablename__ = "policy_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_by: Mapped[str | None] = mapped_column(String(32), nullable=True)


class PolicyChange(Base):
    """Who changed which policy field, from what to what."""

    __tablename__ = "policy_changes"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    actor_id: Mapped[str] = mapped_column(String(32))
    actor_email: Mapped[str] = mapped_column(String(255))
    target: Mapped[str] = mapped_column(String(64))  # "policy" or "user:<id>"
    changes: Mapped[dict] = mapped_column(JSON)  # {field: [old, new]}


class ModelEntry(Base):
    """Model registry: one row per routable model option."""

    __tablename__ = "model_entries"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(64), unique=True, index=True)  # stable arm name
    display_name: Mapped[str] = mapped_column(String(128), default="")
    vendor: Mapped[str] = mapped_column(String(32))  # see app.core.providers.VENDORS
    model_id: Mapped[str] = mapped_column(String(128))  # provider model string or Azure deployment
    tier: Mapped[str] = mapped_column(String(16))  # "local" | "cheap" | "strong"
    is_local: Mapped[bool] = mapped_column(Boolean, default=False)
    base_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    context_window: Mapped[int] = mapped_column(Integer, default=8192)
    max_output_tokens: Mapped[int] = mapped_column(Integer, default=2048)
    price_in_per_mtok: Mapped[float] = mapped_column(Float, default=0.0)
    price_out_per_mtok: Mapped[float] = mapped_column(Float, default=0.0)
    price_updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    params: Mapped[dict] = mapped_column(JSON, default=dict)  # adapter options, see providers
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # Live statistics
    latency_ewma_ms: Mapped[float] = mapped_column(Float, default=3000.0)
    unhealthy_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ProviderCredential(Base):
    """A cloud API key. user_id NULL means a platform key managed by the superadmin."""

    __tablename__ = "provider_credentials"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("users.id"), nullable=True, index=True)
    vendor: Mapped[str] = mapped_column(String(32), index=True)
    label: Mapped[str] = mapped_column(String(128), default="")
    base_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    api_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    encrypted_key: Mapped[str] = mapped_column(Text)
    key_hint: Mapped[str] = mapped_column(String(8), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ApiKey(Base):
    """SmartRoute API key handed to a developer for the /v1 router API."""

    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(String(32), ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(128), default="")
    prefix: Mapped[str] = mapped_column(String(16))
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    default_privacy_mode: Mapped[str] = mapped_column(String(16), default="cloud_allowed")
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(String(32), ForeignKey("users.id"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    label: Mapped[str] = mapped_column(String(16), default="confidential")  # "public" | "confidential"
    pages: Mapped[int] = mapped_column(Integer, default=0)
    n_chunks: Mapped[int] = mapped_column(Integer, default=0)
    sha256: Mapped[str] = mapped_column(String(64))
    ocr_pages: Mapped[int] = mapped_column(Integer, default=0)  # pages read by OCR
    persist: Mapped[bool] = mapped_column(Boolean, default=False)  # opt-in: keep beyond the session expiry
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_used_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    document_id: Mapped[str] = mapped_column(String(32), ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    idx: Mapped[int] = mapped_column(Integer)
    page: Mapped[int] = mapped_column(Integer, default=0)
    text: Mapped[str] = mapped_column(Text)


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(String(32), ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(255), default="New chat")
    privacy_mode: Mapped[str] = mapped_column(String(16), default="cloud_allowed")
    document_ids: Mapped[list] = mapped_column(JSON, default=list)
    # Sticky label: once confidential content entered the session, everything derived
    # from it (history, later answers) is treated as confidential too.
    confidential: Mapped[bool] = mapped_column(Boolean, default=False)
    persist: Mapped[bool] = mapped_column(Boolean, default=False)  # opt-in history retention
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_active_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(String(32), ForeignKey("chat_sessions.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    event_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class RoutingEvent(Base):
    """One routed request. Holds metadata only, never prompt or answer text."""

    __tablename__ = "routing_events"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    source: Mapped[str] = mapped_column(String(16))  # "chat" | "api" | "eval"
    session_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    api_key_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    task: Mapped[str] = mapped_column(String(16), default="chat")
    privacy_mode: Mapped[str] = mapped_column(String(16))
    sensitive: Mapped[bool] = mapped_column(Boolean, default=False)
    features: Mapped[list] = mapped_column(JSON, default=list)
    eligible: Mapped[list] = mapped_column(JSON, default=list)
    exclusions: Mapped[dict] = mapped_column(JSON, default=dict)  # {model: reason}
    policy_name: Mapped[str] = mapped_column(String(32), default="")
    policy_version: Mapped[int] = mapped_column(Integer, default=0)
    chosen_model: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    served_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    propensity: Mapped[float | None] = mapped_column(Float, nullable=True)
    explored: Mapped[bool] = mapped_column(Boolean, default=False)
    explanation: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), index=True)
    est_in_tokens: Mapped[int] = mapped_column(Integer, default=0)
    est_out_tokens: Mapped[int] = mapped_column(Integer, default=0)
    in_tokens: Mapped[int] = mapped_column(Integer, default=0)
    out_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)  # all attempts of this request
    latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    ttft_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    routing_overhead_ms: Mapped[float] = mapped_column(Float, default=0.0)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    fallback_from: Mapped[str | None] = mapped_column(String(64), nullable=True)
    context_compressed: Mapped[bool] = mapped_column(Boolean, default=False)
    cache_hit: Mapped[bool] = mapped_column(Boolean, default=False)
    human_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    auto_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    quality: Mapped[float | None] = mapped_column(Float, nullable=True)
    quality_source: Mapped[str | None] = mapped_column(String(16), nullable=True)
    reward: Mapped[float | None] = mapped_column(Float, nullable=True)
    reward_applied: Mapped[bool] = mapped_column(Boolean, default=False)
    confidential_event_id: Mapped[str | None] = mapped_column(String(32), nullable=True)

    __table_args__ = (Index("ix_events_pending_reward", "reward_applied", "created_at"),)


class Attempt(Base):
    """Cost ledger: one row per model call, including retries and scoring calls."""

    __tablename__ = "attempts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    event_id: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    model_name: Mapped[str] = mapped_column(String(64))
    purpose: Mapped[str] = mapped_column(String(16), default="answer")  # answer|retry|judge|benchmark
    credential_scope: Mapped[str] = mapped_column(String(16), default="local")  # local|user|platform
    status: Mapped[str] = mapped_column(String(16))
    in_tokens: Mapped[int] = mapped_column(Integer, default=0)
    out_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class Feedback(Base):
    __tablename__ = "feedback"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    event_id: Mapped[str] = mapped_column(String(32), index=True)
    user_id: Mapped[str] = mapped_column(String(32))
    correctness: Mapped[int] = mapped_column(Integer)
    relevance: Mapped[int] = mapped_column(Integer)
    completeness: Mapped[int] = mapped_column(Integer)
    usefulness: Mapped[int] = mapped_column(Integer)
    comment: Mapped[str] = mapped_column(Text, default="")


class ConfidentialEvent(Base):
    """Audit trail for every request that carried confidential content.

    Stores metadata, detected entity types, a content hash and a masked preview.
    The full query text is deliberately not stored.
    """

    __tablename__ = "confidential_events"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    user_email: Mapped[str] = mapped_column(String(255))
    source: Mapped[str] = mapped_column(String(16))
    privacy_mode: Mapped[str] = mapped_column(String(16))
    triggers: Mapped[list] = mapped_column(JSON, default=list)  # why it counted as confidential
    entity_types: Mapped[list] = mapped_column(JSON, default=list)
    decision: Mapped[str] = mapped_column(String(32))  # cloud_allowed | cloud_blocked
    decision_reason: Mapped[str] = mapped_column(String(64))
    consent_given: Mapped[bool] = mapped_column(Boolean, default=False)
    destination_model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    left_trusted_boundary: Mapped[bool] = mapped_column(Boolean, default=False)
    payload_sha256: Mapped[str] = mapped_column(String(64))
    masked_preview: Mapped[str] = mapped_column(Text, default="")
    routing_event_id: Mapped[str | None] = mapped_column(String(32), nullable=True)


class PolicyState(Base):
    """Versioned learner state (ridge arms). Old versions are kept for rollback."""

    __tablename__ = "policy_states"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(32), index=True)  # "bandit" | "linucb" | "frozen"
    version: Mapped[int] = mapped_column(Integer)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    state: Mapped[dict] = mapped_column(JSON)
    note: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    __table_args__ = (Index("ix_policy_state_active", "name", "active"),)


class ModelCardRow(Base):
    """Router v2: what is known about one model's ability (core/routing/irt.py).

    Keyed by model identity (provider + model ID), not by tier, so a model keeps its card
    when it moves between tiers or comes back later. A card is only valid for the query
    model it was fitted with (`query_model_version`)."""

    __tablename__ = "model_cards"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    model_key: Mapped[str] = mapped_column(String(200), index=True)  # "<vendor>:<model_id>"
    query_model_version: Mapped[str] = mapped_column(String(64), index=True)
    card: Mapped[dict] = mapped_column(JSON)  # ModelCard.to_json()
    status: Mapped[str] = mapped_column(String(16), default="learning")  # calibrating | calibrated | learning
    calibration: Mapped[dict] = mapped_column(JSON, default=dict)  # items asked, uncertainty, cost, error
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    __table_args__ = (Index("ix_model_card_key_version", "model_key", "query_model_version", unique=True),)


class EventQueryFeatures(Base):
    """Router v2 features of a routed request, kept next to routing_events so ratings can
    update the answering model's card. Separate table: routing_events keeps its schema."""

    __tablename__ = "event_query_features"

    event_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    query_model_version: Mapped[str] = mapped_column(String(64))
    xq: Mapped[list] = mapped_column(JSON)
    model_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    card_applied: Mapped[bool] = mapped_column(Boolean, default=False)
