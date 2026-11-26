"""Reference-guided correctness judge: a local LLM grades each answer 1-5.

Token F1 and word recall (scoring.py) measure word overlap, so they punish correct
answers that are worded differently or carry extra correct detail. The judge grades
CORRECTNESS against the human reference instead.

Design choices, all to keep the grade about correctness and free of bias:
- The judge is a different model family from every model it grades, so it cannot
  prefer its own answers (self-preference bias).
- It never sees which model wrote an answer, and items are graded in shuffled order.
- Pointwise grading against the QASPER reference answer(s), with a fixed rubric.
- Checklist grading: the judge lists the reference's key points, marks each as covered or
  not, flags contradictions, and only then grades. Detail beyond the reference earns no
  credit and the reference is never overruled (v2 failed on both: LLM judges reward
  confident, detailed answers). Output is constrained to JSON by a schema; temperature 0.
- Length, wording, formatting and citations are explicitly NOT graded.

The 1-5 grade maps to [0, 1] as (grade - 1) / 4 and replaces the automatic score A
in the reward when judgements are supplied (see analysis.load_outcomes).
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import httpx

JUDGE_VERSION = "correctness-v3"  # bump when the prompt or rubric changes
# v2: honest abstention ("not in the excerpts") when an answer exists = 2, confident wrong = 1.
# v3: checklist grading. v2 rewarded detailed, confident answers over short references and once
#     overruled a reference; v3 lists the reference's key points, marks coverage, then grades.
MAX_ANSWER_CHARS = 6000

SYSTEM = """You are a strict grader of answer CORRECTNESS for questions about research papers.
The reference answer was written by human annotators who read the whole paper. It is the ground
truth: never decide that the reference is wrong, irrelevant or incomplete.

Work in three steps, then grade.
1. key_points: list the facts the reference requires (1 to 6 short points). Every named item in the
   reference (each model, dataset, method, author or number) is its own key point: never group
   several names into one point. A yes/no reference gives one point: the yes/no conclusion. For a
   summary, use the abstract's main problem, main method or contribution, and main findings.
2. For each key point, mark whether the candidate states it: "yes", "partly" or "no".
   Paraphrases, synonyms and equivalent numbers count as "yes".
3. contradicts: true if the candidate asserts anything that conflicts with the reference
   (for example "yes" when the reference says "no", or a different dataset, number or method).

Grade:
5 = every key point "yes" and no contradiction.
4 = nearly all key points "yes" (at most one "partly" or one minor point missing), no contradiction.
3 = about half of the key points covered, no contradiction.
2 = few or none covered and no contradiction. This includes an honest "the excerpts do not say".
1 = contradicts the reference, or is off-topic.

Rules:
- Detail beyond the reference earns NO credit, however accurate or specific it sounds. Only the
  reference's key points count.
- Do NOT reward or penalise length, wording, style, formatting or citations like [1].
- Several references are alternatives from different annotators: grade against the one the
  candidate matches best.
