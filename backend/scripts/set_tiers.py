"""Point the tiers at Ollama models for a collection round (Kaggle or the server).

    python scripts/set_tiers.py --local gpt-oss:20b --cheap qwen3.5:9b --strong phi4:14b
    python scripts/set_tiers.py --local llama3.2:3b --ctx 16384

Router v2 needs answers from several models of different strength, but a tier holds one
model at a time, so collection runs in rounds: set the tiers, collect into its own file
(collect_outcomes.py --out data/outcomes_<round>.jsonl), switch, repeat. Tiers that are
not given keep their model. Cheap and strong get simulated cloud prices and latency, as
in register_ollama_tiers.py; that matters for cost figures, not for quality training.
"""

import argparse

import _common  # noqa: F401
from sqlalchemy import select

from app.bootstrap import bootstrap
from app.config import get_settings
from app.core.providers.base import simulated_latency_ms
from app.core.tiers import set_tier
from app.db import SessionLocal, create_all
from app.models import ModelEntry

SIMULATED = {
    "local": (0.0, 0.0, None),
    "cheap": (0.10, 0.50, {"base_s": 0.5, "prefill_tps": 20000, "decode_tps": 150}),
    "strong": (4.00, 20.00, {"base_s": 1.2, "prefill_tps": 8000, "decode_tps": 60}),
}


def family_params(tag: str) -> dict:
    """Settings that keep reasoning models within the output budget (see the server run)."""
    if tag.startswith("gpt-oss"):
        return {"think": "low", "reasoning_overhead_tokens": 768}
    if tag.startswith(("qwen3", "deepseek-r1")):
        return {"think": False}
    return {}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for tier in ("local", "cheap", "strong"):
        parser.add_argument(f"--{tier}", default=None, help="Ollama tag")
    parser.add_argument("--ctx", type=int, default=16384, help="context window for every tier set here")
    parser.add_argument("--max-output", type=int, default=2048)
    args = parser.parse_args()

    create_all()
    with SessionLocal() as db:
        bootstrap(db)
        for tier in ("local", "cheap", "strong"):
            tag = getattr(args, tier)
            if not tag:
                continue
            p_in, p_out, sim = SIMULATED[tier]
            params = {"options": {"num_ctx": args.ctx}, **family_params(tag)}
            if sim:
                params["simulated_latency"] = sim
            m = set_tier(db, tier, None, vendor="ollama", model_id=tag, display_name=tag,
                         base_url=get_settings().ollama_base_url, context_window=args.ctx,
                         max_output_tokens=args.max_output, price_in_per_mtok=p_in, price_out_per_mtok=p_out,
                         params=params)
            latency = simulated_latency_ms(m.params, 1500, 150)
            if latency is not None:
                m.latency_ewma_ms = latency
        db.commit()
        for m in db.execute(select(ModelEntry).where(ModelEntry.enabled.is_(True)).order_by(ModelEntry.tier)).scalars():
            print(f"{m.tier:7} {m.name:14} {m.vendor}:{m.model_id}  ctx={m.context_window}")


if __name__ == "__main__":
    main()
