"""Apply the registry's simulated cloud latency to collected outcomes.

    python scripts/apply_latency_model.py              # rewrites data/outcomes.jsonl in place
    python scripts/apply_latency_model.py --dry-run    # print the per-model effect only

Models registered with params["simulated_latency"] (the cheap and strong tiers while
they are local stand-ins for cloud APIs) get

    latency_ms = base_s + in_tokens / prefill_tps + out_tokens / decode_tps

and their measured local latency moves to measured_latency_ms. Models without a latency
model keep their measured latency. Idempotent: it always starts from the measured value,
so it can be rerun after changing the latency model in the registry.

Do not run it while collect_outcomes.py is writing the same file.
"""

import argparse
import json
import os
from collections import defaultdict

import numpy as np

import _common
from sqlalchemy import select

from app.core.providers.base import simulated_latency_ms
from app.db import SessionLocal, create_all
from app.evaluation.workload import load_jsonl
from app.models import ModelEntry


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--outcomes", default=_common.data_path("outcomes.jsonl"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    create_all()
    with SessionLocal() as db:
        params = {m.name: dict(m.params or {}) for m in db.execute(select(ModelEntry)).scalars()}

    rows = load_jsonl(args.outcomes)
    before, after = defaultdict(list), defaultdict(list)
    for r in rows:
        measured = r.get("measured_latency_ms", r["latency_ms"])
        sim = simulated_latency_ms(params.get(r["model"], {}), r["in_tokens"], r["out_tokens"])
        r["measured_latency_ms"] = measured
        r["latency_ms"] = measured if sim is None else sim
        if r["status"] == "ok":
            before[r["model"]].append(measured / 1000)
            after[r["model"]].append(r["latency_ms"] / 1000)

    for model in before:
        kind = "simulated" if params.get(model, {}).get("simulated_latency") else "measured (unchanged)"
        print(f"{model:14} median {np.median(before[model]):5.1f}s -> {np.median(after[model]):5.1f}s   "
              f"p90 {np.percentile(before[model], 90):5.1f}s -> {np.percentile(after[model], 90):5.1f}s   {kind}")
    if args.dry_run:
        return
    tmp = args.outcomes + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(tmp, args.outcomes)
    print(f"Rewrote {len(rows)} rows in {args.outcomes}")


if __name__ == "__main__":
    main()
