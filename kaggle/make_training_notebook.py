"""Writes kaggle/router_v2_training.ipynb. Edit this file, then run: python kaggle/make_training_notebook.py"""
import json
import os

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "router_v2_training.ipynb")
cells = []


def md(text):
    cells.append({"cell_type": "markdown", "metadata": {}, "source": text.strip("\n").splitlines(keepends=True)})


def code(text):
    cells.append({"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [],
                  "source": text.strip("\n").splitlines(keepends=True)})


md("""
# SmartRoute Router v2: data collection and training (Kaggle)

Phase 2 of `docs/plan_router_v2.md`. Collects answers from four local models of different
strength, grades the free-form answers with two judges, trains Router v2 and builds the
calibration bank. The work takes several sessions, so it runs in **stages**: every run
continues where the last one stopped and saves its state in the notebook output.

**Each run**
1. Settings: Accelerator **GPU T4 ×2**, Internet **On**. Secret `GITHUB_TOKEN` attached (as for the backend notebook).
2. From the second run on: *Add Input → Your Work →* this notebook's previous version, so its `state/` is restored.
3. **Save Version → Save & Run All (Commit)**. It runs in the background for up to ~11 hours and saves `/kaggle/working`.
4. Read the last cell's log: it says which stages are done. Repeat until `train` and `snapshot` are done.

**Outputs** (in the final version's output): `state/backend/artifacts/router_v2.json`,
`state/backend/artifacts/calibration_bank.json`, `state/backend/data/router_v2_training_report.json`
and a `results/` snapshot. Download those and give them to Claude to commit.

Rough GPU time on T4 ×2: collection ~15 h, judging ~4 h, training < 1 h: about two runs.
""")

code(r'''
# 1. Configuration: change only this cell
STAGES = ["data", "collect_r1", "collect_r2", "judge", "train", "snapshot"]  # run in this order, done stages are skipped
SESSION_MINUTES = 650            # stop starting new work after this (a commit run may last 12 h)
PAPERS = 120                     # QASPER papers (60/20/20 by paper), same size as the baseline
GENERAL = dict(mmlu=80, arc=40, gsm8k=80, open=60)
ROUNDS = {                       # a tier holds one model at a time, so models are collected in rounds
    "r1": {"local": "gpt-oss:20b", "cheap": "qwen3.5:9b", "strong": "phi4:14b"},
    "r2": {"local": "llama3.2:3b"},
}
JUDGES = {"gemma4:26b": 1.0, "mistral-small:24b": 0.3}   # judge -> share it grades; families not among the graded models
''')

code(r'''
# 2. Secrets, settings and code
import os, subprocess, time, glob, shutil, json
from kaggle_secrets import UserSecretsClient

START = time.time()
GITHUB_TOKEN = UserSecretsClient().get_secret("GITHUB_TOKEN")
WORK = "/kaggle/working"
REPO = f"{WORK}/smartroute"
BACKEND = f"{REPO}/backend"
os.environ.update({
    "SMARTROUTE_ENV": "development",
    "SMARTROUTE_DATABASE_URL": f"sqlite:///{WORK}/state/smartroute_train.db",
    "SMARTROUTE_SEED_MOCK_MODELS": "false",
    "SMARTROUTE_OLLAMA_BASE_URL": "http://127.0.0.1:11434",
    # All models here are local and the data is public, so the privacy gate cannot change any
    # routing; the ML detectors stay off to leave GPU memory to the models.
    "SMARTROUTE_PII_PRESIDIO": "false", "SMARTROUTE_PII_GLINER": "false",
    "SMARTROUTE_EMBEDDINGS_ENABLED": "true", "SMARTROUTE_OCR_BACKEND": "off",
    "SMARTROUTE_REQUEST_TIMEOUT_S": "300",
    "HF_HOME": "/tmp/hf-cache", "OLLAMA_MODELS": "/tmp/ollama-models", "OLLAMA_KEEP_ALIVE": "30m",
})
os.makedirs(f"{WORK}/state", exist_ok=True)
if not os.path.isdir(REPO):
    url = f"https://x-access-token:{GITHUB_TOKEN}@github.com/maarijimran/smartroute.git"
    r = subprocess.run(["git", "clone", "--depth", "1", url, REPO], capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(r.stderr.replace(GITHUB_TOKEN, "***"))
    subprocess.run(["git", "-C", REPO, "remote", "set-url", "origin", "https://github.com/maarijimran/smartroute.git"])
print(subprocess.run(["git", "-C", REPO, "log", "--oneline", "-1"], capture_output=True, text=True).stdout)
!pip install -q -r {BACKEND}/requirements.txt -r {BACKEND}/requirements-ml.txt
!python -m spacy download en_core_web_lg > /dev/null
''')

code(r'''
# 3. Restore the previous run's state (attach the previous version's output as input)
prev = sorted(glob.glob("/kaggle/input/*/state"))
if prev:
    src = prev[-1]
    for name in ("smartroute_train.db",):
        if os.path.exists(f"{src}/{name}") and not os.path.exists(f"{WORK}/state/{name}"):
            shutil.copy(f"{src}/{name}", f"{WORK}/state/{name}")
    for sub in ("backend/data", "backend/artifacts"):
        if os.path.isdir(f"{src}/{sub}"):
            shutil.copytree(f"{src}/{sub}", f"{REPO}/{sub}", dirs_exist_ok=True)
    print("restored from", src)
    print(open(f"{src}/stages_done.txt").read() if os.path.exists(f"{src}/stages_done.txt") else "")
else:
    print("first run: nothing to restore")
DONE_FILE = f"{WORK}/state/stages_done.txt"
done = set(open(f"{prev[-1]}/stages_done.txt").read().split()) if prev and os.path.exists(f"{prev[-1]}/stages_done.txt") else set()
''')

