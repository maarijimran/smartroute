"""Token estimation done locally before any dispatch.

Uses tiktoken when it is installed (server), otherwise a conservative character
heuristic. Provider tokenizers differ, so the eligibility filter adds a safety
margin on top (PolicyConfig.context_safety_margin).
"""

import math

_encoder = None
_tried = False


def _get_encoder():
    global _encoder, _tried
    if not _tried:
        _tried = True
        try:
            import tiktoken

            _encoder = tiktoken.get_encoding("cl100k_base")
        except Exception:
            _encoder = None
    return _encoder


def count_tokens(text: str) -> int:
    if not text:
        return 0
    enc = _get_encoder()
    if enc is not None:
        return len(enc.encode(text, disallowed_special=()))
    return math.ceil(len(text) / 3.6)


def count_messages(messages: list[dict]) -> int:
    # ~4 tokens of framing per message, as in chat formats.
    return sum(count_tokens(m.get("content", "")) + 4 for m in messages) + 2
