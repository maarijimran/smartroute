"""Point the local, cheap and strong tiers at three Ollama models (no cloud keys needed).

    python scripts/register_ollama_tiers.py
    python scripts/register_ollama_tiers.py --ctx-local 16384 --ctx-cheap 16384 --ctx-strong 8192

Used while the project has no cloud API keys: every tier runs on this GPU through
Ollama. The cheap and strong tiers carry SIMULATED prices (the seeded Claude Haiku /
Opus rates), so the router still learns a cost trade-off. Their measured "cost" in
outcomes and analytics is that simulation, not money spent: say so in the report.

All three are local, so the privacy gate never blocks them and every benchmark request
gets a complete row of outcomes. When cloud keys exist, the superadmin sets the cheap and
strong tiers to cloud models in Settings -> Models. The tiers keep their trained router
weights (see app/core/tiers.py); collect outcomes for the new models and retrain when
the evaluation needs them.

Idempotent: it edits the three tier slots in place and keeps their names, so the
learners' weights stay attached.
"""

import argparse

import _common  # noqa: F401
from sqlalchemy import select

from app.bootstrap import bootstrap
from app.config import get_settings
from app.core.providers.base import simulated_latency_ms
from app.db import SessionLocal, create_all
from app.core.tiers import set_tier
from app.models import ModelEntry

# tier, display name, Ollama tag, simulated $/Mtok in, out, extra params
TIERS = [
    ("local", "gpt-oss 20B", "gpt-oss:20b", 0.0, 0.0,
     # gpt-oss cannot turn reasoning off; "low" keeps it short. Its reasoning tokens
     # count against num_predict, so reserve room for them.
     {"think": "low", "reasoning_overhead_tokens": 768}),
    ("cheap", "Qwen3.5 9B", "qwen3.5:9b", 0.10, 0.50,
     {"think": False, "simulated_latency": {"base_s": 0.5, "prefill_tps": 20000, "decode_tps": 150}}),
    ("strong", "Qwen3.6 27B", "qwen3.6:27b", 4.00, 20.00,
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
        for tier, display, tag, p_in, p_out, extra in TIERS:
            params = {"options": {"num_ctx": ctx[tier]}, **extra}
            m = set_tier(
                db, tier, None, vendor="ollama", model_id=tag, display_name=display,
                base_url=get_settings().ollama_base_url, context_window=ctx[tier],
                max_output_tokens=args.max_output, price_in_per_mtok=p_in, price_out_per_mtok=p_out,
                params=params,
            )
            sim = simulated_latency_ms(m.params, *TYPICAL_TOKENS)
            if sim is not None:
                m.latency_ewma_ms = sim  # otherwise the estimate starts from local GPU timings
        db.commit()
        for m in db.execute(select(ModelEntry).order_by(ModelEntry.tier)).scalars():
            print(f"{m.name:14} {m.tier:7} {m.model_id:28} ctx={m.context_window:<6} "
                  f"${m.price_in_per_mtok}/{m.price_out_per_mtok} latency~{m.latency_ewma_ms / 1000:.1f}s "
                  f"enabled={m.enabled} params={m.params}")

if __name__ == "__main__":
    main()
