"""Register three Ollama models as the local, cheap and strong tiers (no cloud keys needed).

    python scripts/register_ollama_tiers.py
    python scripts/register_ollama_tiers.py --ctx-local 16384 --ctx-cheap 16384 --ctx-strong 8192

Used while the project has no cloud API keys: every tier runs on this GPU through
Ollama. The cheap and strong tiers carry SIMULATED prices (the seeded Claude Haiku /
Opus rates), so the router still learns a cost trade-off. Their measured "cost" in
outcomes and analytics is that simulation, not money spent: say so in the report.

All three are registered as local, so the privacy gate never blocks them and every
benchmark request gets a complete row of outcomes. The claude-* entries are disabled
(no keys); re-enable them in Settings -> Models once keys exist, and collect outcomes
again, because a frozen router only knows the models it was trained on.

Idempotent: rerunning updates the entries in place.
"""

import argparse

import _common  # noqa: F401
from sqlalchemy import select

from app.bootstrap import bootstrap
from app.config import get_settings
from app.core.providers.base import simulated_latency_ms
from app.db import SessionLocal, create_all
from app.models import ModelEntry

# name, display name, Ollama tag, tier, simulated $/Mtok in, out, extra params
TIERS = [
    ("local-default", "gpt-oss 20B", "gpt-oss:20b", "local", 0.0, 0.0,
     # gpt-oss cannot turn reasoning off; "low" keeps it short. Its reasoning tokens
     # count against num_predict, so reserve room for them.
     {"think": "low", "reasoning_overhead_tokens": 768}),
    ("sim-cheap", "Qwen3.5 9B", "qwen3.5:9b", "cheap", 0.10, 0.50,
     {"think": False, "simulated_latency": {"base_s": 0.5, "prefill_tps": 20000, "decode_tps": 150}}),
    ("sim-strong", "Qwen3.6 27B", "qwen3.6:27b", "strong", 4.00, 20.00,
     {"think": False, "simulated_latency": {"base_s": 1.2, "prefill_tps": 8000, "decode_tps": 60}}),
]
# SIMULATED CLOUD LATENCY (an assumption; declare it in the evaluation protocol).
# Locally the 27B model is the slowest tier, but as a hosted API it would answer
# faster than this GPU serves it. The cheap/strong tiers therefore report
#   base (network + queueing) + prompt / prefill speed + output / decode speed,
# with figures typical of a small fast hosted model and a large frontier model.
# The router's latency estimate and the outcomes' latency_ms use this; the
# measured local latency is kept as measured_latency_ms. After changing these
# numbers, rerun this script and scripts/apply_latency_model.py (no recollection).
TYPICAL_TOKENS = (1500, 150)  # in, out: seeds the latency estimate before any traffic


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ctx-local", type=int, default=16384)
    parser.add_argument("--ctx-cheap", type=int, default=16384)
    parser.add_argument("--ctx-strong", type=int, default=16384)
    parser.add_argument("--max-output", type=int, default=2048)
    args = parser.parse_args()
    ctx = {"local": args.ctx_local, "cheap": args.ctx_cheap, "strong": args.ctx_strong}

    create_all()
    with SessionLocal() as db:
        bootstrap(db)
        existing = {m.name: m for m in db.execute(select(ModelEntry)).scalars()}
        for name, display, tag, tier, p_in, p_out, extra in TIERS:
            m = existing.get(name) or ModelEntry(name=name)
            m.display_name, m.vendor, m.model_id, m.tier = display, "ollama", tag, tier
            m.is_local, m.enabled = True, True
            m.base_url = get_settings().ollama_base_url
            m.context_window, m.max_output_tokens = ctx[tier], args.max_output
            m.price_in_per_mtok, m.price_out_per_mtok = p_in, p_out
            # num_ctx must equal context_window, or Ollama truncates silently.
            m.params = {"options": {"num_ctx": ctx[tier]}, **extra}
            m.unhealthy_until, m.last_error = None, None
            sim = simulated_latency_ms(m.params, *TYPICAL_TOKENS)
            if sim is not None:
                m.latency_ewma_ms = sim  # otherwise the estimate starts from local GPU timings
            db.add(m)
        for name, m in existing.items():
            if m.vendor != "ollama" and m.enabled:
                m.enabled = False
                print(f"disabled {name} ({m.vendor}: no key on this server)")
        db.commit()
        for m in db.execute(select(ModelEntry).order_by(ModelEntry.tier)).scalars():
            print(f"{m.name:14} {m.tier:7} {m.model_id:28} ctx={m.context_window:<6} "
                  f"${m.price_in_per_mtok}/{m.price_out_per_mtok} latency~{m.latency_ewma_ms / 1000:.1f}s "
                  f"enabled={m.enabled} params={m.params}")


if __name__ == "__main__":
    main()
