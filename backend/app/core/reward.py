"""Reward definition from the proposal (section 5c).

Q = 0.7 H + 0.3 A when both a human rating H and an automatic score A exist;
otherwise whichever one exists. With neither, the quality-dependent update is deferred.

R = w_q Q + w_c (1 - min(C / C_ref, 1)) + w_l (1 - min(L / L_ref, 1))

Failed, empty, timed-out or truncated attempts receive R = -1.
A privacy rejection is not a model failure and gets no reward at all.
"""

from .policy_config import PolicyConfig

FAILURE_REWARD = -1.0
HUMAN_WEIGHT, AUTO_WEIGHT = 0.7, 0.3


def human_score(correctness: int, relevance: int, completeness: int, usefulness: int) -> float:
    """Normalises the mean of four 1-5 ratings to [0, 1]."""
    mean = (correctness + relevance + completeness + usefulness) / 4
    return (mean - 1) / 4


def combine_quality(human: float | None, auto: float | None) -> tuple[float | None, str | None]:
    if human is not None and auto is not None:
        return HUMAN_WEIGHT * human + AUTO_WEIGHT * auto, "human+auto"
    if human is not None:
        return human, "human"
    if auto is not None:
        return auto, "auto"
    return None, None


def cost_term(cost_usd: float, cfg: PolicyConfig) -> float:
    return 1 - min(cost_usd / cfg.c_ref_usd, 1)


def latency_term(latency_s: float, cfg: PolicyConfig) -> float:
    return 1 - min(latency_s / cfg.l_ref_s, 1)


def reward(quality: float, cost_usd: float, latency_s: float, cfg: PolicyConfig) -> float:
    w = cfg.weights
    return w.quality * quality + w.cost * cost_term(cost_usd, cfg) + w.latency * latency_term(latency_s, cfg)
