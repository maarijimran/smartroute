"""Router v2 inside the gateway: calibrated policies, quality floor, cards learning from ratings.

A small hand-built router stands in for the one trained on Kaggle: difficulty grows with
the request's estimated complexity, and the three mock models have known levels
(local weak, cheap medium, strong good)."""

import json

import numpy as np
import pytest
from sqlalchemy import select

from app.core.routing import qfeatures
from app.core.routing.irt import ModelCard, QueryModel
from app.core.routing.router_v2 import RouterV2, set_router_v2
from app.models import EventQueryFeatures, ModelCardRow

LEVELS = {"mock:mock-local": -1.0, "mock:mock-cheap": 0.5, "mock:mock-strong": 2.0}


def make_router(cards=LEVELS) -> RouterV2:
    names = list(qfeatures.NAMES)
    p = len(names)
    w_d = np.zeros(p)
    w_d[names.index("complexity")] = 3.0  # harder requests are harder for every model
    qm = QueryModel(names, np.zeros(p), np.ones(p), np.zeros((2, p)), w_d,
                    prior_mean=np.zeros(3), prior_cov=np.eye(3) * 0.5)
    return RouterV2(
        version="test-v1", qm=qm, embedding_dim=0, feature_version="default",
        cards={k: ModelCard(np.array([0.0, 0.0, b]), np.eye(3) * 0.01, 50) for k, b in cards.items()},
    )


@pytest.fixture(autouse=True)
def router():
    r = make_router()
    set_router_v2(r)
    yield r
    set_router_v2(None, clear=True)


def set_policy(client, root, **changes):
    policy = client.get("/api/policy", headers=root).json()
    policy.update(changes)
    r = client.put("/api/policy", json=policy, headers=root)
    assert r.status_code == 200, r.text


def ask(client, root, text="Write a haiku about rain."):
    session = client.post("/api/chat/sessions", json={}, headers=root).json()
    r = client.post(f"/api/chat/sessions/{session['id']}/messages", json={"content": text}, headers=root)
    events = [json.loads(line[6:]) for line in r.text.splitlines() if line.startswith("data: ") and line != "data: [DONE]"]
    return [e for e in events if e.get("type") == "done"][-1]["meta"]


def test_calibrated_policy_routes_with_cards_and_explains_why(client, root):
    set_policy(client, root, routing_policy="calibrated", quality_floor=0.0)
    meta = ask(client, root)
    assert meta["policy"] == "calibrated"
    assert meta["explanation"].startswith("calibrated router")
    assert set(meta["scores"]) == set(meta["eligible"])
    for parts in meta["scores"].values():
        assert parts["card"] == "trained" and 0 < parts["predicted_quality"] < 1 and "quality_sd" in parts
    # Without a floor, the cheap model wins: decent quality at a fraction of the strong price.
    assert meta["model"] == "mock-cheap"


def test_quality_floor_keeps_a_weak_model_off_requests_it_would_fail(client, root):
    set_policy(client, root, routing_policy="calibrated", quality_floor=0.5)
    meta = ask(client, root)
    assert meta["model"] == "mock-strong"
    assert "below quality floor" in meta["explanation"]
    assert meta["scores"]["mock-local"]["below_floor"] and not meta["scores"]["mock-strong"]["below_floor"]


def test_floor_is_ignored_when_no_model_clears_it(client, root):
    set_policy(client, root, routing_policy="calibrated", quality_floor=0.99)
    meta = ask(client, root)
    assert meta["status"] == "ok" and meta["model"]
    assert "no model clears the quality floor" in meta["explanation"]


def test_unknown_model_uses_the_prior_and_ucb_explores_it(client, root):
    set_router_v2(make_router({"mock:mock-local": -1.0, "mock:mock-strong": 2.0}))  # cheap never seen
    set_policy(client, root, routing_policy="calibrated_ucb", quality_floor=0.0, v2_ucb_alpha=3.0)
    meta = ask(client, root)
    cheap = meta["scores"]["mock-cheap"]
    assert cheap["card"] == "uncalibrated"
    assert cheap["quality_sd"] > meta["scores"]["mock-strong"]["quality_sd"]
    assert cheap["bonus"] > meta["scores"]["mock-strong"]["bonus"]


def test_untrained_router_falls_back_to_rules(client, root):
    set_router_v2(None)
    set_policy(client, root, routing_policy="calibrated")
    meta = ask(client, root)
    assert meta["policy"] == "rules"
    assert any("Router v2 has not been trained" in n for n in meta["notices"])


def test_ratings_update_the_answering_models_card(client, root, db):
    set_policy(client, root, routing_policy="calibrated", quality_floor=0.0, update_batch_size=1)
    meta = ask(client, root)
    stored = db.get(EventQueryFeatures, meta["event_id"])
    assert stored is not None and stored.model_key == "mock:mock-cheap" and len(stored.xq) == len(qfeatures.NAMES)
    r = client.post("/api/feedback", json={"event_id": meta["event_id"], "correctness": 5, "relevance": 5,
                                           "completeness": 5, "usefulness": 5}, headers=root)
    assert r.status_code == 200, r.text
    db.expire_all()
    row = db.execute(select(ModelCardRow).where(ModelCardRow.model_key == "mock:mock-cheap")).scalars().first()
    assert row is not None and row.status == "learning" and row.card["n"] == 51
    assert row.card["theta"][-1] > 0.5  # a top rating raised the level
    assert db.get(EventQueryFeatures, meta["event_id"]).card_applied


def test_baseline_policies_are_unaffected(client, root):
    set_policy(client, root, routing_policy="rules")
    meta = ask(client, root)
    assert meta["policy"] == "rules" and "scores" in meta
