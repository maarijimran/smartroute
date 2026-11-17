"""End-to-end pipeline behaviour with mock models. The central assertion throughout
is on MockProvider.dispatched: the list of payloads that left the trusted boundary."""

from sqlalchemy import select

from app.core import pipeline
from app.core.policy_config import load_policy, save_policy
from app.core.privacy import scanner as scanner_module
from app.core.privacy.scanner import ScanResult
from app.core.providers.mock import MockProvider
from app.models import (
    ConfidentialEvent,
    Document,
    DocumentChunk,
    ModelEntry,
    PolicyState,
    RoutingEvent,
    User,
)

CNIC = "42101-1234567-1"
EASY = "What is overfitting?"
HARD = (
    "Compare the two training methods, analyze their trade-offs step by step, "
    "and justify which one is more robust and why does it generalise better?"
)


def root_user(db) -> User:
    return db.execute(select(User)).scalars().first()


def make_request(db, text, **kwargs):
    return pipeline.RouteRequest.for_user(root_user(db), [{"role": "user", "content": text}], **kwargs)


def go(db, request):
    plan = pipeline.prepare(db, request)
    return plan, pipeline.run_to_completion(plan)


def set_policy(db, **changes):
    cfg = load_policy(db).model_copy(update=changes)
    save_policy(db, cfg, root_user(db))


def set_model(db, name, **changes):
    model = db.execute(select(ModelEntry).where(ModelEntry.name == name)).scalars().first()
    for key, value in changes.items():
        setattr(model, key, value)
    db.commit()


def audit(db) -> ConfidentialEvent:
    return db.execute(select(ConfidentialEvent)).scalars().one()


# ------------------------------------------------------------------ routing


def test_rules_route_easy_to_local_and_hard_to_strong(db):
    _, easy = go(db, make_request(db, EASY))
    assert (easy.status, easy.model) == ("ok", "mock-local")
    assert MockProvider.dispatched == []
    _, hard = go(db, make_request(db, HARD))
    assert (hard.status, hard.model) == ("ok", "mock-strong")
    assert len(MockProvider.dispatched) == 1
    assert hard.cost_usd > 0 and easy.cost_usd == 0


def test_event_is_logged_with_propensity_and_eligible_set(db):
    plan, outcome = go(db, make_request(db, HARD, policy_override="bandit", seed=3))
    event = db.get(RoutingEvent, plan.event_id)
    assert event.status == "ok" and event.chosen_model == outcome.model
    assert 0 < event.propensity <= 1
    assert event.eligible == ["mock-cheap", "mock-local", "mock-strong"]
    assert len(event.features) == 11 and event.policy_name == "bandit"


# ------------------------------------------------------------------ privacy


def test_local_only_mode_never_reaches_cloud(db):
    plan, outcome = go(db, make_request(db, HARD, privacy_mode="local_only"))
    assert outcome.model == "mock-local" and MockProvider.dispatched == []
    assert plan.exclusions["mock-strong"] == "privacy:local_only_mode"


def test_pii_blocks_cloud_and_is_audited_with_a_masked_preview(db):
    _, outcome = go(db, make_request(db, f"{HARD} My CNIC is {CNIC}."))
    assert outcome.model == "mock-local" and outcome.sensitive
    assert MockProvider.dispatched == []
    record = audit(db)
    assert record.decision == "cloud_blocked" and record.decision_reason == "confidential_not_permitted"
    assert record.entity_types == ["NATIONAL_ID"] and not record.left_trusted_boundary
    assert CNIC not in record.masked_preview and "[NATIONAL_ID]" in record.masked_preview


def test_permitted_user_needs_consent_per_request(db):
    user = root_user(db)
    user.allow_confidential_cloud = True
    db.commit()
    text = f"{HARD} My CNIC is {CNIC}."
    plan, outcome = go(db, make_request(db, text))
    assert plan.exclusions["mock-strong"] == "privacy:consent_required" and MockProvider.dispatched == []

    _, outcome = go(db, make_request(db, text, consent=True, pinned_model="mock-strong"))
    assert outcome.status == "ok" and outcome.model == "mock-strong"
    assert len(MockProvider.dispatched) == 1
    allowed = db.execute(
        select(ConfidentialEvent).where(ConfidentialEvent.decision == "cloud_allowed")
    ).scalars().one()
    assert allowed.left_trusted_boundary and allowed.consent_given and allowed.destination_model == "mock-strong"


