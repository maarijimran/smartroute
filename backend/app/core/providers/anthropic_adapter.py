"""Native adapter for the Claude Messages API, using the official Anthropic SDK."""

from __future__ import annotations

from typing import Iterator

import anthropic

from .base import (
    FINISH_LENGTH,
    FINISH_OTHER,
    FINISH_REFUSAL,
    FINISH_STOP,
    ChatRequest,
    ChatResult,
    Provider,
    ProviderError,
)

_FINISH = {
    "end_turn": FINISH_STOP,
    "stop_sequence": FINISH_STOP,
    "max_tokens": FINISH_LENGTH,
    "refusal": FINISH_REFUSAL,
}
# Models where a safety decline can be re-run server-side on a fallback model.
_FALLBACK_MODELS = {"claude-fable-5-2", "claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"}
_FALLBACK_BETA = "server-side-fallback-2026-07-01"


def split_system(messages: list[dict]) -> tuple[str, list[dict]]:
    """The Messages API takes the system prompt as a top-level field and requires
    the conversation to start with a user turn."""
    system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
    turns = [{"role": m["role"], "content": m["content"]} for m in messages if m["role"] in ("user", "assistant")]
    while turns and turns[0]["role"] != "user":
        turns.pop(0)
    return system, turns


def build_kwargs(req: ChatRequest, system: str, turns: list[dict]) -> dict:
    kwargs: dict = {"model": req.model_id, "max_tokens": req.max_tokens, "messages": turns}
    if system:
        kwargs["system"] = system
    if req.params.get("prompt_caching", True):
        # Automatic prompt caching: the provider caches the request prefix (system
        # prompt and earlier turns), so the next turn of the conversation re-reads
        # it at a tenth of the input price and with a shorter time to first token.
        # Prefixes below the model's minimum cacheable length are simply not cached.
        kwargs["cache_control"] = {"type": "ephemeral"}
    kwargs.update(req.params.get("request", {}))
    return kwargs


class AnthropicProvider(Provider):
    def __init__(self, api_key: str, timeout_s: float, base_url: str | None = None, refusal_fallbacks: bool = True):
        kwargs: dict = {"api_key": api_key, "timeout": timeout_s, "max_retries": 1}
        if base_url:
            kwargs["base_url"] = base_url
        self.client = anthropic.Anthropic(**kwargs)
        self.refusal_fallbacks = refusal_fallbacks

    def stream(self, req: ChatRequest) -> Iterator[str | ChatResult]:
        system, turns = split_system(req.messages)
        if not turns:
            raise ProviderError("no user message to send")
        # Sampling parameters such as temperature are rejected by current Claude
        # models, so they are intentionally never forwarded.
        kwargs = build_kwargs(req, system, turns)
        parts: list[str] = []
        try:
            if self.refusal_fallbacks and req.model_id in _FALLBACK_MODELS:
                manager = self.client.beta.messages.stream(betas=[_FALLBACK_BETA], fallbacks="default", **kwargs)
            else:
                manager = self.client.messages.stream(**kwargs)
            with manager as stream:
                for text in stream.text_stream:
                    parts.append(text)
                    yield text
                final = stream.get_final_message()
        except anthropic.BadRequestError as exc:
            raise ProviderError(f"bad request: {exc.message}", status=400) from exc
        except anthropic.AuthenticationError as exc:
            raise ProviderError("invalid Anthropic API key", status=401) from exc
        except anthropic.PermissionDeniedError as exc:
            raise ProviderError("Anthropic API key lacks permission for this model", status=403) from exc
        except anthropic.NotFoundError as exc:
            raise ProviderError(f"unknown Claude model '{req.model_id}'", status=404) from exc
        except anthropic.RateLimitError as exc:
            raise ProviderError("Anthropic rate limit reached", status=429) from exc
        except anthropic.APIStatusError as exc:
            raise ProviderError(f"Anthropic API error {exc.status_code}", status=exc.status_code) from exc
        except anthropic.APIConnectionError as exc:
            raise ProviderError(f"could not reach the Anthropic API ({type(exc).__name__})") from exc

        usage = final.usage
        cache_write = getattr(usage, "cache_creation_input_tokens", 0) or 0
        cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
        yield ChatResult(
            text="".join(parts),
            in_tokens=(usage.input_tokens or 0) + cache_write + cache_read,
            out_tokens=usage.output_tokens or 0,
            finish_reason=_FINISH.get(final.stop_reason or "", FINISH_OTHER),
            served_model=final.model,
            cache_read_tokens=cache_read,
            cache_write_tokens=cache_write,
        )
