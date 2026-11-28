"""Router v2 Phase 2 in one command (the GPU server, or any machine with Ollama).

    python scripts/run_router_v2_pipeline.py                 # all stages, resumes where it stopped
    python scripts/run_router_v2_pipeline.py --stages judge train snapshot

Same stages as kaggle/router_v2_training.ipynb: data, collect_r1, collect_r2, judge,
train, snapshot. Finished stages are recorded in data/router_v2_stages_done.txt and
skipped next time; collection and judging resume where they stopped, so the command
can simply be run again after an interruption.

Run it in a SEPARATE checkout with its own database (see SETUP.md §5b): the data stage
writes data/workload.jsonl, which must not overwrite the baseline's files.
Environment it expects: SMARTROUTE_EMBEDDINGS_ENABLED=true, SMARTROUTE_SEED_MOCK_MODELS=false,
the ML privacy detectors off (all models are local; they would only take GPU memory),
and Ollama running.
"""

import argparse
import os
import subprocess
import sys
import time

import _common

STAGES = ["data", "collect_r1", "collect_r2", "judge", "train", "snapshot"]
ROUNDS = {
    "r1": {"local": "gpt-oss:20b", "cheap": "qwen3.5:9b", "strong": "phi4:14b"},
    "r2": {"local": "llama3.2:3b"},
}
JUDGES = {"gemma4:26b": 1.0, "mistral-small:24b": 0.3}  # judge -> share of answers it grades (agreement sample)
GENERAL = {"mmlu": 80, "arc": 40, "gsm8k": 80, "open": 60}
SCRIPTS = os.path.join(_common.BACKEND_DIR, "scripts")
DONE_FILE = _common.data_path("router_v2_stages_done.txt")


def run(script: str, *args: str) -> int:
    cmd = [sys.executable, os.path.join(SCRIPTS, script), *args]
    print("$", " ".join(cmd[1:]), flush=True)
    return subprocess.run(cmd, cwd=_common.BACKEND_DIR).returncode


def pull(tag: str) -> None:
    print(f"$ ollama pull {tag}", flush=True)
    subprocess.run(["ollama", "pull", tag], check=True)


def stage_data(args) -> bool:
    if not os.path.exists(_common.data_path("workload.jsonl")):
        if run("build_workload.py", "--papers", str(args.papers)):
            return False
    if not os.path.exists(_common.data_path("general.jsonl")):
        if run("build_general_set.py", *sum(([f"--{k}", str(v)] for k, v in GENERAL.items()), [])):
            return False
    return True


def stage_collect(name: str, args) -> bool:
    tiers = ROUNDS[name]
    for tag in tiers.values():
        pull(tag)
    if run("set_tiers.py", *sum(([f"--{t}", tag] for t, tag in tiers.items()), [])):
        return False
    out = _common.data_path(f"outcomes_{name}.jsonl")
    for workload in ("workload.jsonl", "general.jsonl"):
        code = run("collect_outcomes.py", "--workload", _common.data_path(workload), "--models", *tiers,
                   "--by-model", "--budget-usd", "1000000", "--out", out)
        if code != 0:
            return False
    return True


def stage_judge(args) -> bool:
    for judge, share in JUDGES.items():
        pull(judge)
        for name in ROUNDS:
            code = run("judge_outcomes.py", "--judge", judge, "--outcomes", _common.data_path(f"outcomes_{name}.jsonl"),
                       "--workload", _common.data_path("workload.jsonl"), _common.data_path("general.jsonl"),
                       "--out", _common.data_path(f"judgements_{name}.jsonl"), "--skip-auto", "--sample", str(share))
            if code != 0:
                return False
        subprocess.run(["ollama", "stop", judge])
    return True


def stage_train(args) -> bool:
    runs = sum((["--run", _common.data_path(f"outcomes_{n}.jsonl"), _common.data_path(f"judgements_{n}.jsonl")]
                for n in ROUNDS), [])
    workloads = [_common.data_path("workload.jsonl"), _common.data_path("general.jsonl")]
    if run("train_router_v2.py", *runs, "--workload", *workloads, "--judges", *JUDGES.keys()):
        return False
    return run("build_calibration_bank.py", "--workload", *workloads) == 0


def stage_snapshot(args) -> bool:
    return run("snapshot_results.py", "--name", "router_v2_training", "--include-raw",
               "--note", args.note) == 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--stages", nargs="+", default=STAGES, choices=STAGES)
    parser.add_argument("--papers", type=int, default=120)
    parser.add_argument("--note", default="Router v2 data collection and training on the GPU server")
    args = parser.parse_args()
    if os.environ.get("SMARTROUTE_EMBEDDINGS_ENABLED", "").lower() != "true":
        sys.exit("Set SMARTROUTE_EMBEDDINGS_ENABLED=true (Router v2 uses the same embedding features as the baseline).")

    done = set(open(DONE_FILE).read().split()) if os.path.exists(DONE_FILE) else set()
    fns = {"data": stage_data, "collect_r1": lambda a: stage_collect("r1", a),
           "collect_r2": lambda a: stage_collect("r2", a), "judge": stage_judge, "train": stage_train,
           "snapshot": stage_snapshot}
    start = time.time()
    for stage in args.stages:
        if stage in done:
            print(f"[{stage}] already done")
            continue
        print(f"\n===== {stage} ({(time.time() - start) / 3600:.1f} h elapsed) =====", flush=True)
        if not fns[stage](args):
            print(f"[{stage}] did not finish; run the command again to continue.")
            break
        done.add(stage)
        with open(DONE_FILE, "w") as fh:
            fh.write("\n".join(s for s in STAGES if s in done))
        print(f"[{stage}] done")
    print("\nstages done:", [s for s in STAGES if s in done])
    print("remaining:  ", [s for s in STAGES if s not in done])


if __name__ == "__main__":
    main()
