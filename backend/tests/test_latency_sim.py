"""Simulated cloud latency for locally served stand-in tiers."""

import pytest

from app.core.providers.base import ModelSpec, simulated_latency_ms

SIM = {"simulated_latency": {"base_s": 1.0, "prefill_tps": 1000, "decode_tps": 50}}


def _spec(params):
    return ModelSpec(
        name="m", vendor="ollama", model_id="m", tier="strong", is_local=True, base_url=None,
        context_window=8192, max_output_tokens=2048, price_in_per_mtok=0, price_out_per_mtok=0,
        params=params, latency_s=1.0,
    )


def test_latency_model_formula():
    # 1 s base + 2000/1000 s prefill + 100/50 s decode = 5 s
    assert simulated_latency_ms(SIM, 2000, 100) == pytest.approx(5000)


def test_no_latency_model_means_measured_is_real():
    assert simulated_latency_ms({"options": {"num_ctx": 8192}}, 2000, 100) is None
    assert _spec({}).router_latency_ms(7300.0, 2000, 100) == 7300.0


def test_stand_in_tier_reports_simulated_latency():
    assert _spec(SIM).router_latency_ms(7300.0, 2000, 100) == pytest.approx(5000)
