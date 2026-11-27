"""The request pipeline shared by the chat interface, the /v1 router API and the
evaluation scripts.

    prepare()  evidence -> confidentiality assessment -> eligibility filter
               -> cache -> policy selection                      (no model call)
    run()      final outbound gate -> dispatch -> bounded retry -> log -> learn

Hard limits (privacy, context window, health, budget) decide what is ALLOWED.
The routing policy only decides what is BEST among the allowed models. If nothing
is allowed the request is refused with an explanation; there is no silent cloud
fallback anywhere in this file.
"""

from __future__ import annotations

import calendar
import json
import logging
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import timedelta
from typing import Callable, Iterator

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import session_scope
from ..models import (
    ApiKey,
    Attempt,
    ConfidentialEvent,
    Document,
    DocumentChunk,
    ModelEntry,
    ProviderCredential,
    RoutingEvent,
    User,
    new_id,
    utcnow,
)
from ..security import decrypt_secret
from . import context as conversation
from .analysis import classify_task, estimate_complexity, explicit_task, question_text
from .cache import response_cache
from .documents import bm25_scores
from .features import get_extractor
from .policy_config import PolicyConfig, load_policy
from .privacy.gate import (
    CLOUD_ALLOWED,
    KIND_CONFIDENTIAL_DOC,
    KIND_CONVERSATION,
    KIND_PUBLIC_DOC,
    KIND_SYSTEM,
    Assessment,
    CloudPermission,
    Part,
    PayloadGate,
    decide_cloud,
    sha256_text,
)
from .privacy.scanner import get_scanner
from .providers import VENDORS, ChatRequest, ChatResult, CredentialSpec, ModelSpec, ProviderError, build_provider
from .providers.base import FINISH_LENGTH, FINISH_REFUSAL
from .reward import FAILURE_REWARD, combine_quality, reward
from .routing import state as learner_state
from .routing.policies import (
    Candidate,
    Decision,
    EpsilonGreedyPolicy,
    FixedPolicy,
    FrozenPolicy,
    LinUCBPolicy,
    RandomPolicy,
    RequestInfo,
    RulesPolicy,
    pacer_lambda,
)
from .tokens import count_messages, count_tokens
from .tiers import tier_credential

log = logging.getLogger(__name__)

_PROMPT_BASE = "You are SmartRoute, an assistant for academic documents. Answer accurately and concisely."
# Models tend to refuse requests that carry personal data. Deciding where such content may
# go is the gateway's job (privacy gate), not the model's, so the model is told so.
_PROMPT_PERSONAL = (
    " Requests may include the user's own personal details, such as names, ID numbers or contact "
    "details. This server's privacy controls decide where they are processed, so help with them normally."
)
_PROMPT_EVIDENCE = (
    " When document excerpts are provided, base the answer on them and cite the excerpts you used "
    "by their bracketed number, for example [2]. If the excerpts do not contain the answer, say so "
    "instead of guessing."
)
# The excerpt rules only when excerpts are attached: without excerpts, small models read
# them as "answer only from excerpts" and decline ordinary questions.
SYSTEM_PROMPT_WITH_EVIDENCE = _PROMPT_BASE + _PROMPT_EVIDENCE + _PROMPT_PERSONAL
SYSTEM_PROMPT_GENERAL = _PROMPT_BASE.replace("an assistant for academic documents", "a helpful assistant") + _PROMPT_PERSONAL
UNHEALTHY_SECONDS = 60
LATENCY_EWMA_ALPHA = 0.2
MAX_TRIM_ROUNDS = 50

_rng = np.random.default_rng()
_rng_lock = threading.Lock()
_local_inflight = 0
_inflight_lock = threading.Lock()


# ------------------------------------------------------------------ data shapes


@dataclass
class RouteRequest:
    user_id: str
    user_email: str
    messages: list[dict]  # conversation ending with the latest user turn
    user_override: bool | None = None  # User.allow_confidential_cloud
    user_budget_usd: float | None = None
    source: str = "chat"  # "chat" | "api" | "eval"
    privacy_mode: str = CLOUD_ALLOWED
    consent: bool = False  # explicit consent for THIS payload to go to cloud
    confidential_label: bool = False  # caller marks the request confidential
    session_confidential: bool = False  # sticky label inherited from the session
    document_ids: list[str] = field(default_factory=list)
    prior_chunk_ids: list[str] = field(default_factory=list)  # passages the previous answer used
    # None = SmartRoute's own academic prompt (chat interface). A string = the API
    # caller's system prompt, which is caller content and is scanned like any message.
    system_prompt: str | None = None
    task: str | None = None
    pinned_model: str | None = None
    policy_override: str | None = None  # evaluation and admin use
    max_tokens: int | None = None
    temperature: float | None = None
    session_id: str | None = None
    api_key_id: str | None = None
    use_cache: bool = True
    seed: int | None = None

    @classmethod
    def for_user(cls, user: User, messages: list[dict], **kwargs) -> "RouteRequest":
        return cls(
            user_id=user.id,
            user_email=user.email,
            messages=messages,
            user_override=user.allow_confidential_cloud,
            user_budget_usd=user.monthly_budget_usd,
            **kwargs,
        )


@dataclass
class Evidence:
    n: int
    document: str
    page: int
    text: str
    kind: str
    chunk_id: str = ""

    def rendered(self) -> str:
        return f"[{self.n}] ({self.document}, page {self.page})\n{self.text}"


