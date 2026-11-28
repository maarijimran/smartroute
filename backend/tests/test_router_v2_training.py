"""Router v2 training on synthetic collection rounds (outcome and judgement files)."""

import json

import numpy as np
import pytest

from app.core.routing import qfeatures
from app.core.routing.irt import sigmoid
from app.evaluation import router_v2_training as T
from app.evaluation.judge import JUDGE_VERSION

NAMES = list(qfeatures.NAMES)
P = len(NAMES)
CX = NAMES.index("complexity")
COV = NAMES.index("ret_coverage")
# Round 1 and round 2 both use the slot "sim-cheap", with different models behind it.
ROUNDS = {
    "r1": {"local-default": ("ollama", "weak-3b", -1.0), "sim-cheap": ("ollama", "mid-9b", 0.3)},
    "r2": {"local-default": ("ollama", "big-20b", 1.2), "sim-cheap": ("ollama", "other-14b", 0.6)},
}


def write_jsonl(path, rows):
    with open(path, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")


@pytest.fixture
def files(tmp_path):
    rng = np.random.default_rng(0)
    items = []
    for i in range(400):
        split = "train" if i < 240 else "validation" if i < 320 else "test"
        kind = ["mc", "free", "yes_no", "free"][i % 4]
        items.append({"item_id": f"it-{i}", "split": split, "task": "chat" if kind == "mc" else "doc_qa",
                      "kind": kind if kind == "mc" else None,
                      "golds": ["B"] if kind == "mc" else (["Yes"] if kind == "yes_no" else ["a long free form answer that needs a judge to grade it"]),
                      "unanswerable": False})
    x_of = {}
    for it in items:
        qf = np.zeros(P)
        qf[CX] = rng.uniform(-1, 1)
        qf[COV] = rng.uniform(0, 1)
        x_of[it["item_id"]] = qf
    runs = []
    for name, slots in ROUNDS.items():
        outcomes, judgements = [], []
        for it in items:
            for slot, (vendor, model_id, level) in slots.items():
                qf = x_of[it["item_id"]]
                p = float(sigmoid(level - 3 * qf[CX] + 2 * (qf[COV] - 0.5)))
                right = rng.random() < p
                kind = T.item_kind(it)
                answer = {"mc": "The answer is B." if right else "The answer is C.",
                          "yes_no": "Yes." if right else "No."}.get(kind, "free text")
                outcomes.append({"item_id": it["item_id"], "model": slot, "vendor": vendor, "model_id": model_id,
                                 "status": "ok", "answer": answer, "qf": qf.tolist(), "features": [0.0] * 11})
                if kind == "free":
                    grade = 5 if right else 2
                    for judge, g in (("judge-a", grade), ("judge-b", grade if rng.random() < 0.8 else 3)):
                        judgements.append({"item_id": it["item_id"], "model": slot, "judge_model": judge,
                                           "judge_version": JUDGE_VERSION, "score": g})
        o, j = tmp_path / f"outcomes_{name}.jsonl", tmp_path / f"judgements_{name}.jsonl"
        write_jsonl(o, outcomes)
        write_jsonl(j, judgements)
        runs.append((str(o), [str(j)]))
    return runs, {it["item_id"]: it for it in items}


def test_rows_use_model_identity_and_the_right_quality_source(files):
    runs, items = files
    rows, stats = T.build_rows(runs, items, embedding_dim=0)
    keys = {r.model_key for r in rows}
    assert keys == {"ollama:weak-3b", "ollama:mid-9b", "ollama:big-20b", "ollama:other-14b"}  # same slot, 2 models
    assert stats.by_source["auto"] > 0 and stats.by_source["judge"] > 0
    assert all(0 <= r.y <= 1 for r in rows)
    assert stats.judge_pairs > 0 and 0.5 < stats.judge_exact_agreement < 1.0


def test_router_v2_beats_the_blind_baseline_on_validation(files):
    runs, items = files
    rows, _ = T.build_rows(runs, items, embedding_dim=0)
    qm, cards, report = T.train(rows, NAMES, ks=(1, 2), l2s=(1e-2,), steps=1500)
    v = report["validation"]
    assert v["router_v2"]["log_loss"] < v["difficulty_blind"]["log_loss"] - 0.02
    assert v["router_v2"]["auc"] > 0.7
    assert set(cards) == set(report["models"]) and len(cards) == 4
    levels = {k: c.theta[-1] for k, c in cards.items()}
    assert levels["ollama:big-20b"] > levels["ollama:mid-9b"] > levels["ollama:weak-3b"]  # order recovered
    assert report["rows"]["train"] > 0 and report["rows"]["validation"] > 0


def test_failures_count_as_zero_and_abstentions_are_left_out(files, tmp_path):
    _, items = files
    rows_in = [
        {"item_id": "it-0", "model": "s", "vendor": "ollama", "model_id": "m", "status": "failed", "qf": [0.0] * P, "features": []},
        {"item_id": "it-1", "model": "s", "vendor": "ollama", "model_id": "m", "status": "abstained", "qf": [0.0] * P, "features": []},
        {"item_id": "it-2", "model": "s", "status": "ok", "qf": [0.0] * P, "features": []},  # server-era row: no identity
    ]
    path = tmp_path / "o.jsonl"
    write_jsonl(path, rows_in)
    rows, stats = T.build_rows([(str(path), [])], items, embedding_dim=0)
    assert [r.y for r in rows] == [0.0] and rows[0].source == "failure"
    assert stats.skipped_abstained == 1 and stats.skipped_no_identity == 1


@pytest.mark.parametrize("item,kind", [
    ({"kind": "mc"}, "mc"),
    ({"task": "summary", "golds": ["abstract"]}, "free"),
    ({"task": "doc_qa", "unanswerable": True, "golds": []}, "unanswerable"),
    ({"task": "doc_qa", "golds": ["Yes", "No"]}, "yes_no"),
    ({"task": "doc_qa", "golds": ["BLEU and ROUGE"]}, "extractive"),
    ({"task": "doc_qa", "golds": ["They fine-tune a pretrained encoder on the labelled corpus and then distil it"]}, "free"),
])
def test_item_kinds(item, kind):
    assert T.item_kind(item) == kind
