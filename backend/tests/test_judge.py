"""Correctness judge: prompt construction, parsing and how grades enter the outcome table."""

import json

import pytest

from app.evaluation import analysis as an
from app.evaluation.judge import JUDGE_VERSION, build_messages, load_judgements, parse


def test_prompt_is_blind_and_carries_the_reference():
    msgs = build_messages("doc_qa", "Which dataset?", ["SQuAD", "SQuAD v1.1"], "They use SQuAD.", False)
    user = msgs[1]["content"]
    assert "Alternative 1: SQuAD" in user and "Alternative 2: SQuAD v1.1" in user
    assert "They use SQuAD." in user
    # The judge never learns which model wrote the answer.
    assert "model" not in user.lower().replace("models", "")


def test_unanswerable_and_summary_guides():
    unans = build_messages("doc_qa", "Q?", [], "Not stated in the paper.", True)[1]["content"]
    assert "does NOT contain the answer" in unans
    summ = build_messages("summary", "Summarise.", ["The abstract."], "A summary.", False)[1]["content"]
    assert "abstract" in summ


def test_checklist_decides_the_grade():
    def reply(covered, contradicts=False, score=5):
        points = [{"point": f"p{i}", "covered": c} for i, c in enumerate(covered)]
        return json.dumps({"key_points": points, "contradicts": contradicts, "reason": "r", "score": score})

    assert parse(reply(["yes", "yes"])).score == 5
    assert parse(reply(["yes", "yes", "yes", "partly"])).score == 4
    # The judge said 5 although half the points are missing: the checklist wins.
    j = parse(reply(["yes", "no"], score=5))
    assert j.score == 3 and j.judge_score == 5
    assert parse(reply(["no"])).score == 2  # honest "not found": no contradiction
    assert parse(reply(["yes", "yes"], contradicts=True)).score == 1


def test_parse_validates_the_grade():
    assert parse('{"reason": "matches", "score": 5}').normalised == 1.0
    assert parse('{"reason": "partly", "score": 3}').normalised == 0.5
    with pytest.raises(ValueError):
        parse('{"reason": "x", "score": 9}')


def _write(path, rows):
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def _outcome(item, model, quality, status="ok"):
    return {"item_id": item, "doc_id": "d", "split": "train", "category": "doc_qa", "task": "doc_qa",
            "model": model, "tier": "local", "is_local": True, "status": status, "quality": quality,
            "cost_usd": 0.0, "latency_ms": 1000.0, "features": [1.0, 0.0],
            "info": {"in_tokens": 10, "complexity": 0.1, "has_document": True}}


def test_judge_grade_replaces_word_overlap(tmp_path):
    outcomes, judgements = tmp_path / "o.jsonl", tmp_path / "j.jsonl"
    _write(outcomes, [_outcome("i1", "a", 0.1), _outcome("i1", "b", 0.9)])
    _write(judgements, [
        {"item_id": "i1", "model": "a", "judge_model": "j", "judge_version": JUDGE_VERSION, "score": 5},
        {"item_id": "i1", "model": "b", "judge_model": "j", "judge_version": JUDGE_VERSION, "score": 1},
        {"item_id": "i1", "model": "b", "judge_model": "j", "judge_version": "old", "score": 5},  # ignored
    ])
    word = an.load_outcomes(str(outcomes))
    judged = an.load_outcomes(str(outcomes), judgements=load_judgements(str(judgements)))
    assert word.quality.tolist() == [[0.1, 0.9]]
    assert judged.quality.tolist() == [[1.0, 0.0]]


def test_missing_grade_is_an_error(tmp_path):
    outcomes, judgements = tmp_path / "o.jsonl", tmp_path / "j.jsonl"
    _write(outcomes, [_outcome("i1", "a", 0.1), _outcome("i1", "b", 0.9)])
    _write(judgements, [{"item_id": "i1", "model": "a", "judge_model": "j", "judge_version": JUDGE_VERSION,
                         "score": 4}])
    with pytest.raises(ValueError, match="no judge grade"):
        an.load_outcomes(str(outcomes), judgements=load_judgements(str(judgements)))


def test_failed_answers_need_no_grade(tmp_path):
    outcomes, judgements = tmp_path / "o.jsonl", tmp_path / "j.jsonl"
    _write(outcomes, [_outcome("i1", "a", 0.2), _outcome("i1", "b", 0.0, status="truncated")])
    _write(judgements, [{"item_id": "i1", "model": "a", "judge_model": "j", "judge_version": JUDGE_VERSION,
                         "score": 4}])
    t = an.load_outcomes(str(outcomes), judgements=load_judgements(str(judgements)))
    assert t.quality[0, 0] == 0.75 and t.failed.tolist() == [[False, True]]
