"""SYNTHETIC outcome tables for exercising the evaluation code without any model.

Nothing produced here is a result. The numbers come from a made-up generative
story (a latent difficulty per request, three models with different strengths),
chosen so that routing is learnable. Use it to check that the scripts run and
that the statistics behave; never report it.
"""

from __future__ import annotations

import json

import numpy as np

from ..core.analysis import TASKS
from ..core.features import FeatureExtractor
from ..core.policy_config import PolicyConfig, RewardWeights
from .analysis import OutcomeTable, load_outcomes

MODELS = [
    # name, tier, is_local, price_in, price_out, latency mean (s), skill, sensitivity to difficulty
    ("sim-local", "local", True, 0.0, 0.0, 1.5, 0.92, 1.20),
    ("sim-cheap", "cheap", False, 0.10, 0.50, 2.0, 0.90, 0.80),
    ("sim-strong", "strong", False, 4.00, 20.00, 6.0, 0.88, 0.10),
]

# Reward settings calibrated to the synthetic prices above. With the default
# C_ref = $0.002 a request on the strong model (about $0.01) always scores zero on
# the cost term, the strong model is never reward-optimal, and every router
# collapses to the cheap model. C_ref must be set near the typical cost of the
# most expensive model, from pilot data, before any experiment is run.
# The model skills are chosen so that the reward-optimal model changes with
# difficulty (local for the easiest requests, strong for the hardest); with
# flatter skill curves the gap between the oracle and the best single model
# shrinks to almost nothing, and no router can show a benefit.
SYNTHETIC_CFG = PolicyConfig(weights=RewardWeights(quality=0.7, cost=0.2, latency=0.1), c_ref_usd=0.01)


def synthetic_rows(n_docs: int = 200, per_doc: int = 3, seed: int = 0) -> list[dict]:
    rng = np.random.default_rng(seed)
    fx = FeatureExtractor()
    docs = rng.permutation(n_docs)
    split_of = {d: ("train" if r < 0.6 * n_docs else "validation" if r < 0.8 * n_docs else "test")
                for r, d in enumerate(docs)}
    rows = []
    for doc in range(n_docs):
        doc_shift = rng.normal(scale=0.08)  # questions on one paper share difficulty
        for q in range(per_doc):
            difficulty = float(np.clip(rng.uniform() + doc_shift, 0, 1))
            task = str(rng.choice(TASKS + ["doc_qa"]))
            in_tokens = int(np.clip(rng.lognormal(6.2 + 1.2 * difficulty, 0.25), 80, 12000))
            complexity = float(np.clip(0.15 + 0.6 * difficulty + rng.normal(scale=0.05), 0, 1))
            est_out = 250
            x = fx.extract(prompt="", in_tokens=in_tokens, est_out_tokens=est_out, has_document=task != "explain",
                           complexity=complexity, task=task, local_load=0.0)
            for name, tier, is_local, p_in, p_out, lat, skill, slope in MODELS:
                quality = float(np.clip(skill - slope * difficulty + rng.normal(scale=0.06), 0, 1))
                out_tokens = int(rng.normal(260, 40))
                failed = bool(rng.random() < (0.005 if is_local else 0.002))
                rows.append({
                    "synthetic": True,
                    "item_id": f"sim-{doc:04d}-{q}", "doc_id": f"simdoc-{doc:04d}", "split": split_of[doc],
                    "task": task, "model": name, "tier": tier, "is_local": is_local,
                    "status": "failed" if failed else "ok", "quality": 0.0 if failed else quality,
                    "cost_usd": (in_tokens * p_in + out_tokens * p_out) / 1e6,
                    "est_cost_usd": (in_tokens * p_in + est_out * p_out) / 1e6,
                    "latency_ms": float(max(rng.normal(lat, lat * 0.2), 0.2) * 1000 * (1 + in_tokens / 20000)),
                    "in_tokens": in_tokens, "out_tokens": out_tokens,
                    "features": [float(v) for v in x],
                    "info": {"in_tokens": in_tokens, "complexity": complexity, "has_document": task != "explain"},
                })
    return rows


def write_synthetic(path: str, **kwargs) -> int:
    rows = synthetic_rows(**kwargs)
    with open(path, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")
    return len(rows)


def synthetic_table(**kwargs) -> OutcomeTable:
    import os
    import tempfile

    fd, path = tempfile.mkstemp(suffix=".jsonl")
    os.close(fd)
    try:
        write_synthetic(path, **kwargs)
        return load_outcomes(path)
    finally:
        os.remove(path)
