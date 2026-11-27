"""Router maths: arms, exploration schedule, propensities, rules and reward."""

import numpy as np
import pytest

from app.core.features import FeatureExtractor
from app.core.policy_config import PolicyConfig
from app.core.reward import combine_quality, human_score, reward
from app.core.routing.arms import ArmSet, RidgeArm
from app.core.routing.policies import (
    Candidate,
    EpsilonGreedyPolicy,
    FixedPolicy,
    FrozenPolicy,
    LinUCBPolicy,
    RequestInfo,
    RulesPolicy,
    epsilon,
    pacer_lambda,
    utility,
)

CANDS = [
    Candidate("local", "local", True, 0.0, 5.0),
    Candidate("cheap", "cheap", False, 0.0002, 2.0),
    Candidate("strong", "strong", False, 0.0015, 6.0),
]


def test_worked_reward_example_from_the_research_guide():
    cfg = PolicyConfig(c_ref_usd=0.002, l_ref_s=10)
    assert reward(0.90, 0.0015, 6, cfg) == pytest.approx(0.605)
    assert reward(0.80, 0.0002, 2, cfg) == pytest.approx(0.830)
    assert reward(0.66, 0.0, 5, cfg) == pytest.approx(0.730)


def test_quality_combination():
    assert human_score(5, 5, 5, 5) == 1.0 and human_score(1, 1, 1, 1) == 0.0
    assert combine_quality(0.8, 0.4) == (pytest.approx(0.68), "human+auto")
    assert combine_quality(None, 0.4) == (0.4, "auto")
    assert combine_quality(None, None) == (None, None)


def test_epsilon_schedule():
    cfg = PolicyConfig()
    assert epsilon(cfg, 0) == pytest.approx(0.10)
    assert epsilon(cfg, 500) == pytest.approx(0.06)
    assert epsilon(cfg, 1000) == pytest.approx(0.02)
    assert epsilon(cfg, 5000) == pytest.approx(0.02)  # never reaches zero, so IPS stays valid


def test_ridge_arm_recovers_a_linear_function():
    rng = np.random.default_rng(0)
    true = np.array([0.5, -0.2, 0.1])
    arm = RidgeArm(3, lam=0.01)
    for _ in range(400):
        x = rng.normal(size=3)
        arm.update(x, float(true @ x) + rng.normal(scale=0.01))
    assert np.allclose(arm.theta(), true, atol=0.02)
    restored = RidgeArm.from_json(arm.to_json(), lam=0.01)
    assert np.allclose(restored.theta(), arm.theta())


def test_forgetting_tracks_a_change():
    x = np.array([1.0])
    remember, forget = RidgeArm(1), RidgeArm(1)
    for y in [1.0] * 200 + [0.0] * 60:
        remember.update(x, y)
        forget.update(x, y, gamma=0.95)
    assert forget.predict(x) < 0.1 < remember.predict(x)


def test_epsilon_greedy_propensities_match_empirical_frequencies():
    cfg = PolicyConfig(eps_start=0.3, eps_end=0.3)
    arms = ArmSet(2)
    arms.arm("cheap").b = np.array([10.0, 0.0])  # makes "cheap" the greedy arm
    x = np.array([1.0, 0.0])
    rng = np.random.default_rng(1)
    policy = EpsilonGreedyPolicy()
    counts, logged = {}, {}
    n = 6000
    for _ in range(n):
        d = policy.select(x, CANDS, arms, cfg, rng)
        counts[d.arm] = counts.get(d.arm, 0) + 1
        logged[d.arm] = d.propensity
    assert sum(logged.values()) == pytest.approx(1.0)
    assert logged["cheap"] == pytest.approx(0.7 + 0.1)
    for name, p in logged.items():
        assert counts[name] / n == pytest.approx(p, abs=0.02)


def test_single_candidate_is_never_explored():
    d = EpsilonGreedyPolicy().select(np.zeros(2), CANDS[:1], ArmSet(2), PolicyConfig(), np.random.default_rng(0))
    assert d.arm == "local" and d.propensity == 1.0 and not d.explored


