"""Router v2 training: answers of several models -> query model + model cards.

Rows come from outcome files written by scripts/collect_outcomes.py (one file per
collection round; a round answers every item with up to three tier models) and the judge
grades for each file. Quality, per answer:

- failed, empty, truncated or refused: 0
- multiple choice, numeric, yes/no, unanswerable: scored automatically (exact)
- everything else (free-form paper answers, summaries, explanations, open requests):
  the mean of the judges' correctness grades; answers without a grade are left out

Model identity is "<vendor>:<model_id>", so the same tier slot can hold different models
in different rounds. Settings (number of skills, L2) are chosen on the validation split
against the baselines; the test split is never read here.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import dataclass, field

import numpy as np

from ..core.routing import qfeatures
from ..core.routing.calibration import score_item
from ..core.routing.irt import ModelCard, auc, fit_query_model, sigmoid
from .judge import JUDGE_VERSION

AUTO_KINDS = {"mc", "numeric", "yes_no", "unanswerable"}
SHORT_EXTRACTIVE_WORDS = 6
FAILED = {"failed", "empty", "truncated", "refused", "attempt_failed"}


def item_kind(item: dict) -> str:
    """How an item can be scored. General items carry their kind; QASPER items get one
    from their reference answers."""
    if item.get("kind"):
        return item["kind"]
    if item.get("task") in ("summary", "explain"):
        return "free"
    if item.get("unanswerable"):
        return "unanswerable"
    golds = item.get("golds") or []
    if golds and all(g in ("Yes", "No") for g in golds):
        return "yes_no"
    if golds and all(len(g.split()) <= SHORT_EXTRACTIVE_WORDS for g in golds):
        return "extractive"
    return "free"


@dataclass
class Row:
    item_id: str
    split: str
    model_key: str
    x: list[float]
    y: float
    source: str  # "auto" | "judge" | "failure"


@dataclass
class RowStats:
    rows: int = 0
    skipped_no_identity: int = 0
    skipped_no_grade: int = 0
    skipped_abstained: int = 0
    skipped_features: int = 0
    by_source: dict = field(default_factory=dict)
    judge_pairs: int = 0
    judge_exact_agreement: float | None = None
    judge_correlation: float | None = None


def load_jsonl(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def judge_scores(paths: list[str], judges: list[str] | None) -> dict[tuple[str, str], dict[str, float]]:
    """(item_id, slot) -> {judge_model: normalised grade in [0, 1]} for the current rubric."""
    out: dict[tuple[str, str], dict[str, float]] = {}
    for path in paths:
        for j in load_jsonl(path):
            if j.get("judge_version") != JUDGE_VERSION:
                continue
            if judges and j.get("judge_model") not in judges:
                continue
            out.setdefault((j["item_id"], j["model"]), {})[j["judge_model"]] = (int(j["score"]) - 1) / 4
    return out


def build_rows(
    runs: list[tuple[str, list[str]]],
    items: dict[str, dict],
    embedding_dim: int,
    judges: list[str] | None = None,
) -> tuple[list[Row], RowStats]:
    """runs: [(outcomes file, [judgement files for it])]."""
    rows: list[Row] = []
    stats = RowStats()
    pairs_a, pairs_b = [], []
    for outcomes_path, judgement_paths in runs:
        grades = judge_scores(judgement_paths, judges)
        for r in load_jsonl(outcomes_path):
            item = items.get(r["item_id"])
            if item is None:
                continue
            if r.get("status") == "abstained":
                stats.skipped_abstained += 1
                continue
            if not r.get("vendor") or not r.get("model_id"):
                stats.skipped_no_identity += 1
                continue
            qf, feats = r.get("qf"), r.get("features") or []
            if qf is None or len(qf) != len(qfeatures.NAMES) or (embedding_dim and len(feats) < embedding_dim):
                stats.skipped_features += 1
                continue
            x = list(qf) + (list(feats[-embedding_dim:]) if embedding_dim else [])
            kind = item_kind(item)
            if r.get("status") in FAILED:
                y, source = 0.0, "failure"
            elif kind in AUTO_KINDS:
                y, source = score_item({"kind": kind, "golds": item.get("golds", []),
                                        "unanswerable": item.get("unanswerable", False)}, r.get("answer", "")), "auto"
            else:
                g = grades.get((r["item_id"], r["model"]))
                if not g:
                    stats.skipped_no_grade += 1
                    continue
                y, source = float(np.mean(list(g.values()))), "judge"
                if len(g) >= 2:
                    a, b = sorted(g)[:2]
                    pairs_a.append(g[a])
                    pairs_b.append(g[b])
            rows.append(Row(r["item_id"], item["split"], f"{r['vendor']}:{r['model_id']}", x, float(y), source))
            stats.by_source[source] = stats.by_source.get(source, 0) + 1
    stats.rows = len(rows)
    if pairs_a:
        a, b = np.array(pairs_a), np.array(pairs_b)
        stats.judge_pairs = len(a)
        stats.judge_exact_agreement = float(np.mean(np.isclose(a, b)))
        stats.judge_correlation = float(np.corrcoef(a, b)[0, 1]) if a.std() > 0 and b.std() > 0 else None
    return rows, stats


# ------------------------------------------------------------------- evaluation


def metrics(pred: np.ndarray, y: np.ndarray) -> dict:
    p = np.clip(pred, 1e-6, 1 - 1e-6)
    return {
        "log_loss": float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))),
        "brier": float(np.mean((pred - y) ** 2)),
        "auc": auc(pred, (y >= 0.5).astype(float)),
        "n": int(len(y)),
    }


def _arrays(rows: list[Row]) -> tuple[np.ndarray, list[str], np.ndarray]:
    return np.array([r.x for r in rows], dtype=float), [r.model_key for r in rows], np.array([r.y for r in rows])


def baseline_blind(train: list[Row], val: list[Row]) -> np.ndarray:
    """Each model's average quality, ignoring the request (no difficulty at all)."""
    means = {}
    for r in train:
        means.setdefault(r.model_key, []).append(r.y)
    overall = float(np.mean([r.y for r in train]))
    return np.array([float(np.mean(means[r.model_key])) if r.model_key in means else overall for r in val])


