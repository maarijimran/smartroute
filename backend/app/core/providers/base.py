"""Common request/response shapes shared by every provider adapter."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterator

FINISH_STOP = "stop"
FINISH_LENGTH = "length"  # hit the output cap: treated as a truncated answer
FINISH_REFUSAL = "refusal"
FINISH_OTHER = "other"

# Price multipliers for cached input tokens, as (read, write), relative to the
# normal input price. Anthropic publishes 0.1x for cache reads and 1.25x for
# 5-minute cache writes. For every other vendor the default is 1.0 (no discount
# assumed), which overstates cost rather than understating it; set
# "cache_read_multiplier" in the model's adapter options from its pricing page.
CACHE_MULTIPLIERS = {"anthropic": (0.1, 1.25)}


@dataclass(frozen=True)
class ModelSpec:
    """Plain copy of a registry row, safe to hold after the database session closes."""

    name: str
    vendor: str
    model_id: str
    tier: str
    is_local: bool
    base_url: str | None
    context_window: int
    max_output_tokens: int
    price_in_per_mtok: float
    price_out_per_mtok: float
    params: dict
    latency_s: float

    def cost_usd(self, in_tokens: int, out_tokens: int, cache_read: int = 0, cache_write: int = 0) -> float:
        # in_tokens is the total input; cache_read and cache_write are the parts
        # of it billed at the provider's cache rates.
        read_mult, write_mult = CACHE_MULTIPLIERS.get(self.vendor, (1.0, 1.0))
        read_mult = float(self.params.get("cache_read_multiplier", read_mult))
        write_mult = float(self.params.get("cache_write_multiplier", write_mult))
        uncached = max(in_tokens - cache_read - cache_write, 0)
        input_cost = (uncached + cache_read * read_mult + cache_write * write_mult) * self.price_in_per_mtok
        return (input_cost + out_tokens * self.price_out_per_mtok) / 1_000_000

    @property
    def reasoning_overhead(self) -> int:
        """Extra output budget for models that spend output tokens on thinking."""
        return int(self.params.get("reasoning_overhead_tokens", 0))

    def router_latency_ms(self, measured_ms: float, in_tokens: int, out_tokens: int) -> float:
        """The latency the router learns from: measured, unless the entry stands in
        for a cloud API (see simulated_latency_ms)."""
        simulated = simulated_latency_ms(self.params, in_tokens, out_tokens)
        return measured_ms if simulated is None else simulated


def simulated_latency_ms(params: dict, in_tokens: int, out_tokens: int) -> float | None:
    """Cloud-API latency for a model that is served locally only as a stand-in.

    params["simulated_latency"] = {"base_s": ..., "prefill_tps": ..., "decode_tps": ...}
    latency = base (network + queueing) + prompt / prefill speed + output / decode speed.
    Returns None when the entry has no latency model, i.e. its measured latency is real.
    """
    sim = params.get("simulated_latency")
    if not sim:
        return None
    seconds = (
        float(sim["base_s"])
        + max(in_tokens, 0) / float(sim["prefill_tps"])
        + max(out_tokens, 0) / float(sim["decode_tps"])
    )
    return seconds * 1000


@dataclass(frozen=True)
class CredentialSpec:
    api_key: str
    base_url: str | None = None
    api_version: str | None = None
    scope: str = "user"  # "user" (the caller's own key) | "platform"


@dataclass
class ChatRequest:
    model_id: str
    messages: list[dict]  # [{"role": "system"|"user"|"assistant", "content": str}]
    max_tokens: int
    temperature: float | None = None
    params: dict = field(default_factory=dict)


@dataclass
class ChatResult:
    text: str
    in_tokens: int
    out_tokens: int
    finish_reason: str = FINISH_STOP
    served_model: str | None = None
    cache_read_tokens: int = 0  # included in in_tokens
    cache_write_tokens: int = 0  # included in in_tokens


class ProviderError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class Provider:
    """Adapters yield text deltas (str) as they arrive and finish with one ChatResult."""

    def stream(self, req: ChatRequest) -> Iterator[str | ChatResult]:
        raise NotImplementedError

    def complete(self, req: ChatRequest) -> ChatResult:
        result = None
        for item in self.stream(req):
            if isinstance(item, ChatResult):
                result = item
        if result is None:
            raise ProviderError("provider returned no result")
        return result
