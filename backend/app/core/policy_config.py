"""Organisation-wide policy that the superadmin controls at runtime.

Stored as one JSON document in `policy_settings`. Every change is recorded in
`policy_changes` with the actor, the old value and the new value.
"""

from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..models import PolicyChange, PolicySettings, User, utcnow

ENTITY_TYPES = ["PERSON", "EMAIL", "PHONE", "NATIONAL_ID", "CREDIT_CARD", "BANK_ACCOUNT", "ADDRESS", "OTHER"]


class RewardWeights(BaseModel):
    quality: float = 0.5
    cost: float = 0.3
    latency: float = 0.2


class PolicyConfig(BaseModel):
    # ---- Privacy (hard limits; never traded against quality or cost) ----
    cloud_enabled: bool = Field(True, description="Off = institutional local-only. Overrides every consent.")
    allow_confidential_cloud_default: bool = Field(
        False, description="May users send confidential content to cloud models? Per-user overrides win."
    )
    require_consent_for_confidential: bool = Field(
        True, description="Even permitted users must confirm consent on each confidential request."
    )
    blocking_entity_types: list[str] = Field(
        default_factory=lambda: list(ENTITY_TYPES),
        description="Detected entity types that make a request confidential.",
    )
    exempt_person_in_public_documents: bool = Field(
        True, description="Author names inside documents labelled public do not count as confidential."
    )
    audit_preview_chars: int = 160

    # ---- Access ----
    allow_self_registration: bool = False
    users_may_pin_model: bool = True

    # ---- Routing ----
    routing_policy: Literal["rules", "frozen", "bandit", "linucb", "calibrated", "calibrated_ucb"] = "rules"
    reward_mode: Literal["split", "full"] = Field(
        "split",
        description="split = learn quality, calculate cost and latency (research guide). "
        "full = learn the whole reward per model (original proposal).",
    )
    weights: RewardWeights = Field(default_factory=RewardWeights)
    c_ref_usd: float = Field(0.002, gt=0, description="Reference cost per request, fixed from pilot data.")
    l_ref_s: float = Field(10.0, gt=0, description="Reference latency in seconds, fixed from pilot data.")
    eps_start: float = Field(0.10, ge=0, le=1)
    eps_end: float = Field(0.02, ge=0, le=1)
    eps_decay_steps: int = Field(1000, ge=1)
    update_batch_size: int = Field(50, ge=1)
    ridge_lambda: float = Field(1.0, gt=0)
    linucb_alpha: float = Field(0.5, ge=0)
    linucb_gamma: float = Field(0.995, gt=0, le=1)
    max_retries: int = Field(1, ge=0, le=3)
    # Router v2 (calibrated policies)
    quality_floor: float = Field(
        0.5, ge=0, le=1, description="Calibrated policies avoid a model predicted below this quality for a request."
    )
    v2_ucb_alpha: float = Field(1.0, ge=0, description="Exploration bonus of calibrated UCB, in standard deviations.")

    # ---- Context and tokens ----
    output_caps: dict[str, int] = Field(
        default_factory=lambda: {"explain": 400, "doc_qa": 500, "summary": 800, "chat": 1024}
    )
    context_safety_margin: float = Field(0.10, ge=0, le=0.5)
    retrieval_top_k: int = Field(5, ge=1, le=20)

    # ---- Conversation context ----
    history_budget_tokens: int = Field(
        2000, ge=200, description="Earlier turns sent per request. Beyond this, recent turns are sent verbatim "
        "and older ones are summarised locally."
    )
    history_summary_enabled: bool = Field(
        True, description="Summarise older turns with the local model, in the background after each answer."
    )

    # ---- Cost ----
    cache_enabled: bool = True
    cache_ttl_s: int = 3600
    global_monthly_budget_usd: float | None = Field(
        100.0, description="Cap on spend through platform credentials. None = no cap."
    )

    # ---- Retention ----
    session_expiry_minutes: int = Field(60, ge=5, description="Inactivity expiry for chat content and documents.")
    metadata_retention_days: int = Field(30, ge=1, description="Routing metadata and cost ledger.")
    audit_retention_days: int = Field(365, ge=1, description="Confidential-query audit log.")


def load_policy(db: Session) -> PolicyConfig:
    row = db.get(PolicySettings, 1)
    if row is None:
        row = PolicySettings(id=1, data=PolicyConfig().model_dump())
        db.add(row)
        db.commit()
    # Validate through the model so newly added fields get their defaults.
    return PolicyConfig.model_validate(row.data or {})


def save_policy(db: Session, new: PolicyConfig, actor: User) -> PolicyConfig:
    old = load_policy(db).model_dump()
    updated = new.model_dump()
    changes = {k: [old.get(k), v] for k, v in updated.items() if old.get(k) != v}
    if not changes:
        return new
    row = db.get(PolicySettings, 1)
    row.data = updated
    row.updated_at = utcnow()
    row.updated_by = actor.id
    db.add(PolicyChange(actor_id=actor.id, actor_email=actor.email, target="policy", changes=changes))
    db.commit()
    return new
