"""Router v2 maths on synthetic data with known difficulties and abilities.

These tests check the properties the plan relies on (docs/plan_router_v2.md):
difficulty is learned once from several models, a new model is recovered from a few
calibration answers (also weaker or stronger than every training model), informative
questions beat random ones, and the uncertainty a policy needs is honest."""

import numpy as np
import pytest

from app.core.routing import qfeatures
from app.core.routing.irt import (
    ModelCard,
    QueryModel,
    auc,
    calibrate,
    fit_query_model,
    select_items,
    sigmoid,
)

P, K = 10, 2
rng = np.random.default_rng(7)
TRUE_W = rng.normal(0, 0.7, (K, P))
TRUE_WD = rng.normal(0, 0.8, P)
X_ALL = rng.normal(0, 1, (3000, P))
TRAIN, POOL, TEST = slice(0, 1500), slice(1500, 2400), slice(2400, 3000)
# Five training models of different strength, two held-out ones outside their range.
MODELS = {
    "m-weak": (np.array([0.2, -0.3]), -1.2),
    "m-low": (np.array([0.5, 0.1]), -0.5),
    "m-mid": (np.array([0.0, 0.6]), 0.0),
    "m-good": (np.array([0.7, 0.4]), 0.7),
    "m-best": (np.array([0.9, 0.8]), 1.3),
}
HELD_OUT = {
    "new-very-weak": (np.array([0.1, 0.0]), -2.2),
    "new-very-strong": (np.array([1.0, 1.0]), 2.3),
}


def true_p(model, X):
    a, b = (MODELS | HELD_OUT)[model]
    return sigmoid((X @ TRUE_W.T) @ a + b - X @ TRUE_WD)


@pytest.fixture(scope="module")
def trained():
    X, ids, y = [], [], []
    draw = np.random.default_rng(11)
    for m in MODELS:
        p = true_p(m, X_ALL[TRAIN])
        X.append(X_ALL[TRAIN])
        ids += [m] * len(p)
        y.append((draw.random(len(p)) < p).astype(float))  # right/wrong, like EmbedLLM
    names = [f"f{i}" for i in range(P)]
    return fit_query_model(np.vstack(X), ids, np.concatenate(y), names, k=K, steps=3000)


def log_loss(p, y):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def test_difficulty_is_learned_and_beats_a_difficulty_blind_router(trained):
    qm, cards = trained
    draw = np.random.default_rng(3)
    for m in MODELS:
        X = X_ALL[TEST]
        y = (draw.random(len(X)) < true_p(m, X)).astype(float)
        pred, _ = cards[m].predict(qm, X)
        blind = np.full(len(X), y.mean())  # what a per-model average (no difficulty) predicts
        assert auc(pred, y) > 0.75
        assert log_loss(pred, y) < log_loss(blind, y) - 0.05
        assert np.corrcoef(pred, true_p(m, X))[0, 1] > 0.9


@pytest.mark.parametrize("model", list(HELD_OUT))
def test_new_model_is_recovered_from_a_few_calibration_answers(trained, model):
    qm, _ = trained
    draw = np.random.default_rng(5)
    pool = X_ALL[POOL]
    answer = lambda idx: (draw.random(len(idx)) < true_p(model, pool[idx])).astype(float)  # noqa: E731
    prior = ModelCard.prior(qm)
    card, asked = calibrate(qm, pool, answer, X_ALL[TEST][:200], max_items=60)
    assert 20 <= len(asked) <= 60
    pred, std = card.predict(qm, X_ALL[TEST])
    truth = true_p(model, X_ALL[TEST])
    assert np.corrcoef(pred, truth)[0, 1] > 0.85
    assert abs(pred.mean() - truth.mean()) < 0.08  # level found although outside the training range
    assert std.mean() < 0.5 * prior.predict(qm, X_ALL[TEST])[1].mean()  # uncertainty shrank


def test_informative_questions_shrink_uncertainty_more_than_random_ones(trained):
    qm, _ = trained
    prior = ModelCard.prior(qm)
    pool = X_ALL[POOL]
    phi, d = qm.project(pool)

    def logdet_after(picks):
        p = sigmoid(phi[picks] @ prior.theta - d[picks])
        prec = np.linalg.inv(prior.cov) + phi[picks].T @ (phi[picks] * (p * (1 - p))[:, None])
        return -np.linalg.slogdet(prec)[1]

    chosen = select_items(qm, prior, pool, 20)
    random_runs = [logdet_after(list(np.random.default_rng(s).choice(len(pool), 20, replace=False))) for s in range(20)]
    assert len(set(chosen)) == 20
    assert logdet_after(chosen) < min(random_runs)