@dataclass
class Draft:
    """Structured payload. The messages that are dispatched are always rendered
    from this object, and the outbound gate assesses the very same object, so
    every byte that leaves the host has been assessed."""

    system: str
    history: list[dict]
    evidence: list[Evidence]
    question: str
    system_from_caller: bool = False
    memory: str = ""  # local summary of earlier turns
    # Earlier turns that are not sent. They are still assessed: content derived
    # from a confidential turn (the summary) inherits its label.
    omitted: list[str] = field(default_factory=list)

    def parts(self) -> list[Part]:
        out = [Part(KIND_CONVERSATION if self.system_from_caller else KIND_SYSTEM, self.system)] if self.system else []
        if self.memory:
            out.append(Part(KIND_CONVERSATION, self.memory))
        out += [Part(KIND_CONVERSATION, text) for text in self.omitted]
        out += [Part(KIND_CONVERSATION, m["content"]) for m in self.history]
        out += [Part(e.kind, e.rendered()) for e in self.evidence]
        out.append(Part(KIND_CONVERSATION, self.question))
        return out

    def render(self) -> list[dict]:
        if self.evidence:
            excerpts = "\n\n".join(e.rendered() for e in self.evidence)
            content = f"Document excerpts:\n{excerpts}\n\nQuestion: {self.question}"
        else:
            content = self.question
        system = self.system
        if self.memory:
            block = f"{conversation.MEMORY_HEADER}\n{self.memory}"
            system = f"{system}\n\n{block}" if system else block
        head = [{"role": "system", "content": system}] if system else []
        return [*head, *self.history, {"role": "user", "content": content}]


@dataclass
class Route:
    spec: ModelSpec
    cred: CredentialSpec | None
    est_cost_usd: float

    @property
    def scope(self) -> str:
        return "local" if self.spec.is_local else (self.cred.scope if self.cred else "platform")

    def candidate(self) -> Candidate:
        return Candidate(self.spec.name, self.spec.tier, self.spec.is_local, self.est_cost_usd, self.spec.latency_s)


@dataclass
class Plan:
    event_id: str
    req: RouteRequest
    cfg: PolicyConfig
    draft: Draft
    gate: PayloadGate
    assessment: Assessment
    permission: CloudPermission
    task: str
    info: RequestInfo
    x: list[float]
    est_in_tokens: int
    est_out_tokens: int
    out_cap: int
    routes: dict[str, Route]
    exclusions: dict[str, str]
    selector: Callable[[list[Candidate]], Decision | None]
    decision: Decision | None
    policy_name: str
    policy_version: int
    notices: list[str] = field(default_factory=list)
    context_compressed: bool = False
    confidential_event_id: str | None = None
    cache_key: str | None = None
    cached: dict | None = None
    abstain_reason: str | None = None
    abstain_kind: str | None = None  # "privacy" | "unavailable"
    routing_overhead_ms: float = 0.0
    follow_up: bool = False
    history_mode: str = "none"
    history_messages: int = 0


@dataclass
class Outcome:
    event_id: str
    status: str  # ok | abstained | failed | empty | truncated | refused | cache_hit | cancelled
    text: str = ""
    model: str | None = None
    served_model: str | None = None
    tier: str | None = None
    is_local: bool | None = None
    policy: str = ""
    policy_version: int = 0
    explanation: str = ""
    propensity: float | None = None
    explored: bool = False
    in_tokens: int = 0
    out_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: float = 0.0
    ttft_ms: float | None = None
    routing_overhead_ms: float = 0.0
    attempts: int = 0
    fallback_from: str | None = None
    notices: list[str] = field(default_factory=list)
    sources: list[dict] = field(default_factory=list)
    sensitive: bool = False
    entity_types: list[str] = field(default_factory=list)
    eligible: list[str] = field(default_factory=list)
    exclusions: dict[str, str] = field(default_factory=dict)
    abstain_kind: str | None = None
    error: str | None = None
    cache_hit: bool = False
    context_compressed: bool = False
    follow_up: bool = False
    history_mode: str = "none"  # none | full | summary | relevant_turns
    history_messages: int = 0  # earlier messages in the conversation
    history_sent: int = 0  # of those, sent verbatim
    cache_read_tokens: int = 0  # input tokens billed at the provider's cache rate

    def public(self) -> dict:
        """Metadata shown to the caller (everything except the answer text)."""
        data = asdict(self)
        data.pop("text")
        return data


# ----------------------------------------------------------------- small helpers


def month_start():
    now = utcnow()
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _month_fraction() -> float:
    now = utcnow()
    return now.day / calendar.monthrange(now.year, now.month)[1]


def _spent(db: Session, *, user_id: str | None = None, scope: str | None = None) -> float:
    q = select(func.coalesce(func.sum(Attempt.cost_usd), 0.0)).where(Attempt.created_at >= month_start())
    if user_id:
        q = q.where(Attempt.user_id == user_id)
    if scope:
        q = q.where(Attempt.credential_scope == scope)
    return float(db.execute(q).scalar_one())