def test_institutional_prohibition_overrides_consent(db):
    user = root_user(db)
    user.allow_confidential_cloud = True
    db.commit()
    set_policy(db, cloud_enabled=False)
    _, outcome = go(db, make_request(db, f"{HARD} CNIC {CNIC}", consent=True))
    assert outcome.model == "mock-local" and MockProvider.dispatched == []


class FailingScanner:
    def scan(self, text):
        return ScanResult(failed=True, failure_reason="boom")


def test_scanner_failure_blocks_cloud(db):
    scanner_module.set_scanner(FailingScanner())
    plan, outcome = go(db, make_request(db, HARD))
    assert outcome.model == "mock-local" and MockProvider.dispatched == []
    assert plan.exclusions["mock-cheap"] == "privacy:scanner_failure"


def test_safe_abstention_when_no_local_model_can_take_a_confidential_request(db):
    set_model(db, "mock-local", enabled=False)
    plan, outcome = go(db, make_request(db, f"Explain this, my CNIC is {CNIC}"))
    assert outcome.status == "abstained" and outcome.abstain_kind == "privacy"
    assert "confidential" in plan.abstain_reason
    assert MockProvider.dispatched == []
    assert db.get(RoutingEvent, plan.event_id).status == "abstained"


def test_final_gate_blocks_a_payload_that_changed_after_selection(db):
    plan = pipeline.prepare(db, make_request(db, HARD))
    assert plan.decision.arm == "mock-strong"
    plan.draft.question += f" CNIC {CNIC}"  # simulates content added after eligibility
    outcome = pipeline.run_to_completion(plan)
    assert MockProvider.dispatched == []
    assert outcome.status == "ok" and outcome.model == "mock-local"
    assert plan.exclusions["mock-strong"].startswith("final_gate:")


def test_final_gate_abstains_rather_than_rerouting_a_pinned_request(db):
    plan = pipeline.prepare(db, make_request(db, HARD, pinned_model="mock-strong"))
    plan.draft.question += f" CNIC {CNIC}"
    outcome = pipeline.run_to_completion(plan)
    assert outcome.status == "abstained" and MockProvider.dispatched == []


def test_session_label_propagates(db):
    _, outcome = go(db, make_request(db, HARD, session_confidential=True))
    assert outcome.model == "mock-local" and MockProvider.dispatched == []


def test_confidential_document_blocks_cloud_and_other_users_documents_are_ignored(db):
    user = root_user(db)
    other = User(email="other@test.local", password_hash="x")
    db.add(other)
    db.flush()
    mine = Document(user_id=user.id, filename="grades.txt", label="confidential", sha256="a")
    theirs = Document(user_id=other.id, filename="secret.txt", label="public", sha256="b")
    db.add_all([mine, theirs])
    db.flush()
    db.add(DocumentChunk(document_id=mine.id, idx=0, page=1, text="The robust method generalises better."))
    db.add(DocumentChunk(document_id=theirs.id, idx=0, page=1, text="Their robust secret method."))
    db.commit()

    plan, outcome = go(db, make_request(db, HARD, document_ids=[theirs.id]))
    assert plan.draft.evidence == []  # ownership enforced inside the pipeline

    plan, outcome = go(db, make_request(db, HARD, document_ids=[mine.id]))
    assert [e.document for e in plan.draft.evidence] == ["grades.txt"]
    assert outcome.model == "mock-local" and outcome.sources[0]["page"] == 1
    assert "confidential_document" in audit(db).triggers


# ------------------------------------------------------- failures and limits


