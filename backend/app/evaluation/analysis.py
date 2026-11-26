"""Offline evaluation on a full-information outcome table.

The table holds, for every benchmark request, the measured outcome of EVERY model
(quality, cost, latency). That makes three things possible:

- fixed baselines and an empirical oracle are exact look-ups;
- any policy can be scored without spending API money again;
- a bandit can be REPLAYED honestly: at each step it is shown only the outcome of
  the arm it picked, exactly like live traffic (predict first, update afterward).

Statistics: document-clustered bootstrap confidence intervals, because several
questions about one paper are not independent observations.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import numpy as np

from ..core.policy_config import PolicyConfig
from ..core.reward import FAILURE_REWARD
from ..core.routing.arms import ArmSet
from ..core.routing.policies import (
    Candidate,
    EpsilonGreedyPolicy,
    FrozenPolicy,
    LinUCBPolicy,
    RequestInfo,
    RulesPolicy,
)

LATENCY_EWMA_ALPHA = 0.2


@dataclass
class OutcomeTable:
    item_ids: list[str]
    doc_ids: np.ndarray  # cluster labels
    splits: np.ndarray
    tasks: np.ndarray
    models: list[str]
    tiers: dict[str, str]
    is_local: dict[str, bool]
    X: np.ndarray  # (n, d) context vectors
    quality: np.ndarray  # (n, k) in [0, 1]
    cost: np.ndarray  # (n, k) measured USD
    est_cost: np.ndarray  # (n, k) pre-dispatch estimate, what the router sees
    latency: np.ndarray  # (n, k) seconds
    failed: np.ndarray  # (n, k) bool
    in_tokens: np.ndarray
    complexity: np.ndarray
    has_document: np.ndarray
    dropped: int = 0  # requests without an outcome for every model

    def __len__(self) -> int:
        return len(self.item_ids)

    def subset(self, mask: np.ndarray) -> "OutcomeTable":
        idx = np.flatnonzero(mask) if mask.dtype == bool else np.asarray(mask)
        pick = lambda a: a[idx]  # noqa: E731
        return OutcomeTable(
            [self.item_ids[i] for i in idx], pick(self.doc_ids), pick(self.splits), pick(self.tasks),
            self.models, self.tiers, self.is_local, pick(self.X), pick(self.quality), pick(self.cost),
            pick(self.est_cost), pick(self.latency), pick(self.failed), pick(self.in_tokens),
            pick(self.complexity), pick(self.has_document), self.dropped,
        )

    def split(self, name: str) -> "OutcomeTable":
        return self.subset(self.splits == name)

    def index(self, model: str) -> int:
        return self.models.index(model)

    def tier_model(self, tier: str) -> str | None:
        return next((m for m in self.models if self.tiers[m] == tier), None)


def load_outcomes(
    path: str,
    ratings: dict[tuple[str, str], float] | None = None,
    judgements: dict[tuple[str, str], float] | None = None,
) -> OutcomeTable:
    """Reads outcomes.jsonl (one line per request and model, written by
    scripts/collect_outcomes.py). `ratings` maps (item_id, model) to a normalised
    human score H; where present, quality becomes 0.7 H + 0.3 A.

    A is the word-overlap score stored in the file, unless `judgements` (from
    app.evaluation.judge.load_judgements) is given: then A is the judge's
    correctness grade, and every answered request must have one."""
    rows: dict[str, dict] = {}
    models: list[str] = []
    meta: dict[str, dict] = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            r = json.loads(line)
            if r["status"] == "abstained":
                # The model was never called (context window, privacy): not a failure of
                # the model, so no outcome. The request becomes incomplete and is dropped.
                rows.setdefault(r["item_id"], {})
                continue
            rows.setdefault(r["item_id"], {})[r["model"]] = r
            if r["model"] not in meta:
                models.append(r["model"])
                meta[r["model"]] = {"tier": r["tier"], "is_local": r["is_local"]}
    complete = [i for i, by_model in rows.items() if all(m in by_model for m in models)]
    if judgements is not None:
        missing = [(i, m) for i in complete for m in models
                   if rows[i][m]["status"] == "ok" and (i, m) not in judgements]
        if missing:
            raise ValueError(
                f"{len(missing)} answered requests have no judge grade (e.g. {missing[0]}); "
                "run scripts/judge_outcomes.py until it reports nothing left to grade"
            )
    n, k = len(complete), len(models)
    first = [rows[i][models[0]] for i in complete]
    quality, cost, est_cost = np.zeros((n, k)), np.zeros((n, k)), np.zeros((n, k))
    latency, failed = np.zeros((n, k)), np.zeros((n, k), dtype=bool)
    for a, item in enumerate(complete):
        for b, model in enumerate(models):
            r = rows[item][model]
            q = float(r.get("quality") or 0.0)
            if judgements is not None and r["status"] == "ok":
                q = judgements[(item, model)]
            human = (ratings or {}).get((item, model))
            if human is not None:
                q = 0.7 * human + 0.3 * q
            quality[a, b] = q
            cost[a, b] = r["cost_usd"]
            est_cost[a, b] = r.get("est_cost_usd", r["cost_usd"])
            latency[a, b] = r["latency_ms"] / 1000
            failed[a, b] = r["status"] != "ok"
    return OutcomeTable(
        item_ids=complete,
        doc_ids=np.array([r["doc_id"] for r in first]),
        splits=np.array([r["split"] for r in first]),
        tasks=np.array([r["task"] for r in first]),
        models=models,
        tiers={m: meta[m]["tier"] for m in models},
        is_local={m: meta[m]["is_local"] for m in models},
        X=np.array([r["features"] for r in first], dtype=float),
        quality=quality, cost=cost, est_cost=est_cost, latency=latency, failed=failed,
        in_tokens=np.array([r["info"]["in_tokens"] for r in first]),
        complexity=np.array([r["info"]["complexity"] for r in first]),
        has_document=np.array([r["info"]["has_document"] for r in first], dtype=bool),
        dropped=len(rows) - n,
    )


# ------------------------------------------------------------------- rewards


def reward_matrix(t: OutcomeTable, cfg: PolicyConfig) -> np.ndarray:
    w = cfg.weights
    r = (
        w.quality * t.quality
        + w.cost * (1 - np.minimum(t.cost / cfg.c_ref_usd, 1))
        + w.latency * (1 - np.minimum(t.latency / cfg.l_ref_s, 1))
    )
    return np.where(t.failed, FAILURE_REWARD, r)


def learner_targets(t: OutcomeTable, cfg: PolicyConfig) -> np.ndarray:
    """What each arm regresses on (see routing.state.learner_target)."""
    base = t.quality if cfg.reward_mode == "split" else reward_matrix(t, cfg)
    return np.where(t.failed, FAILURE_REWARD, base)


def _take(matrix: np.ndarray, choices: np.ndarray) -> np.ndarray:
    return matrix[np.arange(len(choices)), choices]


def summarise(t: OutcomeTable, choices: np.ndarray, cfg: PolicyConfig) -> dict:
    R = reward_matrix(t, cfg)
    q = np.where(_take(t.failed, choices), 0.0, _take(t.quality, choices))
    lat = _take(t.latency, choices)
    local = np.array([t.is_local[t.models[c]] for c in choices])
    return {
        "n": len(choices),
        "quality": float(q.mean()),
        "cost_usd": float(_take(t.cost, choices).mean()),
        "latency_p50_s": float(np.percentile(lat, 50)),
        "latency_p95_s": float(np.percentile(lat, 95)),
        "reward": float(_take(R, choices).mean()),
        "regret": float((R.max(axis=1) - _take(R, choices)).mean()),
        "failure_rate": float(_take(t.failed, choices).mean()),
        "local_share": float(local.mean()),
        "share": {m: float((choices == i).mean()) for i, m in enumerate(t.models)},
    }


# ---------------------------------------------------------------- statistics


def cluster_bootstrap(values: np.ndarray, clusters: np.ndarray, n_boot: int = 2000, seed: int = 0) -> tuple[float, float, float]:
    """Mean with a 95% interval, resampling whole clusters (documents) with replacement."""
    rng = np.random.default_rng(seed)
    labels = np.unique(clusters)
    sums = np.array([values[clusters == c].sum() for c in labels])
    counts = np.array([(clusters == c).sum() for c in labels])
    draws = rng.integers(0, len(labels), size=(n_boot, len(labels)))
    means = sums[draws].sum(axis=1) / counts[draws].sum(axis=1)
    lo, hi = np.percentile(means, [2.5, 97.5])
    return float(values.mean()), float(lo), float(hi)


def compare_to_baseline(t: OutcomeTable, choices: np.ndarray, baseline: str, n_boot: int = 2000, seed: int = 0) -> dict:
    """Paired comparison with a fixed model on the same requests: the quality
    difference with its clustered CI, and the relative API-cost saving."""
    b = t.index(baseline)
    q_policy = np.where(_take(t.failed, choices), 0.0, _take(t.quality, choices))
    q_base = np.where(t.failed[:, b], 0.0, t.quality[:, b])
    diff, lo, hi = cluster_bootstrap(q_policy - q_base, t.doc_ids, n_boot, seed)
    c_policy, c_base = _take(t.cost, choices), t.cost[:, b]

    rng = np.random.default_rng(seed + 1)
    labels = np.unique(t.doc_ids)
    masks = [t.doc_ids == c for c in labels]
    sp = np.array([c_policy[m].sum() for m in masks])
    sb = np.array([c_base[m].sum() for m in masks])
    draws = rng.integers(0, len(labels), size=(n_boot, len(labels)))
    base_tot = sb[draws].sum(axis=1)
    savings = 1 - sp[draws].sum(axis=1) / np.where(base_tot > 0, base_tot, np.nan)
    saving = 1 - c_policy.sum() / c_base.sum() if c_base.sum() > 0 else float("nan")
    s_lo, s_hi = np.nanpercentile(savings, [2.5, 97.5]) if c_base.sum() > 0 else (float("nan"), float("nan"))
    return {
        "baseline": baseline,
        "quality_diff": diff, "quality_diff_ci": [lo, hi],
        "cost_saving": float(saving), "cost_saving_ci": [float(s_lo), float(s_hi)],
    }


def ips_value(rewards: np.ndarray, propensities: np.ndarray, logged: np.ndarray, target: np.ndarray) -> dict:
    """Inverse-propensity estimate of how a DIFFERENT policy would have done on logs
    collected by a randomised policy. `snips` is the self-normalised variant, which
    has lower variance. Valid only if every logged propensity is positive."""
    match = (logged == target).astype(float)
    w = match / propensities
    return {
        "ips": float((w * rewards).mean()),
        "snips": float((w * rewards).sum() / w.sum()) if w.sum() > 0 else float("nan"),
        "effective_sample_size": float(w.sum() ** 2 / (w**2).sum()) if w.sum() > 0 else 0.0,
    }


# ------------------------------------------------------------ static policies


def _candidates(t: OutcomeTable, i: int, latency_s: np.ndarray) -> list[Candidate]:
    return [
        Candidate(m, t.tiers[m], t.is_local[m], float(t.est_cost[i, a]), float(latency_s[a]))
        for a, m in enumerate(t.models)
    ]


def _info(t: OutcomeTable, i: int) -> RequestInfo:
    return RequestInfo(str(t.tasks[i]), int(t.in_tokens[i]), float(t.complexity[i]), bool(t.has_document[i]))


def mean_latency(t: OutcomeTable) -> np.ndarray:
    ok = np.where(t.failed, np.nan, t.latency)
    return np.nan_to_num(np.nanmean(ok, axis=0), nan=float(np.nanmean(t.latency)))


def choose_fixed(t: OutcomeTable, model: str) -> np.ndarray:
    return np.full(len(t), t.index(model))


def choose_oracle(t: OutcomeTable, cfg: PolicyConfig) -> np.ndarray:
    return reward_matrix(t, cfg).argmax(axis=1)


def choose_rules(t: OutcomeTable, latency_s: np.ndarray) -> np.ndarray:
    rules = RulesPolicy()
    return np.array([t.index(rules.select(_info(t, i), _candidates(t, i, latency_s)).arm) for i in range(len(t))])


def fit_arms(train: OutcomeTable, cfg: PolicyConfig, feature_version: str = "default") -> ArmSet:
    """Frozen supervised router: one ridge regressor per model on full-information data."""
    arms = ArmSet(train.X.shape[1], cfg.ridge_lambda, feature_version)
    targets = learner_targets(train, cfg)
    for a, model in enumerate(train.models):
        arm = arms.arm(model)
        for i in range(len(train)):
            arm.update(train.X[i], float(targets[i, a]))
    return arms


def choose_frozen(t: OutcomeTable, arms: ArmSet, cfg: PolicyConfig, latency_s: np.ndarray) -> np.ndarray:
    policy = FrozenPolicy()
    return np.array(
        [t.index(policy.select(t.X[i], _candidates(t, i, latency_s), arms, cfg).arm) for i in range(len(t))]
    )


def choose_knn(t: OutcomeTable, train: OutcomeTable, cfg: PolicyConfig, k: int = 10) -> np.ndarray:
    """kNN router: copy what earned the highest reward on the k most similar training requests."""
    R = reward_matrix(train, cfg)
    k = min(k, len(train))
    d2 = ((t.X[:, None, :] - train.X[None, :, :]) ** 2).sum(axis=2)
    nearest = np.argpartition(d2, k - 1, axis=1)[:, :k]
    return R[nearest].mean(axis=1).argmax(axis=1)


def random_at_matched_cost(t: OutcomeTable, target_cost: float, cfg: PolicyConfig) -> dict:
    """Expected result of flipping a coin between the cheapest and the most
    expensive model so that the average cost equals `target_cost`. A learned router
    that cannot beat this is not using the content of the request."""
    mean_cost = t.cost.mean(axis=0)
    lo, hi = int(mean_cost.argmin()), int(mean_cost.argmax())
    span = mean_cost[hi] - mean_cost[lo]
    p = float(np.clip((target_cost - mean_cost[lo]) / span, 0, 1)) if span > 0 else 0.0
    R = reward_matrix(t, cfg)
    q = np.where(t.failed, 0.0, t.quality).mean(axis=0)
    return {
        "mix": {t.models[lo]: 1 - p, t.models[hi]: p},
        "quality": float((1 - p) * q[lo] + p * q[hi]),
        "cost_usd": float((1 - p) * mean_cost[lo] + p * mean_cost[hi]),
        "reward": float((1 - p) * R[:, lo].mean() + p * R[:, hi].mean()),
    }


# -------------------------------------------------------------- stream replay


@dataclass
class Drift:
    """A controlled change that starts part-way through the stream."""

    kind: str  # "latency" (endpoint gets slower) | "quality" (silent quality drop)
    model: str
    factor: float
    start_frac: float = 0.5


def make_stream(t: OutcomeTable, order: str = "shuffle", epochs: int = 1, seed: int = 0) -> np.ndarray:
    """Row order for a replay. "task_shift" puts document questions first and
    summaries/explanations last, which is the controlled task change of RQ2."""
    rng = np.random.default_rng(seed)
    parts = []
    for _ in range(epochs):
        idx = rng.permutation(len(t))
        if order == "task_shift":
            late = np.isin(t.tasks[idx], ["summary", "explain"])
            idx = np.concatenate([idx[~late], idx[late]])
        parts.append(idx)
    return np.concatenate(parts)


@dataclass
class Replay:
    choices: np.ndarray
    rewards: np.ndarray
    oracle: np.ndarray
    propensities: np.ndarray
    quality: np.ndarray
    cost: np.ndarray
    rows: np.ndarray
    versions: int = 0
    info: dict = field(default_factory=dict)

    @property
    def regret(self) -> np.ndarray:
        return np.cumsum(self.oracle - self.rewards)

    def window_mean(self, lo: float, hi: float) -> float:
        a, b = int(lo * len(self.rewards)), int(hi * len(self.rewards))
        return float(self.rewards[a:b].mean()) if b > a else float("nan")


def replay(
    t: OutcomeTable,
    stream: np.ndarray,
    policy: str,
    cfg: PolicyConfig,
    arms: ArmSet | None = None,
    latency0: np.ndarray | None = None,
    drift: Drift | None = None,
    seed: int = 0,
) -> Replay:
    """Runs one policy over the stream. Learning policies ("bandit", "linucb") see
    only the outcome of the arm they chose and update in batches; "frozen" and
    "rules" never update. Every policy's latency estimate is an EWMA of the
    latencies it has itself observed, as in the live gateway."""
    rng = np.random.default_rng(seed)
    quality, latency, failed = t.quality.copy(), t.latency.copy(), t.failed
    n = len(stream)
    start = int((drift.start_frac if drift else 1.0) * n)
    lat_est = (latency0 if latency0 is not None else mean_latency(t)).copy()
    arms = arms.copy() if arms is not None else ArmSet(t.X.shape[1], cfg.ridge_lambda)
    learns = policy in ("bandit", "linucb")
    gamma = cfg.linucb_gamma if policy == "linucb" else 1.0
    rules, frozen, eps, ucb = RulesPolicy(), FrozenPolicy(), EpsilonGreedyPolicy(), LinUCBPolicy()
    w = cfg.weights

    out = Replay(*(np.zeros(n) for _ in range(6)), rows=stream.copy())
    out.choices = np.zeros(n, dtype=int)
    pending: list[tuple[np.ndarray, int, float]] = []
    for step, i in enumerate(stream):
        q_row, l_row = quality[i].copy(), latency[i].copy()
        if drift is not None and step >= start:
            a = t.index(drift.model)
            if drift.kind == "latency":
                l_row[a] *= drift.factor
            else:
                q_row[a] *= drift.factor
        r_row = (
            w.quality * q_row
            + w.cost * (1 - np.minimum(t.cost[i] / cfg.c_ref_usd, 1))
            + w.latency * (1 - np.minimum(l_row / cfg.l_ref_s, 1))
        )
        r_row = np.where(failed[i], FAILURE_REWARD, r_row)

        cands, x = _candidates(t, i, lat_est), t.X[i]
        if policy == "rules":
            d = rules.select(_info(t, i), cands)
        elif policy == "frozen":
            d = frozen.select(x, cands, arms, cfg)
        elif policy == "linucb":
            d = ucb.select(x, cands, arms, cfg)
        else:
            d = eps.select(x, cands, arms, cfg, rng)
        a = t.index(d.arm)

        out.choices[step], out.propensities[step] = a, d.propensity
        out.rewards[step], out.oracle[step] = r_row[a], r_row.max()
        out.quality[step] = 0.0 if failed[i, a] else q_row[a]
        out.cost[step] = t.cost[i, a]
        if not failed[i, a]:
            lat_est[a] = (1 - LATENCY_EWMA_ALPHA) * lat_est[a] + LATENCY_EWMA_ALPHA * l_row[a]
        if learns:
            target = FAILURE_REWARD if failed[i, a] else (q_row[a] if cfg.reward_mode == "split" else r_row[a])
            pending.append((x, a, float(target)))
            if len(pending) >= cfg.update_batch_size:
                for px, pa, py in pending:
                    arms.arm(t.models[pa]).update(px, py, gamma)
                arms.n_scored += len(pending)
                pending.clear()
                out.versions += 1
    return out