def spec_from_entry(m: ModelEntry) -> ModelSpec:
    return ModelSpec(
        name=m.name,
        vendor=m.vendor,
        model_id=m.model_id,
        tier=m.tier,
        is_local=m.is_local,
        base_url=m.base_url,
        context_window=m.context_window,
        max_output_tokens=m.max_output_tokens,
        price_in_per_mtok=m.price_in_per_mtok,
        price_out_per_mtok=m.price_out_per_mtok,
        params=dict(m.params or {}),
        latency_s=(m.latency_ewma_ms or 0.0) / 1000,
    )


def _local_summary_model(db: Session) -> ModelSpec | None:
    """A healthy local model for conversation summaries. Never a cloud model."""
    now = utcnow()
    production = get_settings().is_production
    for m in db.execute(
        select(ModelEntry).where(ModelEntry.enabled.is_(True), ModelEntry.is_local.is_(True)).order_by(ModelEntry.name)
    ).scalars():
        if m.unhealthy_until and m.unhealthy_until > now:
            continue
        if production and VENDORS.get(m.vendor, VENDORS["mock"]).adapter == "mock":
            continue
        return spec_from_entry(m)
    return None


def resolve_credential(db: Session, model: ModelEntry) -> CredentialSpec | str:
    """The key the superadmin set for this model's tier. Users cannot add keys, so every
    cloud call uses an organisation key. A shared key added for the same provider before
    tiers existed is used as a fallback. Returns a CredentialSpec or an exclusion reason."""
    row = tier_credential(db, model.tier)
    if row is None or row.vendor != model.vendor:
        row = db.execute(
            select(ProviderCredential)
            .where(ProviderCredential.user_id.is_(None), ProviderCredential.vendor == model.vendor)
            .order_by(ProviderCredential.created_at.desc())
        ).scalars().first()
    if row is None:
        return "no_credential"
    key = decrypt_secret(row.encrypted_key)
    if key is None:
        return "credential_unreadable"
    return CredentialSpec(api_key=key, base_url=row.base_url, api_version=row.api_version, scope="platform")


# -------------------------------------------------------------------- evidence


def _retrieve(
    db: Session, req: RouteRequest, cfg: PolicyConfig, query: dict[str, float], task: str | None, follow_up: bool
) -> list[Evidence]:
    if not req.document_ids:
        return []
    # Ownership is enforced here: a user can only ground answers in their own documents.
    docs = db.execute(
        select(Document).where(Document.id.in_(req.document_ids), Document.user_id == req.user_id)
    ).scalars().all()
    if not docs:
        return []
    for d in docs:
        d.last_used_at = utcnow()  # keeps an in-use document from expiring
    by_id = {d.id: d for d in docs}
    chunks = db.execute(
        select(DocumentChunk)
        .where(DocumentChunk.document_id.in_(list(by_id)))
        .order_by(DocumentChunk.document_id, DocumentChunk.idx)
    ).scalars().all()
    if not chunks:
        return []
    picked = []
    if task != "summary":
        scores = bm25_scores(query, [c.text for c in chunks])
        prior = set(req.prior_chunk_ids)
        if follow_up and prior:
            # Evidence carry-over: a follow-up usually asks about what was just
            # discussed, so the passages behind the previous answer stay in contention.
            bonus = 0.5 * max(scores) if max(scores) > 0 else 1.0
            scores = [s + bonus if c.id in prior else s for s, c in zip(scores, chunks)]
        order = sorted(range(len(chunks)), key=lambda i: scores[i], reverse=True)
        picked = [chunks[i] for i in order if scores[i] > 0][: cfg.retrieval_top_k]
    if not picked:
        # Summaries (and questions with no lexical overlap) use the opening of the document.
        picked = chunks[: cfg.retrieval_top_k * (2 if task == "summary" else 1)]
    out = []
    for n, chunk in enumerate(picked, start=1):
        doc = by_id[chunk.document_id]
        kind = KIND_PUBLIC_DOC if doc.label == "public" else KIND_CONFIDENTIAL_DOC
        out.append(Evidence(n, doc.filename, chunk.page, chunk.text, kind, chunk.id))
    return out


# ----------------------------------------------------------------- eligibility


def _eligibility(
    db: Session,
    req: RouteRequest,
    cfg: PolicyConfig,
    permission: CloudPermission,
    est_in: int,
    est_out: int,
    out_cap: int,
) -> tuple[dict[str, Route], dict[str, str]]:
    """The eligibility funnel: privacy -> credential -> health -> context -> budget."""
    settings = get_settings()
    now = utcnow()
    routes: dict[str, Route] = {}
    exclusions: dict[str, str] = {}
    user_spent = _spent(db, user_id=req.user_id) if req.user_budget_usd is not None else 0.0
    platform_spent = _spent(db, scope="platform") if cfg.global_monthly_budget_usd is not None else 0.0

    for m in db.execute(select(ModelEntry).where(ModelEntry.enabled.is_(True)).order_by(ModelEntry.name)).scalars():
        vendor = VENDORS.get(m.vendor)
        if vendor is None:
            exclusions[m.name] = "unknown_vendor"
            continue
        if vendor.adapter == "mock" and settings.is_production:
            exclusions[m.name] = "mock_disabled_in_production"
            continue
        if not m.is_local and not permission.allowed:
            exclusions[m.name] = f"privacy:{permission.reason}"
            continue
        cred: CredentialSpec | None = None
        if vendor.needs_key:
            resolved = resolve_credential(db, m)
            if isinstance(resolved, str):
                exclusions[m.name] = resolved
                continue
            cred = resolved
            if vendor.needs_base_url and not (m.base_url or cred.base_url):
                exclusions[m.name] = "no_endpoint"
                continue
        if m.unhealthy_until and m.unhealthy_until > now:
            exclusions[m.name] = "unhealthy"
            continue
        spec = spec_from_entry(m)
        if est_in + min(out_cap, spec.max_output_tokens) + spec.reasoning_overhead > spec.context_window:
            exclusions[m.name] = "context_window"
            continue
        est_cost = spec.cost_usd(est_in, est_out)
        route = Route(spec, cred, est_cost)
        if req.user_budget_usd is not None and user_spent + est_cost > req.user_budget_usd and est_cost > 0:
            exclusions[m.name] = "user_budget"
            continue
        if (
            route.scope == "platform"
            and cfg.global_monthly_budget_usd is not None
            and platform_spent + est_cost > cfg.global_monthly_budget_usd
        ):
            exclusions[m.name] = "platform_budget"
            continue
        routes[m.name] = route
    return routes, exclusions


