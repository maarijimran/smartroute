"""Step 5: evaluate every routing policy offline and write the report.

    python scripts/evaluate.py                                   # data/outcomes.jsonl
    python scripts/evaluate.py --ratings data/ratings.json       # blend in human ratings
    python scripts/evaluate.py --outcomes data/outcomes_synthetic.jsonl   # dry run

Costs nothing: it only reads the outcome table collected earlier.

Answers the three research questions:
  RQ1  static TEST split: cost saving and paired quality difference versus
       strong-cloud-only, with document-clustered 95% confidence intervals
  RQ2  streams with a controlled change (task shift, latency drift, silent quality
       drop): fixed rules vs frozen router vs adaptive bandits, over several seeds
  RQ3  is answered by scripts/run_privacy_suite.py, not here

Reward settings come from --policy-json (export of the saved policy), so the
numbers match what the gateway used. Freeze them before looking at test results.
"""

import argparse
import json

import numpy as np

import _common
from app.core.policy_config import PolicyConfig, RewardWeights
from app.evaluation import analysis as an
from app.evaluation.judge import load_judgements
from app.evaluation.synthetic import SYNTHETIC_CFG

TARGET_SAVING, QUALITY_MARGIN = 0.20, -0.05


def pct(v: float) -> str:
    return "   n/a" if v is None or np.isnan(v) else f"{100 * v:5.1f}%"


def static_test(table, cfg, seeds: int, n_boot: int) -> dict:
    train, val, test = table.split("train"), table.split("validation"), table.split("test")
    strong = test.tier_model("strong") or test.models[int(test.cost.mean(axis=0).argmax())]
    lat = an.mean_latency(train)
    arms = an.fit_arms(train, cfg)

    policies: dict[str, np.ndarray] = {}
    for model in test.models:
        policies[f"only:{model}"] = an.choose_fixed(test, model)
    policies["rules"] = an.choose_rules(test, lat)
    policies["frozen-ridge"] = an.choose_frozen(test, arms, cfg, lat)
    policies["knn"] = an.choose_knn(test, train, cfg)
    policies["oracle"] = an.choose_oracle(test, cfg)

    # Adaptive policies: warm start from the frozen router, keep learning on the
    # validation stream, then run over the test split once (predict, then update).
    adaptive: dict[str, list[dict]] = {"bandit": [], "linucb": []}
    for name in adaptive:
        for seed in range(seeds):
            start_arms = _arms_after(val, name, cfg, arms, lat, seed) if len(val) else arms
            run = an.replay(test, an.make_stream(test, seed=seed), name, cfg, arms=start_arms, latency0=lat, seed=seed)
            choices = np.zeros(len(test), dtype=int)
            choices[run.rows] = run.choices
            adaptive[name].append({"choices": choices})
        policies[name] = adaptive[name][0]["choices"]

    rows = {}
    for name, choices in policies.items():
        row = an.summarise(test, choices, cfg)
        row.update(an.compare_to_baseline(test, choices, strong, n_boot))
        if name in adaptive:
            per_seed = [an.summarise(test, r["choices"], cfg) for r in adaptive[name]]
            for key in ("quality", "cost_usd", "reward", "regret"):
                row[f"{key}_seed_sd"] = float(np.std([s[key] for s in per_seed]))
                row[key] = float(np.mean([s[key] for s in per_seed]))
        row["meets_target"] = bool(row["cost_saving"] >= TARGET_SAVING and row["quality_diff_ci"][0] > QUALITY_MARGIN)
        rows[name] = row
    for name in ("frozen-ridge", "bandit"):
        rows[f"random@cost-of-{name}"] = an.random_at_matched_cost(test, rows[name]["cost_usd"], cfg)

    R = an.reward_matrix(test, cfg)
    oracle_share = {m: float((R.argmax(axis=1) == i).mean()) for i, m in enumerate(test.models)}
    return {
        "n_train": len(train), "n_validation": len(val), "n_test": len(test),
        "documents_test": int(len(np.unique(test.doc_ids))), "baseline": strong,
        "policies": rows, "oracle_share": oracle_share,
    }


def _arms_after(val, name, cfg, arms, lat, seed):
    """Arm state after learning on the validation stream."""
    gamma = cfg.linucb_gamma if name == "linucb" else 1.0
    learned = arms.copy()
    run = an.replay(val, an.make_stream(val, seed=seed), name, cfg, arms=arms, latency0=lat, seed=seed)
    targets = an.learner_targets(val, cfg)
    for step, row in enumerate(run.rows):
        a = int(run.choices[step])
        learned.arm(val.models[a]).update(val.X[row], float(targets[row, a]), gamma)
    learned.n_scored = len(run.rows)
    return learned


STREAM_POLICIES = ("rules", "frozen", "bandit", "linucb", "bandit-cold", "linucb-cold")