code(r'''
# 4. Ollama
!apt-get -qq update > /dev/null && apt-get -qq install -y zstd pciutils > /dev/null
!curl -fsSL https://ollama.com/install.sh | sh > /dev/null
import urllib.request
ollama = subprocess.Popen(["ollama", "serve"], stdout=open("/tmp/ollama.log", "w"), stderr=subprocess.STDOUT)
for _ in range(60):
    try:
        urllib.request.urlopen("http://127.0.0.1:11434/api/version", timeout=2); break
    except Exception:
        time.sleep(1)
pulled = set()
def pull(tag):
    if tag not in pulled:
        subprocess.run(["ollama", "pull", tag], check=True, stdout=subprocess.DEVNULL)
        pulled.add(tag)
''')

code(r'''
# 5. Stages
def minutes_left():
    return SESSION_MINUTES - (time.time() - START) / 60

def run(*args):
    """Runs a backend script; returns its exit code (3 = stopped at the time limit)."""
    print("$", " ".join(args), flush=True)
    return subprocess.run(["python", *args], cwd=BACKEND).returncode

def stage_data():
    if not os.path.exists(f"{BACKEND}/data/workload.jsonl"):
        assert run("scripts/build_workload.py", "--papers", str(PAPERS)) == 0
    if not os.path.exists(f"{BACKEND}/data/general.jsonl"):
        assert run("scripts/build_general_set.py", *sum(([f"--{k}", str(v)] for k, v in GENERAL.items()), [])) == 0
    return True

def stage_collect(name):
    tiers = ROUNDS[name]
    for tag in tiers.values():
        pull(tag)
    assert run("scripts/set_tiers.py", *sum(([f"--{t}", tag] for t, tag in tiers.items()), [])) == 0
    out = f"data/outcomes_{name}.jsonl"
    for workload in ("data/workload.jsonl", "data/general.jsonl"):
        code = run("scripts/collect_outcomes.py", "--workload", workload, "--models", *tiers.keys(), "--by-model",
                   "--budget-usd", "1000000", "--out", out, "--max-minutes", str(max(minutes_left(), 1)))
        if code != 0:
            return False  # time limit: continue next run
    return True

def stage_judge():
    for judge, share in JUDGES.items():
        pull(judge)
        for name in ROUNDS:
            run("scripts/judge_outcomes.py", "--judge", judge, "--outcomes", f"data/outcomes_{name}.jsonl",
                "--workload", "data/workload.jsonl", "data/general.jsonl", "--out", f"data/judgements_{name}.jsonl",
                "--skip-auto", "--sample", str(share), "--max-minutes", str(max(minutes_left(), 1)))
            if minutes_left() < 5:
                return False
        subprocess.run(["ollama", "stop", judge])
    return True

def stage_train():
    runs = sum((["--run", f"data/outcomes_{n}.jsonl", f"data/judgements_{n}.jsonl"] for n in ROUNDS), [])
    assert run("scripts/train_router_v2.py", *runs, "--workload", "data/workload.jsonl", "data/general.jsonl",
               "--judges", *JUDGES.keys()) == 0
    assert run("scripts/build_calibration_bank.py", "--workload", "data/workload.jsonl", "data/general.jsonl") == 0
    return True

def stage_snapshot():
    return run("scripts/snapshot_results.py", "--name", "router_v2_training", "--note",
               "Router v2 data collection and training on Kaggle T4x2") == 0

STAGE_FN = {"data": stage_data, "collect_r1": lambda: stage_collect("r1"), "collect_r2": lambda: stage_collect("r2"),
            "judge": stage_judge, "train": stage_train, "snapshot": stage_snapshot}
for stage in STAGES:
    if stage in done:
        print(f"[{stage}] already done"); continue
    if minutes_left() < 20:
        print(f"[{stage}] not started: session time used up"); break
    print(f"\n===== {stage} ({minutes_left():.0f} min left) =====", flush=True)
    if STAGE_FN[stage]():
        done.add(stage)
        print(f"[{stage}] done")
    else:
        print(f"[{stage}] stopped at the time limit; the next run continues it"); break
open(DONE_FILE, "w").write("\n".join(s for s in STAGES if s in done))
''')

code(r'''
# 6. Save state for the next run (and the results)
for sub in ("backend/data", "backend/artifacts"):
    shutil.copytree(f"{REPO}/{sub}", f"{WORK}/state/{sub}", dirs_exist_ok=True)
if os.path.isdir(f"{REPO}/results"):
    shutil.copytree(f"{REPO}/results", f"{WORK}/state/results", dirs_exist_ok=True)
print("stages done:", sorted(done))
print("remaining:", [s for s in STAGES if s not in done])
for f in sorted(glob.glob(f"{WORK}/state/backend/data/outcomes_*.jsonl")):
    print(f, sum(1 for _ in open(f)), "answers")
''')

nb = {"cells": cells, "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
                                   "language_info": {"name": "python"}}, "nbformat": 4, "nbformat_minor": 5}
with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
    json.dump(nb, fh, indent=1, ensure_ascii=False)
print("wrote", OUT, len(cells), "cells")