def test_router_knows_where_the_strong_model_helps(trained):
    """The scenario that motivated v2: with a much weaker local model, the predicted quality
    gap must be large exactly where the strong model really helps, and small where it does
    not (easy requests both answer; the very hardest neither answers)."""
    qm, cards = trained
    X = X_ALL[TEST]
    predicted_gap = cards["m-best"].predict(qm, X)[0] - cards["m-weak"].predict(qm, X)[0]
    true_gap = true_p("m-best", X) - true_p("m-weak", X)
    assert np.corrcoef(predicted_gap, true_gap)[0, 1] > 0.85
    helps = true_gap > 0.4
    assert helps.sum() > 30
    assert predicted_gap[helps].mean() > 0.3
    assert predicted_gap[true_gap < 0.1].mean() < 0.15


def test_unknown_model_is_uncertain_until_calibrated(trained):
    qm, cards = trained
    prior = ModelCard.prior(qm)
    known = cards["m-mid"]
    assert prior.n == 0 and known.n > 0
    assert prior.quality_uncertainty(qm, X_ALL[TEST]) > 3 * known.quality_uncertainty(qm, X_ALL[TEST])


def test_updates_can_be_applied_in_batches(trained):
    qm, _ = trained
    X = X_ALL[POOL][:40]
    y = (true_p("m-good", X) > 0.5).astype(float)
    once = ModelCard.prior(qm).update(qm, X, y)
    twice = ModelCard.prior(qm).update(qm, X[:20], y[:20]).update(qm, X[20:], y[20:])
    assert np.allclose(once.theta, twice.theta, atol=0.05) and twice.n == once.n == 40


def test_out_of_domain_requests_are_flagged(trained):
    qm, _ = trained
    assert qm.ood_score(X_ALL[TEST][0]) < 3
    assert qm.ood_score(X_ALL[TEST][0] + 6.0) > 4


def test_serialisation_round_trip(trained):
    qm, cards = trained
    qm2 = QueryModel.from_json(qm.to_json())
    card2 = ModelCard.from_json(cards["m-mid"].to_json())
    x = X_ALL[TEST][:5]
    assert np.allclose(cards["m-mid"].predict(qm, x)[0], card2.predict(qm2, x)[0])


def test_auc_helper():
    assert auc([0.1, 0.4, 0.35, 0.8], [0, 0, 1, 1]) == 0.75
    assert auc([1, 2, 3], [1, 1, 1]) != auc([1, 2, 3], [1, 1, 1])  # undefined -> nan


# ------------------------------------------------------------------ v2 query features


@pytest.mark.parametrize("question,kind", [
    ("Does the paper evaluate on Urdu?", "q_yes_no"),
    ("How many annotators labelled the data?", "q_numeric"),
    ("Which datasets are used for evaluation?", "q_extractive"),
    ("Why does the proposed model outperform the baseline?", "q_abstractive"),
])
def test_question_types(question, kind):
    qt = qfeatures.question_type(question)
    assert qt[kind] == 1.0
    assert sum(qt[k] for k in ("q_yes_no", "q_numeric", "q_extractive", "q_abstractive")) == 1.0


def test_retrieval_stats_reflect_whether_the_evidence_was_found():
    question = "Which optimizer and learning rate were used for training the transformer?"
    found = qfeatures.RetrievalStats.from_retrieval(
        question, [9.0, 2.0, 1.0], ["We train the transformer with the Adam optimizer and a learning rate of 3e-4."], 5)
    missed = qfeatures.RetrievalStats.from_retrieval(
        question, [1.1, 1.0, 0.9], ["The dataset contains 10k sentences from news articles."], 5)
    assert found.coverage > 0.7 > missed.coverage
    assert found.gap > missed.gap and found.top > missed.top
    assert qfeatures.RetrievalStats.from_retrieval(question, [], [], 5) == qfeatures.RetrievalStats()


def test_query_feature_vector_has_a_fixed_order():
    v = qfeatures.query_features(
        question="Is it fast?", in_tokens=100, est_out_tokens=50, complexity=0.3, history_tokens=0,
        has_document=False, follow_up=False, task="chat", retrieval=qfeatures.RetrievalStats(),
    )
    assert len(v) == len(qfeatures.NAMES)
    assert v[qfeatures.NAMES.index("q_yes_no")] == 1.0