- An honest "I could not find it" is never graded below a confident wrong answer."""

TASK_GUIDE = {
    "doc_qa": "Grade whether the candidate answers the question correctly according to the reference.",
    "unanswerable": (
        "The annotators found that the paper does NOT contain the answer. The only key point is: "
        "'the paper does not provide this information'. Grade 5 if the candidate says so; 3 if it hedges "
        "but leans towards a specific answer; 1 if it asserts a specific answer as fact."
    ),
    "summary": (
        "The reference is the paper's abstract (the candidate did not see it). Key points are the "
        "abstract's main problem, main method or contribution, and main findings. A claim that conflicts "
        "with the abstract is a contradiction."
    ),
}
TASK_GUIDE["explain"] = TASK_GUIDE["summary"]

SCHEMA = {
    "type": "object",
    "properties": {
        "key_points": {
            "type": "array",
            "maxItems": 6,
            "items": {
                "type": "object",
                "properties": {
                    "point": {"type": "string"},
                    "covered": {"type": "string", "enum": ["yes", "partly", "no"]},
                },
                "required": ["point", "covered"],
            },
        },
        "contradicts": {"type": "boolean"},
        "reason": {"type": "string", "description": "one sentence"},
        "score": {"type": "integer", "enum": [1, 2, 3, 4, 5]},
    },
    "required": ["key_points", "contradicts", "reason", "score"],
}


def checklist_grade(key_points: list[dict], contradicts: bool) -> int:
    """The official grade, derived from the checklist so it follows the rubric exactly
    (the judge's own final number occasionally does not)."""
    if contradicts:
        return 1
    weight = {"yes": 1.0, "partly": 0.5, "no": 0.0}
    coverage = sum(weight.get(p.get("covered"), 0.0) for p in key_points) / len(key_points)
    if coverage >= 1.0:
        return 5
    if coverage >= 0.75:
        return 4
    if coverage >= 0.4:
        return 3
    return 2


@dataclass
class Judgement:
    score: int  # 1-5: the checklist grade when a checklist was returned
    reason: str
    key_points: list[dict] | None = None  # [{"point", "covered"}], kept for auditing
    contradicts: bool | None = None
    judge_score: int | None = None  # the judge's own holistic grade, for comparison

    @property
    def normalised(self) -> float:
        return (self.score - 1) / 4


def build_messages(task: str, question: str, golds: list[str], answer: str, unanswerable: bool) -> list[dict]:
    kind = "unanswerable" if unanswerable else task if task in TASK_GUIDE else "doc_qa"
    if unanswerable:
        reference = "(The paper does not contain the answer.)"
    elif len(golds) == 1:
        reference = golds[0]
    else:
        reference = "\n".join(f"- Alternative {i}: {g}" for i, g in enumerate(golds, start=1))
    answer = (answer or "").strip()
    if len(answer) > MAX_ANSWER_CHARS:
        answer = answer[:MAX_ANSWER_CHARS] + " [...truncated]"
    user = (
        f"Task: {TASK_GUIDE[kind]}\n\n"
        f"Question:\n{question}\n\n"
        f"Reference answer:\n{reference}\n\n"
        f"Candidate answer:\n{answer or '(empty)'}\n\n"
        'Reply with JSON only: {"key_points": [{"point": "...", "covered": "yes|partly|no"}], '
        '"contradicts": true|false, "reason": "<one sentence>", "score": <1-5>}'
    )
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]


def parse(content: str) -> Judgement:
    data = json.loads(content)
    score = int(data["score"])
    if not 1 <= score <= 5:
        raise ValueError(f"score out of range: {score}")
    points = data.get("key_points")
    points = (
        [{"point": str(p.get("point", ""))[:200], "covered": p.get("covered")} for p in points if isinstance(p, dict)]
        if isinstance(points, list) else []
    )
    contradicts = data.get("contradicts")
    official = checklist_grade(points, bool(contradicts)) if points and isinstance(contradicts, bool) else score
    return Judgement(
        score=official,
        reason=str(data.get("reason", "")).strip()[:500],
        key_points=points or None,
        contradicts=contradicts if isinstance(contradicts, bool) else None,
        judge_score=score,
    )


class OllamaJudge:
    def __init__(self, model: str, base_url: str = "http://127.0.0.1:11434", num_ctx: int = 8192,
                 think: bool | str | None = False, timeout_s: float = 300.0):
        self.model, self.base_url, self.num_ctx, self.think = model, base_url.rstrip("/"), num_ctx, think
        self.client = httpx.Client(timeout=httpx.Timeout(timeout_s, connect=10.0))

    def grade(self, task: str, question: str, golds: list[str], answer: str, unanswerable: bool,
              temperature: float = 0.0, seed: int = 0) -> Judgement:
        """Deterministic by default. A stability check re-grades with another seed and
        temperature > 0; at temperature 0 a re-grade would match by construction."""
        body = {
            "model": self.model,
            "messages": build_messages(task, question, golds, answer, unanswerable),
            "stream": False,
            "format": SCHEMA,
            "options": {"temperature": temperature, "seed": seed, "num_ctx": self.num_ctx, "num_predict": 800},
        }
        if self.think is not None:
            body["think"] = self.think
        last_error: Exception | None = None
        for _ in range(2):  # one retry for a malformed reply
            r = self.client.post(f"{self.base_url}/api/chat", json=body)
            r.raise_for_status()
            try:
                return parse(r.json()["message"]["content"])
            except (ValueError, KeyError, json.JSONDecodeError) as exc:
                last_error = exc
        raise RuntimeError(f"judge returned no valid grade: {last_error}")


def load_judgements(path: str, judge_model: str | None = None) -> dict[tuple[str, str], float]:
    """(item_id, model) -> normalised correctness in [0, 1], for analysis.load_outcomes.
    Only judgements from the current JUDGE_VERSION (and judge_model, if given) count."""
    out: dict[tuple[str, str], float] = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            j = json.loads(line)
            if j.get("judge_version") != JUDGE_VERSION:
                continue
            if judge_model and j.get("judge_model") != judge_model:
                continue
            out[(j["item_id"], j["model"])] = (int(j["score"]) - 1) / 4
    return out
