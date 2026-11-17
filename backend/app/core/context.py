"""Conversation context: how earlier turns shape the current request.

Four techniques, chosen because none of them adds a model call to the request
path (the summary is written in the background, after an answer, on the local
model):

1. Follow-up detection. A lexical test decides whether the new message leans on
   earlier turns ("why?", "make it shorter", "what about the second method?").
2. History-aware retrieval and task resolution. A follow-up borrows search terms
   from the previous question (and, weakly, the previous answer), keeps the
   passages the previous answer used in contention, and inherits the previous
   task when it names none of its own.
3. A token-budgeted history window. Short conversations are sent verbatim. Long
   ones send the most recent exchanges verbatim and replace older ones with a
   rolling summary; until a summary exists, the older exchanges most relevant
   to the new message are kept instead (extractive fallback).
4. A rolling summary written by the LOCAL model in the background after an
   answer, so it is ready for the next turn and never delays the current one.
   Each new summary extends the previous one rather than rereading the whole
   conversation.

An LLM that rewrites every follow-up into a standalone question would resolve
references better, but it puts a model call (hundreds of milliseconds to
seconds on an 8B local model) in front of every follow-up. The lexical approach
costs microseconds; its accuracy should be measured, and query rewriting added
only if the measurement shows it is needed.

Privacy: turns that are summarised or dropped are still assessed by the privacy
gate on every request (labels propagate to derived content), and the summary
itself is written only by a local model.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from functools import partial

from ..db import session_scope
from ..models import Attempt
from .cache import ResponseCache
from .documents import bm25_scores, tokenize
from .providers import ChatRequest, ModelSpec, build_provider
from .providers.base import FINISH_REFUSAL
from .tokens import count_messages, count_tokens

log = logging.getLogger(__name__)

RECENT_SHARE = 0.6  # share of the history budget for verbatim recent exchanges
PREVIOUS_QUESTION_WEIGHT = 0.6
PREVIOUS_ANSWER_WEIGHT = 0.3
PREVIOUS_ANSWER_TERMS = 10
SHORT_FOLLOW_UP_WORDS = 10
MEMORY_HEADER = "Summary of the earlier conversation (written on this server):"

# Words that carry no topic of their own, so a message made only of these (plus
# words already used in the last exchange) must be referring back.
GENERIC = frozenset(
    """why how what which who whom whose when where more less example examples explain explained
    elaborate mean means meaning detail details detailed shorter simpler longer short simple long
    again else sure ok okay please thanks thank yes no does do did can could would should will
    give tell me show about so then also further continue go on make rewrite rephrase summarise
    summarize briefly simply instead other another one ones point points part parts""".split()
)
# Connectors that continue the thread even when they name a new item:
# "What about batch normalization?", "And for CNNs?"
_CONNECTOR_START = re.compile(r"^\s*(?:and|also|but|then|instead|what about|how about|what else|and what about)\b", re.I)
# Requests to rework or extend the previous answer: "Make it shorter", "Why?"
_FOLLOW_UP_START = re.compile(
    r"^\s*(?:so|ok(?:ay)?|why|how so|in what way|more|elaborate|expand|continue|go on|tell me more|"
    r"explain (?:that|this|it|them|more|further)|make it|rewrite|rephrase|shorten|simplify|shorter|simpler|"
    r"longer|give (?:me )?(?:an? )?examples?|what does (?:that|this|it) mean)\b",
    re.I,
)
CONNECTOR_NOVEL_WORDS = 3
_ANAPHORA = re.compile(
    r"\b(?:it|its|this|that|these|those|they|them|their|above|previous|earlier|same|former|latter|"
    r"the (?:first|second|third|last|other) (?:one|method|approach|point|paper|model|result|step|part|option))\b",
    re.I,
)


# ------------------------------------------------------------- turn analysis


@dataclass
class TurnContext:
    follow_up: bool = False
    previous_question: str = ""
    previous_answer: str = ""


def _last_exchange(history: list[dict]) -> tuple[str, str]:
    """(last user message, assistant reply that followed it)."""
    for i in range(len(history) - 1, -1, -1):
        if history[i].get("role") == "user":
            answer = " ".join(m.get("content", "") for m in history[i + 1 :] if m.get("role") == "assistant")
            return history[i].get("content", ""), answer
    return "", ""


def is_follow_up(question: str, previous_question: str, previous_answer: str) -> bool:
    if not previous_question:
        return False
    words = tokenize(question)
    seen = set(tokenize(previous_question)) | set(tokenize(previous_answer))
    novel = [w for w in words if w not in GENERIC and w not in seen]
    if not novel:
        return True  # nothing new: "Why?", "Make it shorter", "Explain the results more"
    if _ANAPHORA.search(question) and len(words) <= SHORT_FOLLOW_UP_WORDS:
        return True  # "Is it better than BERT?"
    if _CONNECTOR_START.search(question) and len(novel) <= CONNECTOR_NOVEL_WORDS:
        return True  # "What about batch normalization?", "And for CNNs?"
    if _FOLLOW_UP_START.search(question) and len(novel) <= 1:
        return True  # "Explain more about pooling"
    return False


def analyse_turn(question: str, history: list[dict]) -> TurnContext:
    previous_question, previous_answer = _last_exchange(history)
    return TurnContext(
        follow_up=is_follow_up(question, previous_question, previous_answer),
        previous_question=previous_question,
        previous_answer=previous_answer,
    )


def retrieval_query(question: str, turn: TurnContext) -> dict[str, float]:
    """BM25 query weights. A follow-up adds the previous question's terms at 0.6
    and the previous answer's most frequent terms at 0.3; the new message keeps
    full weight, so it still dominates when it names a topic of its own."""
    weights = {t: 1.0 for t in tokenize(question) if t not in GENERIC}
    if not turn.follow_up:
        return weights or {t: 1.0 for t in tokenize(question)}
    for t in tokenize(turn.previous_question):
        if t not in GENERIC:
            weights[t] = max(weights.get(t, 0.0), PREVIOUS_QUESTION_WEIGHT)
    answer_terms = Counter(t for t in tokenize(turn.previous_answer) if t not in GENERIC)
    for t, _ in answer_terms.most_common(PREVIOUS_ANSWER_TERMS):
        weights[t] = max(weights.get(t, 0.0), PREVIOUS_ANSWER_WEIGHT)
    return weights


# ---------------------------------------------------------- history window


def group_exchanges(messages: list[dict]) -> list[list[dict]]:
    """Splits a conversation into exchanges (a user turn plus the replies that
    followed it) so a window never separates a question from its answer."""
    groups: list[list[dict]] = []
    for m in messages:
        if m.get("role") == "user" or not groups:
            groups.append([m])
        else:
            groups[-1].append(m)
    return groups


def split_history(history: list[dict], budget_tokens: int) -> tuple[list[dict], list[dict]]:
    """Returns (older, recent). Everything is recent while the history fits the
    budget. Otherwise the most recent whole exchanges that fit RECENT_SHARE of the
    budget are recent (always at least the last exchange) and the rest is older.
    This is a pure function of the history, so the summary computed after one
    turn is found again by the next turn."""
    if count_messages(history) <= budget_tokens:
        return [], list(history)
    groups = group_exchanges(history)
    limit = budget_tokens * RECENT_SHARE
    kept: list[list[dict]] = []
    used = 0
    for group in reversed(groups):
        tokens = count_messages(group)
        if kept and used + tokens > limit:
            break
        kept.insert(0, group)
        used += tokens
    older = [m for g in groups[: len(groups) - len(kept)] for m in g]
    return older, [m for g in kept for m in g]


def select_relevant(groups: list[list[dict]], query: dict[str, float], budget_tokens: int) -> set[int]:
    """Extractive fallback: indices of the older exchanges most relevant to the
    new message that fit the remaining budget."""
    if budget_tokens <= 0 or not groups:
        return set()
    scores = bm25_scores(query, [" ".join(m.get("content", "") for m in g) for g in groups])
    chosen: set[int] = set()
    used = 0
    for i in sorted(range(len(groups)), key=lambda i: scores[i], reverse=True):
        if scores[i] <= 0:
            break
        tokens = count_messages(groups[i])
        if used + tokens <= budget_tokens:
            chosen.add(i)
            used += tokens
    return chosen


def history_key(user_id: str, messages: list[dict]) -> str:
    canonical = json.dumps([[m.get("role"), (m.get("content") or "").strip()] for m in messages], ensure_ascii=False)
    return hashlib.sha256(f"{user_id}\n{canonical}".encode()).hexdigest()


@dataclass
class ContextWindow:
    recent: list[dict]
    omitted: list[dict] = field(default_factory=list)  # not sent, still privacy-assessed
    memory: str = ""
    mode: str = "full"  # "none" | "full" | "summary" | "relevant_turns"


def build_window(
    user_id: str, history: list[dict], query: dict[str, float], budget_tokens: int, use_summary: bool
) -> ContextWindow:
    if not history:
        return ContextWindow(recent=[], mode="none")
    older, recent = split_history(history, budget_tokens)
    if not older:
        return ContextWindow(recent=recent)
    summary = summarizer.store.get(history_key(user_id, older)) if use_summary else None
    if summary:
        return ContextWindow(recent=recent, omitted=older, memory=summary["text"], mode="summary")
    groups = group_exchanges(older)
    keep = select_relevant(groups, query, budget_tokens - count_messages(recent))
    kept = [m for i, g in enumerate(groups) if i in keep for m in g]
    omitted = [m for i, g in enumerate(groups) if i not in keep for m in g]
    return ContextWindow(recent=kept + recent, omitted=omitted, mode="relevant_turns")


# ------------------------------------------------------------ rolling summary

SUMMARY_SYSTEM = (
    "You keep a running summary of a conversation between a user and an assistant about academic "
    "documents. Keep the user's goals and questions, specific facts, numbers, names of papers, methods "
    "and datasets, conclusions reached, and anything the user asked to remember. Do not add anything "
    "that was not said. Write plain prose."
)


def summary_max_tokens(budget_tokens: int) -> int:
    return max(min(int(budget_tokens * (1 - RECENT_SHARE)), 600), 64)


def summary_messages(base: str | None, new: list[dict], max_tokens: int, context_window: int) -> list[dict]:
    transcript = "\n".join(
        f"{'User' if m.get('role') == 'user' else 'Assistant'}: {m.get('content', '')}" for m in new
    )
    limit = max(context_window - max_tokens - 600 - count_tokens(base or ""), 500)
    if count_tokens(transcript) > limit:
        transcript = "[earlier part omitted]\n" + transcript[-int(limit * 3.5) :]
    words = int(max_tokens * 0.7)
    body = []
    if base:
        body.append(f"Summary so far:\n{base}\n")
    body.append(f"{'New turns' if base else 'Conversation'}:\n{transcript}\n")
    body.append(f"Write the {'updated ' if base else ''}summary in at most {words} words.")
    return [{"role": "system", "content": SUMMARY_SYSTEM}, {"role": "user", "content": "\n".join(body)}]


class Summarizer:
    """Writes conversation summaries with a local model on one background thread
    (so summaries never compete with each other for the GPU). Summaries live in
    memory only, expire with the chat session, and are never written to the
    database."""

    def __init__(self):
        self.store = ResponseCache()
        self.inline = False  # tests run jobs synchronously
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="summarizer")
        self._pending: set[str] = set()
        self._lock = threading.Lock()

    def schedule(self, *, user_id: str, conversation: list[dict], spec: ModelSpec, budget_tokens: int, ttl_s: int) -> str | None:
        """Prepares the summary the NEXT turn of this conversation will need.
        Returns the summary key if a job was started."""
        if not spec.is_local:
            raise ValueError("conversation summaries may only be written by a local model")
        older, _ = split_history(conversation, budget_tokens)
        if not older:
            return None
        key = history_key(user_id, older)
        with self._lock:
            if key in self._pending or self.store.get(key) is not None:
                return None
            self._pending.add(key)
        job = partial(self._run, key, user_id, older, spec, budget_tokens, ttl_s)
        if self.inline:
            job()
        else:
            self._executor.submit(job)
        return key

    def _incremental_base(self, user_id: str, older: list[dict]) -> tuple[str | None, list[dict]]:
        """Extends the longest earlier summary instead of rereading everything."""
        groups = group_exchanges(older)
        for i in range(len(groups) - 1, 0, -1):
            prefix = [m for g in groups[:i] for m in g]
            hit = self.store.get(history_key(user_id, prefix))
            if hit:
                return hit["text"], [m for g in groups[i:] for m in g]
        return None, older

    def _run(self, key: str, user_id: str, older: list[dict], spec: ModelSpec, budget_tokens: int, ttl_s: int) -> None:
        started = time.perf_counter()
        status, error, in_tokens, out_tokens = "failed", None, 0, 0
        try:
            base, new = self._incremental_base(user_id, older)
            max_tokens = summary_max_tokens(budget_tokens)
            request = ChatRequest(
                model_id=spec.model_id,
                messages=summary_messages(base, new, max_tokens, spec.context_window),
                max_tokens=max_tokens,
                params=spec.params,
            )
            result = build_provider(spec, None).complete(request)
            in_tokens, out_tokens = result.in_tokens, result.out_tokens
            text = result.text.strip()
            if text and result.finish_reason != FINISH_REFUSAL:
                self.store.put(key, {"text": text}, ttl_s)
                status = "ok"
            else:
                status = "empty"
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"[:500]
            log.warning("conversation summary failed: %s", error)
        finally:
            with self._lock:
                self._pending.discard(key)
            try:
                with session_scope() as db:
                    db.add(
                        Attempt(
                            user_id=user_id, model_name=spec.name, purpose="summary", credential_scope="local",
                            status=status, in_tokens=in_tokens, out_tokens=out_tokens, cost_usd=0.0,
                            latency_ms=(time.perf_counter() - started) * 1000, error=error,
                        )
                    )
            except Exception:
                log.exception("could not record the summary attempt")

    def clear(self) -> None:
        self.store.clear()
        with self._lock:
            self._pending.clear()


summarizer = Summarizer()
