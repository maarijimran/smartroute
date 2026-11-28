"""Step 3 (server): collect full-information outcomes. THIS STEP SPENDS API MONEY.

    python scripts/collect_outcomes.py --models local cheap strong --by-model --budget-usd 55

--models takes tier names (local, cheap, strong: whatever model the superadmin has set
for that tier) or registry names. Every workload request is answered by every listed
model (pinned), scored automatically, and appended to data/outcomes.jsonl. The run is
resumable: pairs already in the output file are skipped. It stops when measured spend
reaches --budget-usd.

Each row records the provider's model string. After a tier's model has been changed,
write to a new file (--out data/outcomes_<name>.jsonl): the script refuses to mix two
models' answers under one tier in the same file.

Run it with the feature artifact already fitted (scripts/fit_features.py), because
the context vector of each request is stored with its outcome.

Requests go through the normal pipeline, so the privacy gate, context filter and
cost ledger all apply. Benchmark events are tagged source="eval" and never train
the live learner.
"""

import argparse
import os
import sys

import _common  # noqa: F401
from sqlalchemy import select

from app.bootstrap import bootstrap
from app.core import pipeline
from app.core.providers import build_provider
from app.core.providers.base import ChatRequest
from app.db import SessionLocal, create_all
from app.evaluation.scoring import score_answer
from app.evaluation.workload import append_jsonl, ensure_documents, ensure_eval_user, load_jsonl, request_for
from app.core.tiers import TIERS, slot
from app.models import ModelEntry


def _warm_up(entry: ModelEntry) -> None:
    """One tiny unlogged request so a local model is loaded before it is timed."""
    spec = pipeline.spec_from_entry(entry)
    request = ChatRequest(model_id=spec.model_id, messages=[{"role": "user", "content": "Hi"}],
                          max_tokens=8 + spec.reasoning_overhead, temperature=None, params=spec.params)
    try:
        for _ in build_provider(spec, None).stream(request):
            pass
    except Exception as exc:  # the real call will record the failure properly
        print(f"  warm-up of {entry.name} failed: {exc}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--workload", default=_common.data_path("workload.jsonl"))
    parser.add_argument("--docs-dir", default=os.path.dirname(_common.data_path("docs", "x")))
    parser.add_argument("--out", default=_common.data_path("outcomes.jsonl"))
    parser.add_argument("--models", nargs="+", required=True, help="tiers (local cheap strong) or registry names")
    parser.add_argument("--budget-usd", type=float, required=True, help="stop when measured spend reaches this")
    parser.add_argument("--splits", nargs="+", default=["train", "validation", "test"])
    parser.add_argument("--limit", type=int, default=None, help="only the first N requests (pilot runs)")
    parser.add_argument(
        "--by-model", action="store_true",
        help="answer every request with one model before the next. Use when several models share "
             "one GPU, so Ollama does not reload a model on every call and inflate its latency.",
    )
    args = parser.parse_args()

    items = [i for i in load_jsonl(args.workload) if i["split"] in args.splits][: args.limit]
    done = set()
    seen_ids: dict[str, set] = {}
    spent = 0.0
    if os.path.exists(args.out):
        for row in load_jsonl(args.out):
            done.add((row["item_id"], row["model"]))
            seen_ids.setdefault(row["model"], set()).add(row.get("model_id"))
            spent += row["cost_usd"]

    create_all()
    with SessionLocal() as db:
        bootstrap(db)
        user = ensure_eval_user(db)
        registry = {m.name: m for m in db.execute(select(ModelEntry)).scalars()}
        # Tier names resolve to the model the superadmin has set for that tier.
        args.models = [slot(db, m).name if m in TIERS and m not in registry and slot(db, m) else m for m in args.models]
        missing = [m for m in args.models if m not in registry or not registry[m].enabled]
        if missing:
            return sys.exit(f"Not registered or not enabled: {missing}")
        for m in args.models:
            # Rows written before model ids were recorded (None) are taken to be the same model.
            other = {i for i in seen_ids.get(m, set()) if i is not None and i != registry[m].model_id}
            if other:
                return sys.exit(
                    f"{args.out} already has answers from {sorted(other)} under '{m}', which is now "
                    f"{registry[m].model_id}. Write to a new file with --out."
                )
        doc_map = ensure_documents(db, user, {i["doc_id"] for i in items if i.get("doc_id")}, args.docs_dir)
        total = len(items) * len(args.models)
        n = len(done)
        print(f"{total} model calls planned, {n} already done, ${spent:.4f} spent so far")
        if args.by_model:
            pairs = [(item, model) for model in args.models for item in items]
        else:
            pairs = [(item, model) for item in items for model in args.models]
        warmed = None
        for item, model in pairs:
            if (item["item_id"], model) in done:
                continue
            if args.by_model and model != warmed and registry[model].is_local:
                _warm_up(registry[model])  # keep the model's load time out of its first latency
                warmed = model
            if spent >= args.budget_usd:
                print(f"Budget of ${args.budget_usd:.2f} reached after {n} calls. Re-run to resume.")
                return 2
            plan = pipeline.prepare(db, request_for(item, user, doc_map, args.docs_dir, pinned_model=model))
            outcome = pipeline.run_to_completion(plan)
            ok = outcome.status == "ok"
            auto = score_answer(outcome.text, item["golds"], item["unanswerable"], item["task"]) if ok else 0.0
            route = plan.routes.get(model)
            append_jsonl(args.out, {
                "item_id": item["item_id"], "doc_id": item["doc_id"], "split": item["split"],
                "category": item["category"], "task": item["task"], "model": model,
                "model_id": registry[model].model_id, "vendor": registry[model].vendor,
                "tier": registry[model].tier, "is_local": registry[model].is_local,
                "status": outcome.status, "quality": auto, "quality_source": "auto",
                "cost_usd": outcome.cost_usd, "est_cost_usd": route.est_cost_usd if route else 0.0,
                # Stand-in cloud tiers get their simulated API latency; the real one is kept.
                "latency_ms": pipeline.spec_from_entry(registry[model]).router_latency_ms(
                    outcome.latency_ms, outcome.in_tokens, outcome.out_tokens),
                "measured_latency_ms": outcome.latency_ms, "ttft_ms": outcome.ttft_ms,
                "in_tokens": outcome.in_tokens, "out_tokens": outcome.out_tokens,
                "features": plan.x,
                "qf": plan.qf,  # Router v2 base features; the embedding dimensions are the tail of "features"
                "kind": item.get("kind"),
                "info": {"in_tokens": plan.est_in_tokens, "complexity": plan.info.complexity,
                         "has_document": plan.info.has_document},
                "event_id": outcome.event_id, "error": outcome.error or plan.abstain_reason,
                "prompt": item["prompt"], "answer": outcome.text,
            })
            spent += outcome.cost_usd
            n += 1
            if n % 25 == 0:
                print(f"  {n}/{total} calls, ${spent:.4f} spent")
    print(f"Finished: {n} calls, ${spent:.4f} measured API spend. Output: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