# --------------------------------------------------------------------- policy


def _make_selector(
    db: Session, req: RouteRequest, cfg: PolicyConfig, x: np.ndarray, info: RequestInfo, notices: list[str]
) -> tuple[Callable[[list[Candidate]], Decision | None], str, int]:
    """Returns (selector, policy name, policy version). Any error inside a learned
    policy falls back to the fixed rules, so a broken learner never blocks answers."""
    rules = RulesPolicy()
    extractor = get_extractor()

    if req.pinned_model:
        fixed = FixedPolicy(model=req.pinned_model)
        return (lambda cands: fixed.select(info, cands)), fixed.name, 0

    name = req.policy_override or cfg.routing_policy
    if name.startswith("fixed:"):
        fixed = FixedPolicy(tier=name.split(":", 1)[1])
        return (lambda cands: fixed.select(info, cands)), fixed.name, 0
    if name == "rules":
        return (lambda cands: rules.select(info, cands)), "rules", 0

    rng = np.random.default_rng(req.seed) if req.seed is not None else None

    def draw(fn):
        if rng is not None:
            return fn(rng)
        with _rng_lock:
            return fn(_rng)

    if name == "random":
        policy = RandomPolicy()
        return (lambda cands: draw(lambda r: policy.select(cands, r))), "random", 0

    arms, version = learner_state.load_arms(db, name, extractor.dim, cfg.ridge_lambda, extractor.version)
    if name == "frozen" and version == 0:
        notices.append("The frozen router has not been trained yet; fixed rules were used.")
        return (lambda cands: rules.select(info, cands)), "rules", 0

    if name == "frozen":
        policy = FrozenPolicy()
        learned = lambda cands: policy.select(x, cands, arms, cfg)  # noqa: E731
    elif name == "linucb":
        policy = LinUCBPolicy()
        lam = pacer_lambda(_spent(db, scope="platform"), cfg.global_monthly_budget_usd, _month_fraction())
        learned = lambda cands: policy.select(x, cands, arms, cfg, lam)  # noqa: E731
    else:
        name = "bandit"
        policy = EpsilonGreedyPolicy()
        learned = lambda cands: draw(lambda r: policy.select(x, cands, arms, cfg, r))  # noqa: E731

    def safe(cands: list[Candidate]) -> Decision | None:
        try:
            return learned(cands)
        except Exception:
            log.exception("learned policy failed; falling back to fixed rules")
            decision = rules.select(info, cands)
            decision.explanation = "router error, fixed rules used: " + decision.explanation
            return decision

    return safe, name, version


# -------------------------------------------------------------------- prepare


