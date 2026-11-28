"""Calibration of a tier's model from automatically scored questions.

A simulated model answers multiple-choice questions correctly with a probability set by
its hidden level and each question's difficulty; calibration must find that level from a
few dozen answers, respect the budget, skip flagged items for cloud models and fail
cleanly on a broken key."""

import numpy as np
import pytest
from sqlalchemy import select

from app.core import tiers
from app.core.providers.base import ChatResult, ProviderError
from app.core.routing import calibration, qfeatures
from app.core.routing.calibration import CalibrationSettings, calibrate_tier, score_item
from app.core.routing.irt import ModelCard, QueryModel, sigmoid
from app.core.routing.router_v2 import RouterV2, load_card, set_router_v2
from app.models import Attempt, User

NAMES = list(qfeatures.NAMES)
P = len(NAMES)
CX = NAMES.index("complexity")


def make_router() -> RouterV2:
    w_d = np.zeros(P)
    w_d[CX] = 4.0
    qm = QueryModel(NAMES, np.zeros(P), np.ones(P), np.zeros((2, P)), w_d,
                    prior_mean=np.zeros(3), prior_cov=np.eye(3) * 1.0)
    return RouterV2(version="calib-test", qm=qm, embedding_dim=0, feature_version="default")


def make_bank(n=150, seed=0, cnic_items=0):
    rng = np.random.default_rng(seed)
    items = []
    for i in range(n):
        x = np.zeros(P)
        x[CX] = rng.uniform(-1.0, 1.0)  # difficulty spread
        text = f"Question {i}: pick the right option. A) foo B) bar C) baz D) qux"
        if i < cnic_items:
            text += " The student's CNIC is 42101-1234567-1."
        items.append({"id": f"q{i}", "kind": "mc", "golds": ["B"], "xq": x.tolist(), "reference": i % 3 == 0,
                      "messages": [{"role": "user", "content": text}]})
    return {"names": NAMES, "feature_version": "default", "items": items}


class HiddenAbilityProvider:
    """Answers "B" (correct) with probability sigmoid(level − 4·complexity)."""

    def __init__(self, level, bank, seed=1, fail_status=None):
        self.level, self.fail_status = level, fail_status
        self.rng = np.random.default_rng(seed)
        self.by_text = {it["messages"][0]["content"]: np.array(it["xq"]) for it in bank["items"]}
        self.calls = 0

    def complete(self, req):
        self.calls += 1
        if self.fail_status:
            raise ProviderError("invalid key", status=self.fail_status)
        x = self.by_text[req.messages[0]["content"]]
        right = self.rng.random() < sigmoid(self.level - 4.0 * x[CX])
        return ChatResult(text="The answer is B." if right else "The answer is D.", in_tokens=200, out_tokens=10)


@pytest.fixture
def setup(db, monkeypatch):
    set_router_v2(make_router())
    root = db.execute(select(User).where(User.role == "superadmin")).scalars().first()
    # A cloud-like tier (mock adapter outside the local tier is treated as cloud).
    tiers.set_tier(db, "cheap", root, vendor="mock", model_id="hidden-model", price_in_per_mtok=1.0,
                   price_out_per_mtok=1.0, context_window=128000)

    def use(provider):
        monkeypatch.setattr(calibration, "build_provider", lambda spec, cred: provider)
        return provider

    yield root, use
    set_router_v2(None, clear=True)


@pytest.mark.parametrize("level", [-1.5, 0.0, 2.0])
def test_calibration_finds_the_hidden_level(db, setup, level):
    root, use = setup
    bank = make_bank()
    provider = use(HiddenAbilityProvider(level, bank))
    record = calibrate_tier(db, "cheap", root.id, CalibrationSettings(max_items=60), bank=bank)
    assert record["error"] is None
    assert 20 <= record["scored"] <= 60 and provider.calls == record["asked"]
    card, status = load_card(db, make_router(), "mock:hidden-model")
    assert status == "calibrated" and card.n == record["scored"]
    assert abs(card.theta[-1] - level) < 0.8  # the level, recovered from a few dozen right/wrong answers
    assert record["uncertainty"] is not None
    ledger = db.execute(select(Attempt).where(Attempt.purpose == "calibration")).scalars().all()
    assert len(ledger) == record["scored"] and record["cost_usd"] == pytest.approx(sum(a.cost_usd for a in ledger))


def test_calibration_stops_at_the_budget_cap(db, setup):
    root, use = setup
    bank = make_bank()
    use(HiddenAbilityProvider(0.0, bank))
    record = calibrate_tier(db, "cheap", root.id, CalibrationSettings(budget_usd=0.002), bank=bank)
    assert "budget cap" in record.get("note", "")
    assert record["cost_usd"] < 0.002 + 0.0003  # at most one call over


def test_broken_key_fails_cleanly_and_leaves_no_calibrated_card(db, setup):
    root, use = setup
    bank = make_bank()
    use(HiddenAbilityProvider(0.0, bank, fail_status=401))
    record = calibrate_tier(db, "cheap", root.id, CalibrationSettings(), bank=bank)
    assert record["error"] and "failed" in record["error"]
    _, status = load_card(db, make_router(), "mock:hidden-model")
    assert status == "uncalibrated"


def test_flagged_items_are_never_sent_to_a_cloud_model(db, setup):
    root, use = setup
    bank = make_bank(cnic_items=40)
    provider = use(HiddenAbilityProvider(0.0, bank))
    sent = []
    original = provider.complete

    def spy(req):
        sent.append(req.messages[0]["content"])
        return original(req)

    provider.complete = spy
    calibrate_tier(db, "cheap", root.id, CalibrationSettings(), bank=bank)
    assert sent and not any("CNIC" in s for s in sent)


def test_missing_router_or_bank_is_reported(db, setup, client):
    root, _ = setup
    from .conftest import login, ROOT

    headers = login(client, **ROOT)
    r = client.post("/api/tiers/cheap/calibrate", headers=headers)
    assert r.status_code == 422 and "bank" in r.text  # router set, bank file absent
    set_router_v2(None)
    r = client.post("/api/tiers/cheap/calibrate", headers=headers)
    assert r.status_code == 422 and "not been trained" in r.text


def test_users_cannot_calibrate(client, root):
    from .conftest import make_user

    user = make_user(client, root)
    assert client.post("/api/tiers/cheap/calibrate", headers=user).status_code == 403


@pytest.mark.parametrize("item,answer,score", [
    ({"kind": "mc", "golds": ["C"]}, "The answer is C.", 1.0),
    ({"kind": "mc", "golds": ["C"]}, "C) because ...", 1.0),
    ({"kind": "mc", "golds": ["C"]}, "Answer: B", 0.0),
    ({"kind": "numeric", "golds": ["1,250"]}, "So the total is 1250.", 1.0),
    ({"kind": "numeric", "golds": ["42"]}, "It is 41.", 0.0),
    ({"kind": "yes_no", "golds": ["Yes"]}, "Yes, they do.", 1.0),
    ({"kind": "unanswerable", "golds": [], "unanswerable": True}, "The paper does not mention this.", 1.0),
])
def test_automatic_scoring(item, answer, score):
    assert score_item(item, answer) == score


def test_prior_card_is_the_start_for_an_unknown_model(db, setup):
    card, status = load_card(db, make_router(), "mock:never-seen")
    assert status == "uncalibrated" and card.n == 0 and isinstance(card, ModelCard)
