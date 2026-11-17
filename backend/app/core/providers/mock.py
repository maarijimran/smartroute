"""Deterministic fake provider.

Lets the whole gateway (routing, privacy gate, RBAC, UI) run on a machine with no
model and no API key, and lets tests record exactly what would have left the host.
Only available outside production.
"""

from __future__ import annotations

import threading
from typing import Iterator

from ..tokens import count_messages, count_tokens
from .base import FINISH_LENGTH, FINISH_STOP, ChatRequest, ChatResult, Provider, ProviderError


class MockProvider(Provider):
    # Every payload "sent" by a non-local mock model, so tests and the privacy
    # suite can assert that nothing confidential was dispatched.
    dispatched: list[dict] = []
    _lock = threading.Lock()

    def __init__(self, is_local: bool):
        self.is_local = is_local

    @classmethod
    def reset(cls) -> None:
        with cls._lock:
            cls.dispatched.clear()

    def stream(self, req: ChatRequest) -> Iterator[str | ChatResult]:
        with self._lock:
            if not self.is_local:
                self.dispatched.append({"model": req.model_id, "messages": req.messages})
                del self.dispatched[:-500]
        behaviour = req.params.get("mock", "ok")
        if behaviour == "fail":
            raise ProviderError("mock failure", status=503)
        text = "" if behaviour == "empty" else f"Demo response ({req.model_id})."
        for word in text.split(" "):
            if word:
                yield word + " "
        yield ChatResult(
            text=text,
            in_tokens=count_messages(req.messages),
            out_tokens=count_tokens(text),
            finish_reason=FINISH_LENGTH if behaviour == "truncate" else FINISH_STOP,
            served_model=req.model_id,
        )