def prepare(db: Session, req: RouteRequest) -> Plan:
    started = time.perf_counter()
    cfg = load_policy(db)
    notices: list[str] = []
    question = question_text(req.messages)
    history = [m for m in req.messages[:-1] if m.get("role") in ("user", "assistant")]
    has_document = bool(req.document_ids)

    # Conversation context: is this a follow-up, and what should it borrow?
    turn = conversation.analyse_turn(question, history)
    task = req.task or explicit_task(question)
    if task is None:
        source_text = turn.previous_question if turn.follow_up else question
        task = classify_task(source_text, has_document)
    query = conversation.retrieval_query(question, turn)
    window = conversation.build_window(
        req.user_id, history, query, cfg.history_budget_tokens, cfg.history_summary_enabled
    )
    if window.mode == "summary":
        notices.append("Earlier turns were replaced by a summary written on this server.")
    elif window.omitted:
        notices.append(
            f"{len(window.omitted)} earlier messages were left out; the most relevant earlier turns were kept."
        )

    evidence = _retrieve(db, req, cfg, query, task, turn.follow_up)
    if req.system_prompt is not None:
        system, from_caller = req.system_prompt, True
    else:
        system, from_caller = (SYSTEM_PROMPT_WITH_EVIDENCE if evidence else SYSTEM_PROMPT_GENERAL), False
    draft = Draft(
        system, window.recent, evidence, question, system_from_caller=from_caller,
        memory=window.memory, omitted=[m["content"] for m in window.omitted],
    )
    out_cap = req.max_tokens or cfg.output_caps.get(task, cfg.output_caps.get("chat", 1024))
    est_out = max(out_cap // 2, 1)

    # 1. Detection: is the payload confidential?
    gate = PayloadGate(get_scanner(), cfg)
    assessment = gate.assess(
        draft.parts(), explicit_label=req.confidential_label, session_label=req.session_confidential
    )
    # 2. Enforcement: may it leave the host?
    permission = decide_cloud(
        cfg,
        user_override=req.user_override,
        privacy_mode=req.privacy_mode,
        assessment=assessment,
        consent=req.consent,
    )

    # 3. Eligibility, compressing old history if nothing fits a context window.
    margin = 1 + cfg.context_safety_margin
    compressed = False
    for _ in range(MAX_TRIM_ROUNDS):
        est_in = int(count_messages(draft.render()) * margin)
        routes, exclusions = _eligibility(db, req, cfg, permission, est_in, est_out, out_cap)
        only_context = not routes and "context_window" in exclusions.values()
        if routes or not only_context or not draft.history:
            break
        drop = 2 if len(draft.history) >= 2 else len(draft.history)
        draft.omitted += [m["content"] for m in draft.history[:drop]]
        draft.history = draft.history[drop:]
        compressed = True
    if compressed:
        notices.append("Older conversation turns were dropped so the request fits the model context window.")
        assessment = gate.assess(
            draft.parts(), explicit_label=req.confidential_label, session_label=req.session_confidential
        )

    # 4. Features and policy.
    complexity = estimate_complexity(question, est_in)
    if turn.follow_up:
        # A follow-up continues the thread, so it is at least as hard as the
        # question it follows: "Why?" after a hard question is a hard question.
        complexity = max(complexity, estimate_complexity(turn.previous_question, est_in))
    history_tokens = count_messages(draft.history) + (count_tokens(draft.memory) if draft.memory else 0)
    info = RequestInfo(task=task, in_tokens=est_in, complexity=complexity, has_document=has_document)
    with _inflight_lock:
        local_load = float(_local_inflight)
    try:
        x = get_extractor().extract(
            prompt=question,
            in_tokens=est_in,
            est_out_tokens=est_out,
            has_document=has_document,
            complexity=complexity,
            task=task,
            local_load=local_load,
            history_tokens=history_tokens if draft.history or draft.memory else 0,
            follow_up=turn.follow_up,
        )
    except Exception:
        log.exception("feature extraction failed; fixed rules will be used")
        x = np.zeros(get_extractor().dim)
        req.policy_override = req.policy_override or "rules"
        notices.append("Feature extraction failed; fixed rules were used.")
    selector, policy_name, policy_version = _make_selector(db, req, cfg, x, info, notices)

    plan = Plan(
        event_id=new_id(),
        req=req,
        cfg=cfg,
        draft=draft,
        gate=gate,
        assessment=assessment,
        permission=permission,
        task=task,
        info=info,
        x=[float(v) for v in x],
        est_in_tokens=est_in,
        est_out_tokens=est_out,
        out_cap=out_cap,
        routes=routes,
        exclusions=exclusions,
        selector=selector,
        decision=None,
        policy_name=policy_name,
        policy_version=policy_version,
        notices=notices,
        context_compressed=compressed or bool(window.omitted),
        follow_up=turn.follow_up,
        history_mode=window.mode,
        history_messages=len(history),
    )

    # 5. Audit trail for confidential content, written before anything is dispatched.
    if assessment.sensitive:
        plan.confidential_event_id = new_id()
        db.add(
            ConfidentialEvent(
                id=plan.confidential_event_id,
                user_id=req.user_id,
                user_email=req.user_email,
                source=req.source,
                privacy_mode=req.privacy_mode,
                triggers=assessment.triggers,
                entity_types=assessment.entity_types,
                decision="cloud_allowed" if permission.allowed else "cloud_blocked",
                decision_reason=permission.reason,
                consent_given=req.consent,
                payload_sha256=assessment.payload_sha256,
                masked_preview=assessment.masked_preview,
                routing_event_id=plan.event_id,
            )
        )

    if not routes:
        _set_abstain(plan)
    else:
        if cfg.cache_enabled and req.use_cache and not assessment.sensitive and req.source != "eval":
            plan.cache_key = sha256_text(
                json.dumps(
                    [req.user_id, req.privacy_mode, req.pinned_model, out_cap, draft.render()], ensure_ascii=False
                )
            )
            plan.cached = response_cache.get(plan.cache_key)
        if plan.cached is None:
            plan.decision = selector([r.candidate() for r in routes.values()])
            if plan.decision is None:
                _set_abstain(plan, pinned=bool(req.pinned_model))

    plan.routing_overhead_ms = (time.perf_counter() - started) * 1000
    if plan.abstain_reason:
        _write_event(db, plan, status="abstained")
    db.commit()
    return plan


_PRIVACY_TEXT = {
    "institutional_policy": "Your organisation has disabled cloud models.",
    "local_only_mode": "This request is in local-only mode.",
    "scanner_failure": "The privacy scanner could not check this request, so cloud dispatch is blocked.",
    "confidential_not_permitted": "The request contains confidential content and your account is not "
    "permitted to send confidential content to cloud models.",
    "consent_required": "The request contains confidential content. Confirm consent to send it to a cloud model.",
}


def _set_abstain(plan: Plan, pinned: bool = False) -> None:
    reasons = set(plan.exclusions.values())
    privacy_block = not plan.permission.allowed
    if pinned:
        why = plan.exclusions.get(plan.req.pinned_model or "", "not registered or not enabled")
        plan.abstain_kind = "privacy" if why.startswith(("privacy:", "final_gate:")) else "unavailable"
        plan.abstain_reason = f"The requested model '{plan.req.pinned_model}' is not eligible ({why})."
        return
    if plan.routes:
        plan.abstain_kind = "unavailable"
        plan.abstain_reason = f"The policy '{plan.policy_name}' has no eligible model for this request."
    elif privacy_block:
        plan.abstain_kind = "privacy"
        other = sorted(r for r in reasons if not r.startswith(("privacy:", "final_gate:")))
        local_note = f" No local model could take it ({', '.join(other)})." if other else " No local model is available."
        plan.abstain_reason = _PRIVACY_TEXT.get(plan.permission.reason, "Cloud dispatch is not permitted.") + local_note
    else:
        plan.abstain_kind = "unavailable"
        plan.abstain_reason = "No eligible model: " + (", ".join(sorted(reasons)) or "no models are registered") + "."


# ------------------------------------------------------------------- logging


def _write_event(db: Session, plan: Plan, *, status: str, **fields) -> None:
    decision = plan.decision
    db.add(
        RoutingEvent(
            id=plan.event_id,
            user_id=plan.req.user_id,
            source=plan.req.source,
            session_id=plan.req.session_id,
            api_key_id=plan.req.api_key_id,
            task=plan.task,
            privacy_mode=plan.req.privacy_mode,
            sensitive=plan.assessment.sensitive,
            features=plan.x,
            eligible=sorted(plan.routes),
            exclusions=plan.exclusions,
            policy_name=plan.policy_name,
            policy_version=plan.policy_version,
            propensity=decision.propensity if decision else None,
            explored=decision.explored if decision else False,
            explanation=(decision.explanation if decision else plan.abstain_reason) or "",
            status=status,
            est_in_tokens=plan.est_in_tokens,
            est_out_tokens=plan.est_out_tokens,
            routing_overhead_ms=plan.routing_overhead_ms,
            context_compressed=plan.context_compressed,
            confidential_event_id=plan.confidential_event_id,
            **fields,
        )
    )


def _base_outcome(plan: Plan, status: str) -> Outcome:
    d = plan.decision
    return Outcome(
        event_id=plan.event_id,
        status=status,
        policy=plan.policy_name,
        policy_version=plan.policy_version,
        explanation=d.explanation if d else (plan.abstain_reason or ""),
        propensity=d.propensity if d else None,
        explored=d.explored if d else False,
        routing_overhead_ms=round(plan.routing_overhead_ms, 2),
        notices=list(plan.notices),
        sources=[
            {"n": e.n, "document": e.document, "page": e.page, "chunk_id": e.chunk_id} for e in plan.draft.evidence
        ],
        sensitive=plan.assessment.sensitive,
        entity_types=plan.assessment.entity_types,
        eligible=sorted(plan.routes),
        exclusions=dict(plan.exclusions),
        abstain_kind=plan.abstain_kind,
        context_compressed=plan.context_compressed,
        follow_up=plan.follow_up,
        history_mode=plan.history_mode,
        history_messages=plan.history_messages,
        history_sent=len(plan.draft.history),
    )


# ------------------------------------------------------------------------ run


def _final_gate(plan: Plan) -> tuple[bool, str]:
    """Independent outbound check on the payload about to be dispatched to a cloud
    model. Re-assesses the current draft and re-applies the enforcement rules; the
    router's utility score plays no part in it."""
    assessment = plan.gate.assess(
        plan.draft.parts(),
        explicit_label=plan.req.confidential_label,
        session_label=plan.req.session_confidential,
    )
    permission = decide_cloud(
        plan.cfg,
        user_override=plan.req.user_override,
        privacy_mode=plan.req.privacy_mode,
        assessment=assessment,
        consent=plan.req.consent,
    )
    plan.assessment = assessment
    return permission.allowed, permission.reason


def run(plan: Plan) -> Iterator[tuple[str, object]]:
    """Yields ("delta", text) while the answer streams, then ("final", Outcome)."""
    if plan.abstain_reason:
        yield "final", _base_outcome(plan, "abstained")
        return

    if plan.cached is not None:
        outcome = _base_outcome(plan, "cache_hit")
        outcome.text = plan.cached["text"]
        outcome.model = plan.cached["model"]
        outcome.cache_hit = True
        outcome.explanation = "Served from the response cache; no model was called."
        with session_scope() as db:
            _write_event(db, plan, status="cache_hit", chosen_model=outcome.model, cache_hit=True)
        yield "delta", outcome.text
        yield "final", outcome
        return

    state = _RunState(plan)
    try:
        yield from state.execute()
    finally:
        # Also runs if the client disconnects mid-stream, so every dispatch is logged.
        outcome = state.finalize()
    yield "final", outcome


class _RunState:
    def __init__(self, plan: Plan):
        self.plan = plan
        self.remaining = dict(plan.routes)
        self.attempts: list[dict] = []
        self.status = "cancelled"
        self.text = ""
        self.result: ChatResult | None = None
        self.route: Route | None = None
        self.error: str | None = None
        self.fallback_from: str | None = None
        self.ttft_ms: float | None = None
        self.started = time.perf_counter()
        self.left_boundary = False
        self._finalized: Outcome | None = None

    def _reselect(self) -> bool:
        plan = self.plan
        if not self.remaining:
            return False
        plan.decision = plan.selector([r.candidate() for r in self.remaining.values()])
        return plan.decision is not None

    def execute(self) -> Iterator[tuple[str, object]]:
        global _local_inflight
        plan, cfg = self.plan, self.plan.cfg
        emitted = False
        while True:
            route = self.remaining[plan.decision.arm]
            if not route.spec.is_local:
                allowed, reason = _final_gate(plan)
                if not allowed:
                    for name in [n for n, r in self.remaining.items() if not r.spec.is_local]:
                        plan.exclusions[name] = f"final_gate:{reason}"
                        del self.remaining[name]
                    plan.notices.append("The outbound privacy check blocked cloud dispatch for this request.")
                    if not self._reselect():
                        plan.routes = dict(self.remaining)
                        plan.permission = CloudPermission(False, reason)
                        plan.decision = None
                        _set_abstain(plan, pinned=bool(plan.req.pinned_model))
                        self.status = "abstained"
                        return
                    continue
            messages = plan.draft.render()
            spec = route.spec
            self.route = route
            request = ChatRequest(
                model_id=spec.model_id,
                messages=messages,
                max_tokens=min(plan.out_cap, spec.max_output_tokens) + spec.reasoning_overhead,
                temperature=plan.req.temperature,
                params=spec.params,
            )
            result: ChatResult | None = None
            error: str | None = None
            parts: list[str] = []
            t0 = time.perf_counter()
            if spec.is_local:
                with _inflight_lock:
                    _local_inflight += 1
            else:
                self.left_boundary = True
            try:
                provider = build_provider(spec, route.cred)
                for item in provider.stream(request):
                    if isinstance(item, str):
                        if not emitted:
                            emitted = True
                            self.ttft_ms = (time.perf_counter() - self.started) * 1000
                        parts.append(item)
                        yield "delta", item
                    else:
                        result = item
            except ProviderError as exc:
                error = str(exc)[:500]
            except Exception as exc:  # an adapter bug must not take the request down
                log.exception("provider crashed")
                error = f"{type(exc).__name__}: {exc}"[:500]
            finally:
                if spec.is_local:
                    with _inflight_lock:
                        _local_inflight -= 1
            latency_ms = (time.perf_counter() - t0) * 1000

            if error is not None or result is None:
                attempt_status = "failed"
                error = error or "provider returned no result"
            elif result.finish_reason == FINISH_REFUSAL:
                attempt_status = "refused"
            elif not result.text.strip():
                attempt_status = "empty"
            elif result.finish_reason == FINISH_LENGTH:
                attempt_status = "truncated"
            else:
                attempt_status = "ok"
            in_tok = result.in_tokens if result else 0
            out_tok = result.out_tokens if result else 0
            cache_read = result.cache_read_tokens if result else 0
            cache_write = result.cache_write_tokens if result else 0
            self.attempts.append(
                {
                    "model_name": spec.name,
                    "purpose": "retry" if self.attempts else ("benchmark" if plan.req.source == "eval" else "answer"),
                    "credential_scope": route.scope,
                    "status": attempt_status,
                    "in_tokens": in_tok,
                    "out_tokens": out_tok,
                    "cost_usd": spec.cost_usd(in_tok, out_tok, cache_read, cache_write),
                    "latency_ms": latency_ms,
                    "error": error,
                    # Stand-in cloud tiers: the router tracks the simulated API latency.
                    "router_latency_ms": spec.router_latency_ms(latency_ms, in_tok, out_tok),
                }
            )
            self.result, self.error, self.text = result, error, "".join(parts)
            if attempt_status == "ok":
                self.status = "ok"
                return
            # Failure. A different model is tried only if nothing has been shown to
            # the user yet: the application never switches models mid-answer.
            del self.remaining[spec.name]
            plan.exclusions[spec.name] = f"attempt_{attempt_status}"
            can_retry = not emitted and len(self.attempts) <= cfg.max_retries and not plan.req.pinned_model
            if not can_retry or not self._reselect():
                self.status = attempt_status
                return
            self.fallback_from = self.fallback_from or spec.name
            plan.notices.append(f"{spec.name} failed ({attempt_status}); the request was retried on another model.")

    def finalize(self) -> Outcome:
        if self._finalized is not None:
            return self._finalized
        plan, route, result = self.plan, self.route, self.result
        total_ms = (time.perf_counter() - self.started) * 1000
        total_cost = sum(a["cost_usd"] for a in self.attempts)
        failed = self.status in ("failed", "empty", "truncated", "refused")
        outcome = _base_outcome(plan, self.status)
        outcome.text = self.text
        outcome.error = self.error if failed else None
        outcome.attempts = len(self.attempts)
        outcome.fallback_from = self.fallback_from
        outcome.cost_usd = round(total_cost, 8)
        outcome.latency_ms = round(total_ms, 1)
        outcome.ttft_ms = round(self.ttft_ms, 1) if self.ttft_ms is not None else None
        if route is not None:
            outcome.model, outcome.tier, outcome.is_local = route.spec.name, route.spec.tier, route.spec.is_local
        if result is not None:
            outcome.in_tokens, outcome.out_tokens = result.in_tokens, result.out_tokens
            outcome.served_model = result.served_model
            outcome.cache_read_tokens = result.cache_read_tokens
        summary_model: ModelSpec | None = None
        try:
            with session_scope() as db:
                if self.status == "ok" and plan.cfg.history_summary_enabled:
                    summary_model = _local_summary_model(db)
                _write_event(
                    db,
                    plan,
                    status=self.status,
                    chosen_model=outcome.model,
                    served_model=outcome.served_model,
                    in_tokens=outcome.in_tokens,
                    out_tokens=outcome.out_tokens,
                    cost_usd=total_cost,
                    latency_ms=total_ms,
                    ttft_ms=self.ttft_ms,
                    attempts=len(self.attempts),
                    fallback_from=self.fallback_from,
                    reward=FAILURE_REWARD if failed else None,
                )
                for a in self.attempts:
                    columns = {k: v for k, v in a.items() if k != "router_latency_ms"}
                    db.add(Attempt(event_id=plan.event_id, user_id=plan.req.user_id, **columns))
                    self._update_model_stats(db, a)
                    if a["status"] != "ok" and a["model_name"] != outcome.model:
                        # Attribute a failed attempt to the arm that failed, not to the
                        # model that finally answered. Cost stays on the main event.
                        db.add(
                            RoutingEvent(
                                user_id=plan.req.user_id,
                                source=plan.req.source,
                                session_id=plan.req.session_id,
                                task=plan.task,
                                privacy_mode=plan.req.privacy_mode,
                                sensitive=plan.assessment.sensitive,
                                features=plan.x,
                                policy_name=plan.policy_name,
                                policy_version=plan.policy_version,
                                chosen_model=a["model_name"],
                                explanation=f"failed attempt of request {plan.event_id}",
                                status="attempt_failed",
                                latency_ms=a["latency_ms"],
                                reward=FAILURE_REWARD,
                            )
                        )
                if plan.confidential_event_id:
                    audit = db.get(ConfidentialEvent, plan.confidential_event_id)
                    if audit is not None:
                        audit.destination_model = outcome.model
                        audit.left_trusted_boundary = self.left_boundary
                        if self.status == "abstained":
                            audit.decision, audit.decision_reason = "cloud_blocked", plan.permission.reason
                if plan.req.api_key_id:
                    key = db.get(ApiKey, plan.req.api_key_id)
                    if key is not None:
                        key.last_used_at = utcnow()
            if self.status == "ok" and plan.cache_key:
                response_cache.put(plan.cache_key, {"text": self.text, "model": outcome.model}, plan.cfg.cache_ttl_s)
            if summary_model is not None:
                # Prepare, in the background, the summary the NEXT turn will need
                # once this conversation outgrows the history budget.
                conversation_so_far = [
                    {"role": m["role"], "content": m.get("content", "")}
                    for m in plan.req.messages
                    if m.get("role") in ("user", "assistant")
                ] + [{"role": "assistant", "content": self.text}]
                conversation.summarizer.schedule(
                    user_id=plan.req.user_id,
                    conversation=conversation_so_far,
                    spec=summary_model,
                    budget_tokens=plan.cfg.history_budget_tokens,
                    ttl_s=plan.cfg.session_expiry_minutes * 60,
                )
            if failed:
                with session_scope() as db:
                    learner_state.apply_pending_updates(db, plan.cfg)
        except Exception:
            log.exception("failed to record routing event %s", plan.event_id)
        self._finalized = outcome
        return outcome

    @staticmethod
    def _update_model_stats(db: Session, attempt: dict) -> None:
        model = db.execute(select(ModelEntry).where(ModelEntry.name == attempt["model_name"])).scalars().first()
        if model is None:
            return
        if attempt["status"] == "failed":
            # Circuit breaker: skip an endpoint that just errored for a short while.
            model.unhealthy_until = utcnow() + timedelta(seconds=UNHEALTHY_SECONDS)
            model.last_error = attempt["error"]
        elif attempt["status"] == "ok":
            model.unhealthy_until = None
            observed = attempt.get("router_latency_ms", attempt["latency_ms"])
            model.latency_ewma_ms = (
                (1 - LATENCY_EWMA_ALPHA) * (model.latency_ewma_ms or observed)
                + LATENCY_EWMA_ALPHA * observed
            )


def run_to_completion(plan: Plan) -> Outcome:
    outcome = None
    for kind, item in run(plan):
        if kind == "final":
            outcome = item
    return outcome


# -------------------------------------------------------------------- scoring


def record_quality(
    db: Session, event_id: str, *, human: float | None = None, auto: float | None = None
) -> RoutingEvent | None:
    """Stores a human rating and/or automatic score, recomputes quality and reward,
    and triggers the batched learner update. An outcome that was already fed to the
    learner is not fed again."""
    event = db.get(RoutingEvent, event_id)
    if event is None or event.status not in ("ok", "cache_hit"):
        return event
    cfg = load_policy(db)
    if human is not None:
        event.human_score = human
    if auto is not None:
        event.auto_score = auto
    event.quality, event.quality_source = combine_quality(event.human_score, event.auto_score)
    if event.quality is not None and event.status == "ok":
        event.reward = reward(event.quality, event.cost_usd, event.latency_ms / 1000, cfg)
    db.commit()
    learner_state.apply_pending_updates(db, cfg)
    return event
