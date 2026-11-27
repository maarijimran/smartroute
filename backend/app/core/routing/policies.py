"""Routing policies. Every policy chooses ONLY among candidates that already
passed the eligibility filter, so no policy (and no exploration step) can select
a model that privacy, context, health or budget rules removed.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..policy_config import PolicyConfig
from ..reward import cost_term, latency_term
from .arms import ArmSet

TIER_LOCAL, TIER_CHEAP, TIER_STRONG = "local", "cheap", "strong"

# Thresholds of the explainable rule baseline (research guide 4.1).
RULE_SHORT_TOKENS = 300
RULE_LONG_TOKENS = 6000
RULE_HARD_COMPLEXITY = 0.60


@dataclass(frozen=True)
class Candidate:
    name: str
    tier: str
    is_local: bool
    est_cost_usd: float
    latency_s: float


@dataclass(frozen=True)
class RequestInfo:
    task: str
    in_tokens: int
    complexity: float
    has_document: bool


@dataclass
class Decision:
    arm: str
    propensity: float
    explored: bool
    explanation: str
    scores: dict[str, float] = field(default_factory=dict)
    # Per candidate: how its score was built (shown in the chat's route details).
    breakdown: dict[str, dict] = field(default_factory=dict)


def epsilon(cfg: PolicyConfig, n_scored: int) -> float:
    """Linear decay from eps_start to eps_end over eps_decay_steps scored decisions."""
    frac = min(n_scored / cfg.eps_decay_steps, 1.0)
    return cfg.eps_start + (cfg.eps_end - cfg.eps_start) * frac


def utility_parts(cfg: PolicyConfig, predicted: float, cand: Candidate) -> dict:
    """The utility of one candidate and the weighted terms it is made of.

    split mode: `predicted` is learned quality; cost is calculated from tokens and
    prices and latency is measured, so a price change takes effect without relearning.
    full mode: `predicted` is the learned reward itself."""
    parts = {"tier": cand.tier, "est_cost_usd": cand.est_cost_usd, "latency_s": cand.latency_s}
    if cfg.reward_mode == "full":
        return {**parts, "predicted_reward": predicted, "total": predicted}
    w = cfg.weights
    quality = w.quality * predicted
    cost = w.cost * cost_term(cand.est_cost_usd, cfg)
    speed = w.latency * latency_term(cand.latency_s, cfg)
    return {**parts, "predicted_quality": predicted, "quality": quality, "cost": cost, "speed": speed,
            "total": quality + cost + speed}


def utility(cfg: PolicyConfig, predicted: float, cand: Candidate) -> float:
    return utility_parts(cfg, predicted, cand)["total"]


def _rounded(parts: dict) -> dict:
    return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in parts.items()}


def _argmax(scores: dict[str, float]) -> str:
    # Ties resolve to the first candidate, which keeps decisions reproducible.
    return max(scores, key=lambda name: scores[name])


class RulesPolicy:
    """Explainable fixed rules. Also the rollback policy if learning misbehaves."""

    name = "rules"

    def select(self, info: RequestInfo, candidates: list[Candidate]) -> Decision:
        if info.task == "explain" and info.in_tokens < RULE_SHORT_TOKENS:
            order, why = [TIER_LOCAL, TIER_CHEAP, TIER_STRONG], "short explanation request"
        elif info.complexity >= RULE_HARD_COMPLEXITY or info.in_tokens > RULE_LONG_TOKENS:
            order, why = [TIER_STRONG, TIER_CHEAP, TIER_LOCAL], "high complexity or long input"
        elif info.task == "summary":
            order, why = [TIER_CHEAP, TIER_LOCAL, TIER_STRONG], "summary of moderate length"
        else:
            order, why = [TIER_CHEAP, TIER_STRONG, TIER_LOCAL], "default"
        for tier in order:
            in_tier = [c for c in candidates if c.tier == tier]
            if in_tier:
                pick = min(in_tier, key=lambda c: c.est_cost_usd)
                return Decision(pick.name, 1.0, False, f"rule '{why}' prefers the {tier} tier")
        pick = candidates[0]
        return Decision(pick.name, 1.0, False, "no preferred tier available; first eligible model")


class FixedPolicy:
    """Always one model or one tier. Used for pinned requests and for the
    local-only / cheap-only / strong-only baselines."""

    def __init__(self, model: str | None = None, tier: str | None = None):
        self.model, self.tier = model, tier
        self.name = f"fixed:{model or tier}"

    def select(self, info: RequestInfo, candidates: list[Candidate]) -> Decision | None:
        for c in candidates:
            if (self.model and c.name == self.model) or (self.tier and c.tier == self.tier):
                return Decision(c.name, 1.0, False, f"fixed choice {self.model or self.tier}")
        return None  # caller abstains; a fixed request is never silently rerouted


class RandomPolicy:
    """Uniform random baseline. `probs` (name -> probability) gives the
    'random at matched cost' baseline used in the evaluation."""

    name = "random"

    def __init__(self, probs: dict[str, float] | None = None):
        self.probs = probs

    def select(self, candidates: list[Candidate], rng: np.random.Generator) -> Decision:
        names = [c.name for c in candidates]
        if self.probs:
            p = np.array([self.probs.get(n, 0.0) for n in names], dtype=float)
            p = p / p.sum() if p.sum() > 0 else np.full(len(names), 1 / len(names))
        else:
            p = np.full(len(names), 1 / len(names))
        i = int(rng.choice(len(names), p=p))
        return Decision(names[i], float(p[i]), True, "random baseline")


class FrozenPolicy:
    """Supervised router trained offline on full-information data, never updated."""

    name = "frozen"

    def select(self, x: np.ndarray, candidates: list[Candidate], arms: ArmSet, cfg: PolicyConfig) -> Decision:
        parts = {c.name: utility_parts(cfg, arms.arm(c.name).predict(x), c) for c in candidates}
        scores = {name: p["total"] for name, p in parts.items()}
        best = _argmax(scores)
        return Decision(best, 1.0, False, f"frozen router: highest predicted utility {scores[best]:.3f}", scores,
                        {n: _rounded(p) for n, p in parts.items()})


class EpsilonGreedyPolicy:
    """Eligible epsilon-greedy contextual bandit (the proposal's main method)."""

    name = "bandit"

    def select(
        self,
        x: np.ndarray,
        candidates: list[Candidate],
        arms: ArmSet,
        cfg: PolicyConfig,
        rng: np.random.Generator,
    ) -> Decision:
        parts = {c.name: utility_parts(cfg, arms.arm(c.name).predict(x), c) for c in candidates}
        scores = {name: p["total"] for name, p in parts.items()}
        best = _argmax(scores)
        k = len(candidates)
        eps = epsilon(cfg, arms.n_scored) if k > 1 else 0.0
        explored = bool(rng.random() < eps)
        arm = candidates[int(rng.integers(k))].name if explored else best
        # Logged propensity is the true probability of the action that was taken:
        # the greedy arm can also be drawn by the uniform exploration step.
        propensity = (1 - eps) + eps / k if arm == best else eps / k
        how = f"explored (epsilon={eps:.3f})" if explored else f"greedy (epsilon={eps:.3f})"
        return Decision(arm, float(propensity), explored, f"bandit {how}; utility {scores[arm]:.3f}", scores,
                        {n: _rounded(p) for n, p in parts.items()})


class LinUCBPolicy:
    """LinUCB with an uncertainty bonus and a budget pacer (stretch algorithm).

    Deterministic given the state, so the logged propensity is 1 and its logs are
    not suitable for inverse-propensity evaluation of other policies."""

    name = "linucb"

    def select(
        self,
        x: np.ndarray,
        candidates: list[Candidate],
        arms: ArmSet,
        cfg: PolicyConfig,
        pacer_lambda: float = 0.0,
    ) -> Decision:
        scores, breakdown = {}, {}
        for c in candidates:
            arm = arms.arm(c.name)
            bonus = cfg.linucb_alpha * arm.uncertainty(x)
            penalty = pacer_lambda * min(c.est_cost_usd / cfg.c_ref_usd, 1.0)
            parts = utility_parts(cfg, arm.predict(x), c)
            scores[c.name] = parts["total"] + bonus - penalty
            breakdown[c.name] = _rounded({**parts, "bonus": bonus, "pacer": -penalty, "total": scores[c.name]})
        best = _argmax(scores)
        return Decision(
            best, 1.0, False, f"LinUCB optimistic score {scores[best]:.3f} (pacer {pacer_lambda:.2f})", scores,
            breakdown,
        )


def pacer_lambda(spent_usd: float, budget_usd: float | None, month_fraction: float) -> float:
    """Budget pacer: 0 while spending is on or under a linear pace through the
    month, rising towards 1 as spending runs ahead of that pace."""
    if not budget_usd or budget_usd <= 0:
        return 0.0
    expected = budget_usd * max(month_fraction, 0.05)
    overrun = spent_usd / expected - 1.0
    return float(min(max(overrun, 0.0), 1.0))
