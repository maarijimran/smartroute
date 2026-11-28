"""Router v2 query features: what makes a request hard, independent of any model.

The baseline feature vector (core/features.py) cannot see whether retrieval found the
evidence, which is what decides most document questions. These features add that, plus
the kind of answer the question asks for. All of them are cheap and are known before a
model is chosen. Values are raw; the query model stores its own standardisation.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

_STOP = frozenset("""
a an the of to in on for and or but is are was were be been being do does did what which who whom whose
when where why how this that these those it its with by from as at about into than then there their they
them we our you your i he she his her not no yes can could would should will shall may might must has
have had any some all each more most other such only own same so too very just also paper authors author
""".split())
_WORD = re.compile(r"[a-z0-9]+")

_YES_NO = re.compile(r"^\s*(is|are|was|were|do|does|did|can|could|has|have|had|will|would|should|shall|may)\b", re.I)
_NUMERIC = re.compile(r"\b(how (many|much|long|large|big|often)|what (percentage|percent|proportion|number|size|accuracy|score)|by how much)\b", re.I)
_EXTRACTIVE = re.compile(r"^\s*(which|what|who|where|when|name|list)\b", re.I)
_ABSTRACTIVE = re.compile(r"\b(why|how (does|do|did|is|are|can)|explain|describe|discuss|summar\w*|compare|contrast|what (are|is) the (main|key) )\b", re.I)

# Order is fixed: a trained query model refers to features by name.
NAMES = (
    "log_in_tokens", "log_out_tokens", "complexity", "log_history_tokens",
    "has_document", "follow_up", "task_doc_qa", "task_summary", "task_explain",
    "q_yes_no", "q_numeric", "q_extractive", "q_abstractive", "log_question_words",
    "ret_top", "ret_gap", "ret_coverage", "ret_passages", "log_doc_chunks",
)


def _stem(word: str) -> str:
    """Light suffix stripping, so "training" matches "train" and "models" matches "model"."""
    for suffix in ("ing", "ed", "es", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            return word[: -len(suffix)]
    return word


def content_words(text: str) -> set[str]:
    return {_stem(w) for w in _WORD.findall(text.lower()) if w not in _STOP and len(w) > 1}


def question_type(question: str) -> dict[str, float]:
    q = question.strip()
    yes_no = bool(_YES_NO.search(q))
    numeric = bool(_NUMERIC.search(q))
    abstractive = bool(_ABSTRACTIVE.search(q))
    extractive = bool(_EXTRACTIVE.search(q)) and not abstractive and not numeric
    return {
        "q_yes_no": float(yes_no and not abstractive),
        "q_numeric": float(numeric),
        "q_extractive": float(extractive),
        "q_abstractive": float(abstractive),
        "log_question_words": math.log1p(len(q.split())),
    }


@dataclass(frozen=True)
class RetrievalStats:
    """How well retrieval matched the question. All zero when no document is attached."""

    top: float = 0.0  # best BM25 score, squashed to [0, 1)
    gap: float = 0.0  # (best − second best) / best: a clear winner means a findable answer
    coverage: float = 0.0  # share of the question's content words present in the passages sent
    passages: float = 0.0  # passages sent / retrieval top-k
    log_doc_chunks: float = 0.0  # size of the attached documents

    @classmethod
    def from_retrieval(cls, question: str, scores: list[float], passages: list[str], top_k: int) -> "RetrievalStats":
        if not scores:
            return cls()
        ranked = sorted(scores, reverse=True)
        best = ranked[0]
        second = ranked[1] if len(ranked) > 1 else 0.0
        wanted = content_words(question)
        found = content_words(" ".join(passages)) if passages else set()
        return cls(
            top=best / (best + 5.0) if best > 0 else 0.0,
            gap=(best - second) / best if best > 0 else 0.0,
            coverage=len(wanted & found) / len(wanted) if wanted else 0.0,
            passages=min(len(passages) / max(top_k, 1), 1.0),
            log_doc_chunks=math.log1p(len(scores)),
        )


def query_features(
    *,
    question: str,
    in_tokens: int,
    est_out_tokens: int,
    complexity: float,
    history_tokens: int,
    has_document: bool,
    follow_up: bool,
    task: str,
    retrieval: RetrievalStats,
) -> list[float]:
    """The v2 feature vector, in the order of NAMES (embedding dimensions are appended by the caller)."""
    qt = question_type(question)
    values = {
        "log_in_tokens": math.log1p(in_tokens),
        "log_out_tokens": math.log1p(est_out_tokens),
        "complexity": complexity,
        "log_history_tokens": math.log1p(history_tokens),
        "has_document": float(has_document),
        "follow_up": float(follow_up),
        "task_doc_qa": float(task == "doc_qa"),
        "task_summary": float(task == "summary"),
        "task_explain": float(task == "explain"),
        **qt,
        "ret_top": retrieval.top,
        "ret_gap": retrieval.gap,
        "ret_coverage": retrieval.coverage,
        "ret_passages": retrieval.passages,
        "log_doc_chunks": retrieval.log_doc_chunks,
    }
    return [float(values[n]) for n in NAMES]