def test_failed_model_falls_back_and_is_attributed_separately(db):
    set_model(db, "mock-strong", params={"mock": "fail"})
    plan, outcome = go(db, make_request(db, HARD))
    assert outcome.status == "ok" and outcome.fallback_from == "mock-strong"
    assert outcome.model != "mock-strong" and outcome.attempts == 2
    failed = db.execute(select(RoutingEvent).where(RoutingEvent.status == "attempt_failed")).scalars().one()
    assert failed.chosen_model == "mock-strong" and failed.reward == -1.0
    strong = db.execute(select(ModelEntry).where(ModelEntry.name == "mock-strong")).scalars().one()
    assert strong.unhealthy_until is not None  # circuit breaker
    plan2, _ = go(db, make_request(db, HARD + " again"))
    assert plan2.exclusions["mock-strong"] == "unhealthy"


def test_fallback_repeats_the_privacy_check(db):
    """A local-only request whose local model fails must stop, not fall back to cloud."""
    set_model(db, "mock-local", params={"mock": "fail"})
    _, outcome = go(db, make_request(db, EASY, privacy_mode="local_only"))
    assert outcome.status == "failed" and MockProvider.dispatched == []


def test_empty_answer_counts_as_failure(db):
    set_policy(db, max_retries=0)
    set_model(db, "mock-local", params={"mock": "empty"})
    plan, outcome = go(db, make_request(db, EASY))
    assert outcome.status == "empty"
    assert db.get(RoutingEvent, plan.event_id).reward == -1.0


def test_budget_and_context_filters(db):
    user = root_user(db)
    user.monthly_budget_usd = 0.0000001
    db.commit()
    plan, outcome = go(db, make_request(db, HARD))
    assert plan.exclusions["mock-strong"] == "user_budget" and outcome.model == "mock-local"

    user.monthly_budget_usd = None
    db.commit()
    set_model(db, "mock-strong", context_window=600)
    plan, _ = go(db, make_request(db, HARD + " once more"))
    assert plan.exclusions["mock-strong"] == "context_window"


def test_history_is_trimmed_with_a_visible_notice_when_nothing_fits(db):
    for name in ("mock-cheap", "mock-strong"):
        set_model(db, name, enabled=False)
    set_model(db, "mock-local", context_window=900)
    history = []
    for i in range(6):
        history += [{"role": "user", "content": f"question {i} " + "word " * 120}, {"role": "assistant", "content": "ok"}]
    request = pipeline.RouteRequest.for_user(root_user(db), history + [{"role": "user", "content": EASY}])
    plan, outcome = go(db, request)
    assert outcome.status == "ok" and outcome.context_compressed
    assert len(plan.draft.history) < len(history) and plan.notices


def test_exact_cache_hits_only_for_non_confidential_requests(db):
    go(db, make_request(db, HARD))
    _, second = go(db, make_request(db, HARD))
    assert second.status == "cache_hit" and second.cost_usd == 0 and len(MockProvider.dispatched) == 1
    text = f"{EASY} CNIC {CNIC}"
    go(db, make_request(db, text))
    _, again = go(db, make_request(db, text))
    assert again.status == "ok"


# ------------------------------------------------------------------ learning


def test_scored_outcomes_update_the_bandit_in_batches(db):
    set_policy(db, routing_policy="bandit", update_batch_size=2, cache_enabled=False)
    plans = [go(db, make_request(db, f"{HARD} v{i}", seed=i))[0] for i in range(2)]
    pipeline.record_quality(db, plans[0].event_id, human=0.75)
    assert db.execute(select(PolicyState)).scalars().all() == []  # batch not full yet
    event = pipeline.record_quality(db, plans[1].event_id, human=0.5, auto=1.0)
    assert event.quality == 0.7 * 0.5 + 0.3 * 1.0 and event.quality_source == "human+auto"
    state = db.execute(
        select(PolicyState).where(PolicyState.name == "bandit", PolicyState.active.is_(True))
    ).scalars().one()
    assert state.version == 1 and state.state["n_scored"] == 2
    assert all(e.reward_applied for e in db.execute(select(RoutingEvent)).scalars())
    # The next decision is made by the updated policy version.
    plan, _ = go(db, make_request(db, HARD + " v9", seed=9))
    assert plan.policy_version == 1


def test_untrained_frozen_router_falls_back_to_rules_with_a_notice(db):
    plan, outcome = go(db, make_request(db, HARD, policy_override="frozen"))
    assert plan.policy_name == "rules" and outcome.status == "ok" and plan.notices
