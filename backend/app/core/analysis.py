"""Cheap, local, pre-decision analysis of a request: task type and complexity.

Both are heuristics that cost microseconds. `estimate_complexity` is the default
backend for the proposal's "estimated complexity" feature; SETUP.md describes how
to swap in NVIDIA's prompt-task-and-complexity classifier on the GPU server.
"""

import math
import re

TASKS = ["doc_qa", "summary", "explain"]  # one-hot order used by the feature vector
TASK_CHAT = "chat"

_SUMMARY = re.compile(r"\b(summar(?:y|ise|ize|ies)|tl;?dr|overview of|key points|main points|abstract of)\b", re.I)
_EXPLAIN = re.compile(r"\b(explain|define|definition|what (?:is|are|does)|meaning of|in simple terms|describe)\b", re.I)
_HARD = re.compile(
    r"\b(prove|derive|derivation|compare|contrast|analy[sz]e|evaluate|critique|justify|trade-?offs?|"
    r"why does|why is|step by step|multi-?step|implications?|limitations?|robust|synthesi[sz]e)\b",
    re.I,
)
_EASY = re.compile(r"\b(define|definition|what is|list|name|who|when|which year|how many)\b", re.I)


def explicit_task(prompt: str) -> str | None:
    """The task the message itself asks for, if it names one."""
    if _SUMMARY.search(prompt):
        return "summary"
    if _EXPLAIN.search(prompt):
        return "explain"
    return None


def classify_task(prompt: str, has_document: bool) -> str:
    if _SUMMARY.search(prompt):
        return "summary"
    if has_document:
        return "doc_qa"
    if _EXPLAIN.search(prompt):
        return "explain"
    return TASK_CHAT


def estimate_complexity(prompt: str, in_tokens: int) -> float:
    """Returns a score in [0, 1]; higher means the request likely needs a stronger model."""
    score = 0.25
    score += 0.12 * min(len(_HARD.findall(prompt)), 3)
    score -= 0.10 * min(len(_EASY.findall(prompt)), 2)
    score += 0.08 * max(prompt.count("?") - 1, 0)  # several questions in one prompt
    score += 0.10 * min(math.log1p(len(prompt.split())) / math.log1p(120), 1.0)
    score += 0.10 * min(math.log1p(in_tokens) / math.log1p(8000), 1.0)
    return float(min(max(score, 0.0), 1.0))


def question_text(messages: list[dict]) -> str:
    """The latest user turn."""
    for m in reversed(messages):
        if m.get("role") == "user":
            return m.get("content", "")
    return ""
