"""Router v2: predict answer quality from query difficulty and model ability.

    quality(x, m) = sigmoid( a_m · s(x) + b_m − d(x) )

- d(x), s(x): the query model. Difficulty and a k-dimensional skill profile, linear in the
  standardised v2 features (qfeatures.py plus embedding dimensions). Learned once, from
  the answers of several models of different strength.
- a_m, b_m: the model card. k abilities and a level, with a covariance. Learned per model
  from a few calibration answers, so a tier's model can change without retraining.

This is multidimensional item response theory (models are test-takers, requests are
items), as in IRT-Router (ACL 2025). Quality targets may be fractional (judge grades
0–1); the loss is binary cross-entropy either way.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

OOD_THRESHOLD = 4.0  # mean squared standardised feature value above which a request is "unusual"


def sigmoid(x):
    return 1.0 / (1.0 + np.exp(-np.clip(x, -30.0, 30.0)))


# --------------------------------------------------------------------- query model


@dataclass
class QueryModel:
    names: list[str]
    mean: np.ndarray  # (p,) feature means of the training data
    scale: np.ndarray  # (p,) feature standard deviations
    W: np.ndarray  # (k, p) skill profile s(x) = W z
    w_d: np.ndarray  # (p,)  difficulty d(x) = w_d · z
    prior_mean: np.ndarray  # (k+1,) the average training model's card
    prior_cov: np.ndarray  # (k+1, k+1) spread of the training models' cards
    meta: dict = field(default_factory=dict)

    @property
    def k(self) -> int:
        return int(self.W.shape[0])

    def standardize(self, x) -> np.ndarray:
        return (np.asarray(x, dtype=float) - self.mean) / self.scale

    def project(self, x) -> tuple[np.ndarray, np.ndarray]:
        """Returns (phi, d): phi = [s(x), 1] and the difficulty. Accepts one row or a matrix."""
        z = self.standardize(x)
        s = z @ self.W.T
        ones = np.ones(s.shape[:-1] + (1,))
        return np.concatenate([s, ones], axis=-1), z @ self.w_d

    def ood_score(self, x) -> float:
        """How unlike the training data a request is (1 ≈ typical)."""
        return float(np.mean(self.standardize(x) ** 2))

    def to_json(self) -> dict:
        return {
            "names": list(self.names), "mean": self.mean.tolist(), "scale": self.scale.tolist(),
            "W": self.W.tolist(), "w_d": self.w_d.tolist(),
            "prior_mean": self.prior_mean.tolist(), "prior_cov": self.prior_cov.tolist(), "meta": self.meta,
        }

    @classmethod
    def from_json(cls, d: dict) -> "QueryModel":
        return cls(
            names=list(d["names"]), mean=np.array(d["mean"]), scale=np.array(d["scale"]),
            W=np.array(d["W"]), w_d=np.array(d["w_d"]),
            prior_mean=np.array(d["prior_mean"]), prior_cov=np.array(d["prior_cov"]), meta=d.get("meta", {}),
        )


# ---------------------------------------------------------------------- model card


@dataclass
class ModelCard:
    theta: np.ndarray  # (k+1,) abilities and level
    cov: np.ndarray  # (k+1, k+1) uncertainty about theta
    n: int = 0  # answers this card has learned from

    @classmethod
    def prior(cls, qm: QueryModel) -> "ModelCard":
        """An unknown model: the average training model, with the spread of all of them."""
        return cls(qm.prior_mean.copy(), qm.prior_cov.copy(), 0)

    def predict(self, qm: QueryModel, x, extra_var: float = 0.0) -> tuple[np.ndarray, np.ndarray]:
        """Expected quality and its standard deviation, for one row or a matrix of rows."""
        phi, d = qm.project(x)
        eta = phi @ self.theta - d
        var = np.einsum("...i,ij,...j->...", phi, self.cov, phi) + extra_var
        mean = sigmoid(eta / np.sqrt(1.0 + math.pi * var / 8.0))  # probit approximation
        p = sigmoid(eta)
        return mean, p * (1.0 - p) * np.sqrt(var)

    def update(self, qm: QueryModel, x, y, iters: int = 50) -> "ModelCard":
        """Bayesian update with new answers (Laplace approximation, Newton steps).
        The current card is the prior, so updates can be applied batch by batch."""
        phi, d = qm.project(np.atleast_2d(x))
        y = np.asarray(y, dtype=float).reshape(-1)
        prior_prec = np.linalg.inv(self.cov)
        t = self.theta.copy()
        for _ in range(iters):
            p = sigmoid(phi @ t - d)
            grad = phi.T @ (p - y) + prior_prec @ (t - self.theta)
            hess = phi.T @ (phi * (p * (1 - p))[:, None]) + prior_prec
            step = np.linalg.solve(hess, grad)
            t = t - step
            if float(np.linalg.norm(step)) < 1e-9:
                break
        p = sigmoid(phi @ t - d)
        hess = phi.T @ (phi * (p * (1 - p))[:, None]) + prior_prec
        cov = np.linalg.inv(hess)
        return ModelCard(t, 0.5 * (cov + cov.T), self.n + len(y))

    def quality_uncertainty(self, qm: QueryModel, x_ref) -> float:
        """Mean standard deviation of predicted quality over reference requests."""
        return float(np.mean(self.predict(qm, x_ref)[1]))

    def to_json(self) -> dict:
        return {"theta": self.theta.tolist(), "cov": self.cov.tolist(), "n": self.n}

    @classmethod
    def from_json(cls, d: dict) -> "ModelCard":
        return cls(np.array(d["theta"]), np.array(d["cov"]), int(d.get("n", 0)))


# ------------------------------------------------------------------------ training


def fit_query_model(
    X,
    model_ids: list[str],
    y,
    names: list[str],
    k: int = 2,
    l2: float = 1e-2,
    steps: int = 4000,
    lr: float = 0.03,
    seed: int = 0,
    var_floor: float = 0.25,
) -> tuple[QueryModel, dict[str, ModelCard]]:
    """Fits difficulty, skills and the training models' cards together.

    X: (n, p) features of each answered request; model_ids: which model answered;
    y: quality in [0, 1]. Returns the query model and a card per training model.
    Full-batch Adam on mean binary cross-entropy with L2 on everything but the levels."""
    X = np.asarray(X, dtype=float)
    y = np.asarray(y, dtype=float)
    mean = X.mean(axis=0)
    scale = X.std(axis=0)
    scale[scale < 1e-8] = 1.0
    Z = (X - mean) / scale
    models = sorted(set(model_ids))
    m_idx = np.array([models.index(m) for m in model_ids])
    n, p = Z.shape
    M = len(models)
    rng = np.random.default_rng(seed)
    params = {
        "W": rng.normal(0, 0.1, (k, p)),
        "w_d": np.zeros(p),
        "A": rng.normal(0, 0.1, (M, k)),
        "B": np.zeros(M),
    }
    moments = {key: (np.zeros_like(v), np.zeros_like(v)) for key, v in params.items()}
    b1, b2, eps = 0.9, 0.999, 1e-8
    for step in range(1, steps + 1):
        W, w_d, A, B = params["W"], params["w_d"], params["A"], params["B"]
        S = Z @ W.T  # (n, k)
        eta = np.sum(A[m_idx] * S, axis=1) + B[m_idx] - Z @ w_d
        g = (sigmoid(eta) - y) / n  # d loss / d eta
        grads = {
            "W": (A[m_idx] * g[:, None]).T @ Z + l2 * W,
            "w_d": -(Z.T @ g) + l2 * w_d,
            "A": np.zeros_like(A),
            "B": np.bincount(m_idx, weights=g, minlength=M),
        }
        np.add.at(grads["A"], m_idx, S * g[:, None])
        grads["A"] += l2 * A
        for key in params:
            m1, m2 = moments[key]
            m1[:] = b1 * m1 + (1 - b1) * grads[key]
            m2[:] = b2 * m2 + (1 - b2) * grads[key] ** 2
            params[key] -= lr * (m1 / (1 - b1**step)) / (np.sqrt(m2 / (1 - b2**step)) + eps)

    thetas = np.column_stack([params["A"], params["B"]])
    prior_mean = thetas.mean(axis=0)
    spread = np.cov(thetas.T) if M >= 3 else np.zeros((k + 1, k + 1))
    prior_cov = spread + var_floor * np.eye(k + 1)  # a new model may be stronger or weaker than all seen so far
    qm = QueryModel(list(names), mean, scale, params["W"], params["w_d"], prior_mean, prior_cov,
                    meta={"k": k, "l2": l2, "steps": steps, "models": models, "rows": int(n)})
    cards = {}
    for i, m in enumerate(models):
        rows = m_idx == i
        start = ModelCard(thetas[i].copy(), 10.0 * np.eye(k + 1), 0)  # weak prior: the data decides
        cards[m] = start.update(qm, X[rows], y[rows])
    return qm, cards


# ----------------------------------------------------------------- calibration


def select_items(qm: QueryModel, card: ModelCard, X_pool, n: int, exclude: set[int] | None = None) -> list[int]:
    """Greedy choice of the n most informative calibration questions (D-optimal design).

    Each pick maximises p(1−p)·phiᵀΣphi, the expected shrinkage of the card's uncertainty,
    and the covariance is updated as if the answer had been seen (Sherman–Morrison)."""
    phi, d = qm.project(np.atleast_2d(X_pool))
    p = sigmoid(phi @ card.theta - d)
    w = p * (1 - p)
    sigma = card.cov.copy()
    taken = set(exclude or ())
    picks: list[int] = []
    for _ in range(min(n, len(phi) - len(taken))):
        sp = phi @ sigma  # (m, k+1)
        info = w * np.einsum("ij,ij->i", sp, phi)
        if taken:
            info[list(taken)] = -np.inf
        i = int(np.argmax(info))
        picks.append(i)
        taken.add(i)
        v = sigma @ phi[i]
        sigma = sigma - np.outer(v, v) * (w[i] / (1.0 + w[i] * phi[i] @ v))
    return picks


def calibrate(
    qm: QueryModel,
    X_pool,
    answer,
    x_ref,
    card: ModelCard | None = None,
    batch: int = 10,
    max_items: int = 60,
    min_items: int = 20,
    tolerance: float = 0.05,
) -> tuple[ModelCard, list[int]]:
    """Asks the most informative questions in batches until the predicted-quality
    uncertainty on x_ref is below `tolerance` (after at least min_items) or max_items.

    answer(indices) -> quality scores in [0, 1] for those pool rows (the caller runs the
    model and scores the answers automatically)."""
    X_pool = np.atleast_2d(np.asarray(X_pool, dtype=float))
    card = card or ModelCard.prior(qm)
    asked: list[int] = []
    while len(asked) < max_items:
        picks = select_items(qm, card, X_pool, min(batch, max_items - len(asked)), exclude=set(asked))
        if not picks:
            break
        card = card.update(qm, X_pool[picks], answer(picks))
        asked += picks
        if len(asked) >= min_items and card.quality_uncertainty(qm, x_ref) < tolerance:
            break
    return card, asked


def auc(scores, labels) -> float:
    """Area under the ROC curve (labels 0/1), by ranks; 0.5 = no better than chance."""
    scores, labels = np.asarray(scores, dtype=float), np.asarray(labels, dtype=float)
    pos, neg = labels == 1, labels == 0
    if not pos.any() or not neg.any():
        return float("nan")
    order = scores.argsort()
    ranks = np.empty(len(scores))
    ranks[order] = np.arange(1, len(scores) + 1)
    return float((ranks[pos].sum() - pos.sum() * (pos.sum() + 1) / 2) / (pos.sum() * neg.sum()))
