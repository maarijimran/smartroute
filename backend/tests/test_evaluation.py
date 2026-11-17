"""Evaluation harness: scoring, statistics, replay and the privacy suite."""

import numpy as np
import pytest

from app.core.policy_config import PolicyConfig
from app.evaluation import analysis as an
from app.evaluation.privacy_suite import build_suite, run_suite
from app.evaluation.scoring import score_answer, token_f1
from app.evaluation.synthetic import SYNTHETIC_CFG, synthetic_table


def test_scoring():
    assert token_f1("The BERT model", "bert model") == 1.0
    assert token_f1("completely different", "bert model") == 0.0
    assert score_answer("They use SQuAD and NewsQA.", ["SQuAD", "SQuAD and NewsQA"]) > 0.7
    assert score_answer("Yes, it does.", ["Yes"]) == 1.0 and score_answer("No.", ["Yes"]) == 0.0
    assert score_answer("The paper does not mention this.", [], unanswerable=True) == 1.0
    assert score_answer("It is 42.", [], unanswerable=True) == 0.0
    ref = "we propose a router that lowers api cost while keeping answer quality"
    good = score_answer("A router that lowers API cost while keeping answer quality.", [ref], kind="summary")
    padded = score_answer(ref + " " + "filler words " * 80, [ref], kind="summary")
    assert good > 0.7 and padded < good


def test_cluster_bootstrap_is_wider_than_naive_when_clusters_correlate():
    rng = np.random.default_rng(0)
    cluster_effect = rng.normal(size=30)
    clusters = np.repeat(np.arange(30), 10)
    values = cluster_effect[clusters] + rng.normal(scale=0.1, size=300)
    _, lo, hi = an.cluster_bootstrap(values, clusters, seed=1)
    _, nlo, nhi = an.cluster_bootstrap(values, np.arange(300), seed=1)
    assert (hi - lo) > 2 * (nhi - nlo)


def test_ips_recovers_the_value_of_a_fixed_policy():
    rng = np.random.default_rng(0)
    n, k = 20000, 3
    true_mean = np.array([0.2, 0.5, 0.8])
    logged = rng.integers(0, k, size=n)
    rewards = true_mean[logged] + rng.normal(scale=0.05, size=n)
    est = an.ips_value(rewards, np.full(n, 1 / k), logged, np.full(n, 2))
    assert est["ips"] == pytest.approx(0.8, abs=0.03) and est["snips"] == pytest.approx(0.8, abs=0.01)


@pytest.fixture(scope="module")
def table():
    return synthetic_table(n_docs=120, per_doc=3, seed=0)


def test_table_shapes_and_oracle(table):
    cfg = SYNTHETIC_CFG
    assert len(table) == 360 and table.quality.shape == (360, 3)
    test = table.split("test")
    oracle = an.summarise(test, an.choose_oracle(test, cfg), cfg)
    for model in test.models:
        fixed = an.summarise(test, an.choose_fixed(test, model), cfg)
        assert fixed["reward"] <= oracle["reward"] + 1e-9 and fixed["regret"] >= 0
    assert oracle["regret"] == pytest.approx(0.0)


def test_learned_routers_beat_fixed_models_on_synthetic_data(table):
    """Sanity check of the machinery on data where routing is learnable by
    construction. It says nothing about real models."""
    cfg = SYNTHETIC_CFG
    train, test = table.split("train"), table.split("test")
    arms = an.fit_arms(train, cfg)
    lat = an.mean_latency(train)
    frozen = an.summarise(test, an.choose_frozen(test, arms, cfg, lat), cfg)
    knn = an.summarise(test, an.choose_knn(test, train, cfg), cfg)
    best_fixed = max(an.summarise(test, an.choose_fixed(test, m), cfg)["reward"] for m in test.models)
    assert frozen["reward"] > best_fixed and knn["reward"] > best_fixed

    strong = test.tier_model("strong")
    cmp = an.compare_to_baseline(test, an.choose_frozen(test, arms, cfg, lat), strong)
    assert cmp["cost_saving"] > 0.2 and cmp["quality_diff_ci"][0] <= cmp["quality_diff"] <= cmp["quality_diff_ci"][1]
    matched = an.random_at_matched_cost(test, frozen["cost_usd"], cfg)
    assert matched["cost_usd"] == pytest.approx(frozen["cost_usd"], rel=1e-6)
    assert frozen["quality"] > matched["quality"]


def test_replay_shows_only_the_chosen_arm_and_updates_in_batches(table):
    cfg = SYNTHETIC_CFG.model_copy(update={"update_batch_size": 50})
    test = table.split("test")
    stream = an.make_stream(test, epochs=4, seed=1)
    run = an.replay(test, stream, "bandit", cfg, seed=1)
    assert run.versions == len(stream) // 50
    assert np.all(run.propensities > 0) and np.all(run.propensities <= 1)
    assert run.regret[-1] >= 0 and len(run.rewards) == len(stream)
    # A cold-start bandit improves as it learns.
    assert run.window_mean(0.75, 1.0) > run.window_mean(0.0, 0.25)
    frozen = an.replay(test, stream, "frozen", cfg, arms=an.fit_arms(table.split("train"), cfg), seed=1)
    assert frozen.versions == 0 and np.all(frozen.propensities == 1.0)


def test_adaptive_router_recovers_from_a_silent_quality_drop(table):
    cfg = SYNTHETIC_CFG.model_copy(update={"update_batch_size": 25, "eps_start": 0.1, "eps_end": 0.05})
    train, test = table.split("train"), table.split("test")
    arms = an.fit_arms(train, cfg)
    stream = an.make_stream(test, epochs=12, seed=2)
    drift = an.Drift("quality", test.tier_model("cheap"), factor=0.2, start_frac=0.3)
    frozen = an.replay(test, stream, "frozen", cfg, arms=arms, drift=drift, seed=2)
    bandit = an.replay(test, stream, "bandit", cfg, arms=arms, drift=drift, seed=2)
    assert bandit.window_mean(0.7, 1.0) > frozen.window_mean(0.7, 1.0)


def test_task_shift_stream_orders_tasks(table):
    test = table.split("test")
    stream = an.make_stream(test, order="task_shift", seed=0)
    late = np.isin(test.tasks[stream], ["summary", "explain"])
    assert not late[: (~late).sum()].any() and late[(~late).sum():].all()


def test_privacy_suite_has_no_enforcement_failures():
    cases = build_suite()
    assert len(cases) == 200
    report = run_suite(cases)
    assert report["enforcement"]["unauthorized_dispatches"] == 0
    # With regex detectors only, every structured identifier must be caught; the
    # only expected misses are bare person names, which need the ML detectors.
    assert report["detector"]["pattern_detectable_only"]["recall"] == 1.0
    assert report["detector"]["needs_ml_detector"]["recall"] == 0.0
    assert report["enforcement"]["leaks_from_missed_detection"] == 10
