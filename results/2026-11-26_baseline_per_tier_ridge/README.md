# Baseline: one ridge model per tier (26 November 2026)

This is the reference point for every later change to the router. It records the router as it was trained and evaluated in the first GPU-server run, before query difficulty and model ability were separated.

## Code and weights

| Item | Value |
|---|---|
| Code that produced the results | commit `b564724` ("Server run: local model tiers, correctness judge, trained frozen router"), tag `baseline-per-tier-ridge` |
| Router form | one ridge regression per tier, `A = λI + Σxxᵀ`, `θ = A⁻¹b`, λ = 1; predicts answer quality from 27 features (5 numeric, 2 flags, 3 task, 1 constant, 16 PCA dimensions of the all-MiniLM-L6-v2 embedding); feature version `a38136b668fa` |
| Active weights | `backend/artifacts/frozen_router_v3.json`: quality = correctness graded by `gemma4:26b` (checklist rubric v3), trained on 345 requests of the train split |
| Comparison weights | v2: same requests, quality = word overlap. v1: 353 requests, word overlap, counted context-window exclusions as failures (superseded) |
| Online learners | epsilon-greedy (ε 0.10 → 0.02 over 1,000 decisions) and LinUCB (α = 0.5, γ = 0.995, budget pacer), both warm-started from frozen v3 |
| Reward | R = 0.5·Q + 0.3·c + 0.2·l, split mode (quality learned; cost and latency calculated); C_ref = $0.0075 (median strong-tier request cost in a 20-request pilot), L_ref = 10 s |

Weight fingerprints (SHA-256 of the files in the repository; on 27 November a `tiers` map was added to each file, and the weights themselves are unchanged):

| File | SHA-256 |
|---|---|
| `features.json` | `f1536d47ca22fe9503917807160e2c10ff0231221d11d07e1266864fc6ff644d` |
| `frozen_router_v1.json` | `e1e9a51f8acecda6a46622ea3b9f5955b2b9764ad7a4fad723caaf47ef0fafcb` |
| `frozen_router_v2.json` | `02fa43fd481b9e4367c989aed6ea4fe0104dbbc2d0c9e42e2b8249649f12bd18` |
| `frozen_router_v3.json` | `72c502374b5e7e29eb439d2b671557b6e1102ee6a2b1178d5fe4a62f95b02fba` |

## Setup

| | |
|---|---|
| Machine | GPU server: Windows 11, NVIDIA RTX 4000 Ada (20 GB), 32 GB RAM, Python 3.11, PyTorch 2.14 (CUDA 13.0), SQLite |
| Local tier | `gpt-oss:20b` (Ollama, reasoning "low", 16k context): measured latency, no cost |
| Cheap tier | `qwen3.5:9b` (Ollama, 16k context), standing in for a cloud API: **simulated** price $0.10 / $0.50 per million tokens and **simulated** latency 0.5 s + input/20k + output/150 tokens per second |
| Strong tier | `qwen3.6:27b` (Ollama, 8k context), standing in for a cloud API: **simulated** price $4 / $20 per million tokens and **simulated** latency 1.2 s + input/8k + output/60 tokens per second |
| Workload | QASPER, 588 requests over 120 papers, split 60/20/20 by paper; the test split has 116 requests |
| Outcomes | 1,764 answers (588 × 3, collected `--by-model`); 13 full-paper requests did not fit the strong tier's 8k context and were left out of training |
| Quality | correctness graded by `gemma4:26b` (a different model family from all graded models, blind to the model name, temperature 0); 94% identical grades when re-graded |
| Privacy detectors | regex with checksums + Presidio (spaCy `en_core_web_lg`) + GLiNER-PII on the GPU |

## Results

### Test split (116 requests, judge correctness)

| Policy | Quality | Cost $/request | Saving vs strong | Reward |
|---|---|---|---|---|
| Only strong (Qwen3.6-27B) | 0.644 | 0.00988 | 0% | 0.473 |
| Only cheap (Qwen3.5-9B) | 0.647 | 0.00025 | 97.5% | 0.784 |
| Only local (gpt-oss-20b) | 0.666 | 0 | 100% | 0.774 |
| **Frozen ridge (v3)** | 0.653 | 0.00020 | 98.0% | 0.784 |
| LinUCB | 0.641 | 0.00023 | 97.6% | 0.780 |
| Oracle (best model per request) | 0.718 | 0.00025 | 97.4% | 0.814 |