def stream_experiments(table, cfg, seeds: int, epochs: int) -> dict:
    train, test = table.split("train"), table.split("test")
    arms, lat = an.fit_arms(train, cfg), an.mean_latency(train)
    local = test.tier_model("local") or test.models[0]
    cheap = test.tier_model("cheap") or test.models[min(1, len(test.models) - 1)]
    scenarios = {
        "stationary": ("shuffle", None),
        "task_shift": ("task_shift", None),
        "latency_drift": ("shuffle", an.Drift("latency", local, factor=4.0)),
        "quality_drop": ("shuffle", an.Drift("quality", cheap, factor=0.5)),
    }
    out = {}
    for label, (order, drift) in scenarios.items():
        out[label] = {"change": None if drift is None else f"{drift.kind} of {drift.model} x{drift.factor} at 50%"}
        for policy in STREAM_POLICIES:
            # "-cold" variants start the same learner from empty weights instead of the
            # frozen router: the gap shows what offline pre-training is worth.
            base, start = (policy[: -len("-cold")], None) if policy.endswith("-cold") else (policy, arms)
            after, first, total, regret = [], [], [], []
            for seed in range(seeds):
                stream = an.make_stream(test, order=order, epochs=epochs, seed=seed)
                run = an.replay(test, stream, base, cfg, arms=start, latency0=lat, drift=drift, seed=seed)
                after.append(run.window_mean(0.5, 1.0))
                first.append(run.window_mean(0.0, 0.125))
                total.append(float(run.rewards.mean()))
                regret.append(float(run.regret[-1]))
            out[label][policy] = {
                "reward_second_half": float(np.mean(after)), "reward_second_half_sd": float(np.std(after)),
                "reward_first_eighth": float(np.mean(first)),
                "reward_overall": float(np.mean(total)), "cumulative_regret": float(np.mean(regret)),
            }
    return out


def sensitivity(table, cfg) -> dict:
    train, test = table.split("train"), table.split("test")
    strong = test.tier_model("strong") or test.models[-1]
    lat = an.mean_latency(train)
    out = {}
    for q, c, l in [(0.5, 0.3, 0.2), (0.6, 0.3, 0.1), (0.7, 0.2, 0.1), (0.4, 0.4, 0.2), (0.8, 0.1, 0.1)]:
        alt = cfg.model_copy(update={"weights": RewardWeights(quality=q, cost=c, latency=l)})
        choices = an.choose_frozen(test, an.fit_arms(train, alt), alt, lat)
        cmp = an.compare_to_baseline(test, choices, strong, n_boot=500)
        out[f"{q}/{c}/{l}"] = {
            "cost_saving": cmp["cost_saving"], "quality_diff": cmp["quality_diff"],
            "quality_diff_ci": cmp["quality_diff_ci"], "strong_share": an.summarise(test, choices, alt)["share"][strong],
        }
    return out