def baseline_ridge(train: list[Row], val: list[Row], lam: float = 1.0) -> np.ndarray:
    """The baseline router's form: one ridge regression per model on the same features."""
    X, models, y = _arrays(train)
    mean, scale = X.mean(axis=0), X.std(axis=0)
    scale[scale < 1e-8] = 1.0
    Z = np.column_stack([(X - mean) / scale, np.ones(len(X))])
    weights = {}
    for m in set(models):
        idx = [i for i, k in enumerate(models) if k == m]
        A = Z[idx].T @ Z[idx] + lam * np.eye(Z.shape[1])
        weights[m] = np.linalg.solve(A, Z[idx].T @ y[idx])
    Xv, mv, _ = _arrays(val)
    Zv = np.column_stack([(Xv - mean) / scale, np.ones(len(Xv))])
    overall = float(y.mean())
    return np.clip(np.array([Zv[i] @ weights[m] if m in weights else overall for i, m in enumerate(mv)]), 0, 1)


def predict_rows(qm, cards: dict[str, ModelCard], rows: list[Row]) -> np.ndarray:
    out = []
    for r in rows:
        card = cards.get(r.model_key) or ModelCard.prior(qm)
        out.append(float(card.predict(qm, np.array(r.x))[0]))
    return np.array(out)


# ------------------------------------------------------------------------ training


def train(
    rows: list[Row],
    names: list[str],
    ks: tuple[int, ...] = (1, 2, 3),
    l2s: tuple[float, ...] = (1e-3, 1e-2, 1e-1),
    steps: int = 3000,
    seed: int = 0,
) -> tuple[object, dict[str, ModelCard], dict]:
    """Chooses (k, l2) by validation log loss, reports the baselines on the same
    validation rows, then refits the chosen setting on train + validation."""
    tr = [r for r in rows if r.split == "train"]
    va = [r for r in rows if r.split == "validation"]
    if not tr or not va:
        raise ValueError("Training needs rows in both the train and the validation split.")
    Xt, mt, yt = _arrays(tr)
    yv = np.array([r.y for r in va])
    grid = []
    for k in ks:
        for l2 in l2s:
            qm, cards = fit_query_model(Xt, mt, yt, names, k=k, l2=l2, steps=steps, seed=seed)
            grid.append({"k": k, "l2": l2, **metrics(predict_rows(qm, cards, va), yv)})
    best = min(grid, key=lambda g: g["log_loss"])
    report = {
        "validation": {
            "router_v2": {key: best[key] for key in ("log_loss", "brier", "auc", "n")},
            "baseline_per_model_ridge": metrics(baseline_ridge(tr, va), yv),
            "difficulty_blind": metrics(baseline_blind(tr, va), yv),
        },
        "grid": grid,
        "chosen": {"k": best["k"], "l2": best["l2"]},
        "rows": {"train": len(tr), "validation": len(va)},
        "models": sorted({r.model_key for r in rows}),
    }
    both = tr + va
    Xb, mb, yb = _arrays(both)
    qm, cards = fit_query_model(Xb, mb, yb, names, k=best["k"], l2=best["l2"], steps=steps, seed=seed)
    return qm, cards, report


def version_for(report: dict, names: list[str]) -> str:
    digest = hashlib.sha256(json.dumps([report["chosen"], report["rows"], report["models"], names],
                                       sort_keys=True).encode()).hexdigest()[:8]
    return f"v2-{dt.date.today().isoformat()}-{digest}"