### Adaptation (stream experiments in `evaluate.py`, several passes over the test split)

- When the cheap tier's quality halves partway through the stream, the reward is: LinUCB **0.735**, epsilon-greedy 0.694, frozen 0.625.
- Warm start compared with cold start:

| Learner | Reward in the first eighth of the stream (warm / cold) | Cumulative regret (warm / cold) |
|---|---|---|
| LinUCB | 0.780 / 0.738 | 26.7 / 39.9 |
| Epsilon-greedy | 0.768 / 0.772 | 32.9 / 30.7 |

### Privacy suite (200 cases)

| | Regex only (laptop) | Presidio + GLiNER (server) |
|---|---|---|
| Unauthorised cloud dispatches | 0 / 150 | **0 / 150** |
| Person names detected | 0 / 10 | 10 / 10 |
| Detector recall / precision | 0.889 / 0.964 | 1.000 / 0.865 |
| Harmless requests over-blocked | 3 / 50 | 14 / 50 |

The laptop's regex-only report is stored here as [`privacy_report_laptop_regex.json`](privacy_report_laptop_regex.json).

Found afterwards on Kaggle (27 November), with the same detectors and the baseline scanner: GLiNER labels everyday greetings as person names, so a chat that says only "hello" counted as confidential and could not go to a cloud model.

| Text | Presidio | GLiNER |
|---|---|---|
| `hello` | none | PERSON 0.76 |
| `hi` | none | PERSON 0.90 |
| `hello how are you` | none | PERSON 0.62 |
| `My name is Aman Malik` | PERSON 0.85 | PERSON 0.96 |
| `aman malik called me today` | PERSON 0.85 | PERSON 1.00 |

A filter for greetings and forms of address was added on 27 November (commit `772fd05`); this table is the "before".

## What the baseline shows, and its limits

1. **The three models are about equally correct on this workload** (judge means 0.70 / 0.71 / 0.70 over all answers). The strong stand-in buys no quality, so every router learns to avoid it. The ≥ 20% saving target is met, but always using the cheap model meets it too.
2. **The router does not beat the best single model on a stable workload.** The oracle shows +0.07 quality of headroom, but the 27 features do not predict which model is right on a given request.
3. **Routing pays off under change:** LinUCB holds its reward when a model's quality drops; the frozen router does not.
4. **The metric matters:** with word overlap the local model looked significantly worse than the strong one (−0.047, confidence interval excluding zero); with the judge it is the most accurate.
5. **The weights belong to these three models.** Each tier's ridge model mixes how hard a query is with how good that tier's model is, so the weights do not transfer to a model of different strength. A new model in a tier inherits the old model's predicted quality. Because the three models here were about equally strong, the data also says little about query difficulty. This is the motivation for the next change: learn query difficulty once from models of different strength, describe each model by a few ability numbers, and calibrate a new model with a small set of graded questions instead of retraining.
6. **Cost and latency of the cheap and strong tiers are simulated.** Retrieval looks like the common bottleneck: when BM25 misses the evidence, no model can answer (failure-injection items score 0.57–0.61 for all three).

## Raw files

The evaluation reports, `policy.json`, the server privacy report and the per-request files are on the GPU server in `backend/data/`, which is not in git. To add them here, run on the server:

```bash
cd backend
git pull
python scripts/snapshot_results.py --name baseline_per_tier_ridge --date 2026-11-26 --include-raw \
    --note "Baseline: per-tier ridge, frozen v3, local stand-in tiers"
```

That writes into this folder: `evaluation_report_judge.json`, `evaluation_report_wordoverlap.json`, `privacy_report.json` (server, full detectors), `policy.json`, the gzip-compressed workload, outcomes and judge grades, and `manifest.json`. Commit them without changing this README. If the server's learner states have changed since 26 November, the manifest records that; the weight files above remain the reference.