def test_split_utility_reacts_to_price_without_relearning():
    cfg = PolicyConfig()
    cheap, pricey = CANDS[1], Candidate("cheap", "cheap", False, 0.002, 2.0)
    assert utility(cfg, 0.8, cheap) > utility(cfg, 0.8, pricey)
    full = PolicyConfig(reward_mode="full")
    assert utility(full, 0.8, cheap) == utility(full, 0.8, pricey) == 0.8


def test_linucb_prefers_the_uncertain_arm_and_frozen_does_not():
    cfg = PolicyConfig(linucb_alpha=2.0, reward_mode="full")
    arms = ArmSet(1)
    x = np.array([1.0])
    for _ in range(300):
        arms.arm("cheap").update(x, 0.7)
    arms.arm("strong").update(x, 0.66)  # seen once: large uncertainty bonus
    two = CANDS[1:]
    assert FrozenPolicy().select(x, two, arms, cfg).arm == "cheap"
    assert LinUCBPolicy().select(x, two, arms, cfg).arm == "strong"


def test_budget_pacer():
    assert pacer_lambda(10, 100, 0.5) == 0.0  # under pace
    assert 0 < pacer_lambda(75, 100, 0.5) <= 1.0  # ahead of pace
    assert pacer_lambda(10, None, 0.5) == 0.0


def test_rules_policy():
    rules = RulesPolicy()
    short = RequestInfo("explain", 120, 0.2, False)
    hard = RequestInfo("doc_qa", 2000, 0.8, True)
    assert rules.select(short, CANDS).arm == "local"
    assert rules.select(hard, CANDS).arm == "strong"
    assert rules.select(RequestInfo("summary", 2000, 0.3, True), CANDS).arm == "cheap"
    # With cloud removed by the eligibility filter, rules stay inside what is left.
    assert rules.select(hard, CANDS[:1]).arm == "local"


def test_fixed_policy_never_reroutes():
    assert FixedPolicy(model="strong").select(RequestInfo("chat", 10, 0.1, False), CANDS[:2]) is None


def test_feature_vector_keeps_its_constant():
    fx = FeatureExtractor()
    x = fx.extract(
        prompt="q", in_tokens=500, est_out_tokens=250, has_document=True, complexity=0.4, task="doc_qa", local_load=0
    )
    names = fx.names()
    assert len(x) == fx.dim == len(names) == 11
    assert x[names.index("constant")] == 1.0
    assert x[names.index("task_doc_qa")] == 1.0 and x[names.index("task_summary")] == 0.0


def test_score_breakdown_explains_every_learned_decision():
    """The route details show quality + cost + speed (+ LinUCB bonus and pacer) per model;
    the parts must add up to the score that decided the route."""
    cfg = PolicyConfig()
    arms = ArmSet(1)
    x = np.array([1.0])
    for name, q in (("local", 0.70), ("cheap", 0.72), ("strong", 0.74)):
        for _ in range(50):
            arms.arm(name).update(x, q)
    decisions = [
        FrozenPolicy().select(x, CANDS, arms, cfg),
        EpsilonGreedyPolicy().select(x, CANDS, arms, cfg, np.random.default_rng(0)),
        LinUCBPolicy().select(x, CANDS, arms, cfg, pacer_lambda=0.5),
    ]
    for d in decisions:
        assert set(d.breakdown) == {c.name for c in CANDS}
        for name, p in d.breakdown.items():
            parts = p["quality"] + p["cost"] + p["speed"] + p.get("bonus", 0.0) + p.get("pacer", 0.0)
            assert parts == pytest.approx(p["total"], abs=1e-3)
            assert p["total"] == pytest.approx(d.scores[name], abs=1e-4)
            assert p["tier"] == name
    assert decisions[0].breakdown["local"]["cost"] == pytest.approx(cfg.weights.cost)  # free model: full cost score