def ips_check(table, cfg) -> dict:
    """Sanity check of the logged propensities: estimate the frozen router's value
    from the bandit's logs and compare with its true value from the full table."""
    train, test = table.split("train"), table.split("test")
    arms, lat = an.fit_arms(train, cfg), an.mean_latency(train)
    stream = an.make_stream(test, epochs=8, seed=0)
    logs = an.replay(test, stream, "bandit", cfg.model_copy(update={"eps_start": 0.2, "eps_end": 0.2,
                     "update_batch_size": 10**9}), arms=arms, latency0=lat, seed=0)
    target = an.choose_frozen(test, arms, cfg, lat)[stream]
    estimate = an.ips_value(logs.rewards, logs.propensities, logs.choices, target)
    truth = float(an.reward_matrix(test, cfg)[stream, target].mean())
    return {**estimate, "true_value": truth}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--outcomes", default=_common.data_path("outcomes.jsonl"))
    parser.add_argument("--ratings", default=None, help="data/ratings.json from scripts/ratings.py import")
    parser.add_argument("--policy-json", default=None, help="saved policy (GET /api/policy) to take reward settings from")
    parser.add_argument("--judgements", default=None, help="data/judgements.jsonl: quality = judge correctness")
    parser.add_argument("--judge-model", default=None, help="only use grades from this judge model")
    parser.add_argument("--seeds", type=int, default=3)
    parser.add_argument("--epochs", type=int, default=8, help="passes over the test split in stream experiments")
    parser.add_argument("--bootstrap", type=int, default=2000)
    parser.add_argument("--out", default=_common.data_path("evaluation_report.json"))
    args = parser.parse_args()

    ratings = None
    if args.ratings:
        with open(args.ratings, encoding="utf-8") as fh:
            ratings = {tuple(key.split("|", 1)): value for key, value in json.load(fh).items()}
    judgements = load_judgements(args.judgements, args.judge_model) if args.judgements else None
    table = an.load_outcomes(args.outcomes, ratings, judgements)
    print("Quality: " + ("judge correctness" if judgements is not None else "word overlap")
          + (" + blinded human ratings (0.7)" if ratings else ""))
    with open(args.outcomes, encoding="utf-8") as fh:
        synthetic = bool(json.loads(fh.readline()).get("synthetic"))
    if args.policy_json:
        with open(args.policy_json, encoding="utf-8") as fh:
            cfg = PolicyConfig.model_validate(json.load(fh))
    else:
        cfg = SYNTHETIC_CFG if synthetic else PolicyConfig()

    if synthetic:
        print("=" * 78 + "\nSYNTHETIC DATA: invented numbers for checking the code. NOT RESULTS.\n" + "=" * 78)
    static = static_test(table, cfg, args.seeds, args.bootstrap)
    w = cfg.weights
    print(f"Reward: {w.quality} quality + {w.cost} cost + {w.latency} latency, "
          f"C_ref ${cfg.c_ref_usd}, L_ref {cfg.l_ref_s}s, mode {cfg.reward_mode}")
    print(f"Requests: train {static['n_train']}, validation {static['n_validation']}, test {static['n_test']} "
          f"({static['documents_test']} documents); {table.dropped} incomplete requests dropped")
    print(f"\nRQ1  static test split, baseline = {static['baseline']}")
    print(f"{'policy':26s} {'quality':>7s} {'cost $':>9s} {'saving':>7s} {'dQ vs strong [95% CI]':>26s} "
          f"{'p95 s':>6s} {'reward':>7s} {'regret':>7s}  target")
    for name, r in static["policies"].items():
        if name.startswith("random@"):
            print(f"{name:26s} {r['quality']:7.3f} {r['cost_usd']:9.5f} {'':>7s} {'':>26s} {'':>6s} {r['reward']:7.3f}")
            continue
        lo, hi = r["quality_diff_ci"]
        print(f"{name:26s} {r['quality']:7.3f} {r['cost_usd']:9.5f} {pct(r['cost_saving']):>7s} "
              f"{r['quality_diff']:+8.3f} [{lo:+.3f}, {hi:+.3f}] {r['latency_p95_s']:6.2f} {r['reward']:7.3f} "
              f"{r['regret']:7.3f}  {'MET' if r['meets_target'] else 'not met'}")
    print(f"Target: saving >= {TARGET_SAVING:.0%} and lower CI bound of dQ > {QUALITY_MARGIN}")
    share = static["oracle_share"]
    print("Share of test requests on which each model is reward-optimal: "
          + ", ".join(f"{m} {pct(v).strip()}" for m, v in share.items()))
    never = [m for m, v in share.items() if v < 0.02]
    if never:
        print(f"WARNING: {never} are almost never reward-optimal. Check C_ref and the reward weights: with "
              "these settings no router can gain anything by using them.")

    streams = stream_experiments(table, cfg, args.seeds, args.epochs)
    print(f"\nRQ2  mean reward after the change (second half of the stream), {args.seeds} seeds")
    print(f"{'scenario':15s} " + " ".join(f"{p:>11s}" for p in STREAM_POLICIES) + "   change")
    for label, r in streams.items():
        print(f"{label:15s} " + " ".join(f"{r[p]['reward_second_half']:11.3f}" for p in STREAM_POLICIES)
              + f"   {r['change'] or 'none'}")
    print("\nCold vs warm start: mean reward over the first eighth of the stream (stationary), "
          "and cumulative regret over the whole stream")
    st = streams["stationary"]
    for name in ("bandit", "linucb"):
        warm, cold = st[name], st[f"{name}-cold"]
        print(f"  {name:7s} warm {warm['reward_first_eighth']:.3f} (regret {warm['cumulative_regret']:6.1f})   "
              f"cold {cold['reward_first_eighth']:.3f} (regret {cold['cumulative_regret']:6.1f})")

    sens = sensitivity(table, cfg)
    print("\nWeight sensitivity (frozen router; quality/cost/latency weights)")
    for label, r in sens.items():
        print(f"  {label:12s} saving {pct(r['cost_saving'])}, dQ {r['quality_diff']:+.3f}, strong share {pct(r['strong_share'])}")

    ips = ips_check(table, cfg)
    print(f"\nIPS check: frozen router value from bandit logs {ips['snips']:.3f} (true {ips['true_value']:.3f}, "
          f"effective sample size {ips['effective_sample_size']:.0f})")

    report = {"synthetic": synthetic, "policy": cfg.model_dump(), "static": static, "streams": streams,
              "sensitivity": sens, "ips_check": ips, "target": {"saving": TARGET_SAVING, "quality_margin": QUALITY_MARGIN}}
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)
    print(f"\nReport written to {args.out}")


if __name__ == "__main__":
    main()
