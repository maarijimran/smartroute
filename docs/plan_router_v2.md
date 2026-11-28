# Router v2: query difficulty and model ability

Status: approved 28 November 2026; Phase 1 in progress. Baseline for comparison: [`results/2026-11-26_baseline_per_tier_ridge`](../results/2026-11-26_baseline_per_tier_ridge/README.md).

## Why

The baseline router keeps one ridge model per tier. Each one mixes two facts, how hard a request is and how good that tier's model is, so its weights belong to the three models it was trained on. When a tier's model changes, the router assumes the new model is as good as the old one. A weak local model would keep getting hard questions because it is free; a strong one would be used only by luck. Retraining for every model change costs time and money.

## Idea

Predict answer quality from two separate parts:

    predicted quality(x, m) = sigmoid( a_m · s(x) + b_m − d(x) )

- **Query side, learned once:** difficulty `d(x)` and a small skill profile `s(x)` (2–3 numbers) from the request's features.
- **Model side, learned per model:** a model card with ability `a_m` and level `b_m` (3–4 numbers), each with an uncertainty.

A new model is **calibrated** with 20–60 automatically scored questions instead of retraining the router. The same idea is published as IRT-Router (ACL 2025), which applies item response theory to LLM routing.

## Weaknesses found in the first draft, and the fixes

| # | Weakness | Fix |
|---|---|---|
| 1 | The baseline features cannot see what makes a document question hard: whether retrieval found the evidence | Retrieval and question-type features (below) |
| 2 | Public datasets (EmbedLLM) are multiple-choice exams, not questions about papers | Train mainly in-domain (QASPER); use EmbedLLM only if an ablation shows it helps |
| 3 | A Gemma judge grading Gemini can favour its own family | Two judges from families not among the graded models; human κ |
| 4 | Calibration that needs a 26B judge does not fit next to the tier models on Kaggle | Calibrate only with automatically scored questions (yes/no, extractive, multiple choice, numeric) |
| 5 | 50 random questions give a noisy card | Pick the most informative questions; stop when the uncertainty is small enough |
| 6 | Live chat is not QASPER | A general-task set (MMLU, GSM8K, MBPP, open chat) in training, calibration and test (E5); out-of-domain check |
| 7 | A weak but free local model can still win hard questions | A quality floor: never route to a model predicted below X for this request |
| 8 | An uncalibrated model has no defined behaviour | Average-model prior with wide uncertainty, an "Uncalibrated" state on the tier card, LinUCB explores |
| 9 | Cards stored per slot are lost when switching back | Cards stored by model identity (provider + model ID) |
| 10 | Replacing the baseline removes the control condition | v2 is added as new policies; the baseline policies stay selectable |
| 11 | 116 test requests give wide confidence intervals | QASPER expanded to about 300 papers (~1,500 requests) |
| 12 | Choices made after seeing test results | `results/PROTOCOL_v2.md` written and frozen before any test run |

## Components

| Component | Design |
|---|---|
| Query features (v2) | The baseline's numeric features and 16 embedding dimensions, plus: top BM25 score, gap between the first and second passage, how many question words appear in the retrieved passages, number of passages, document size, question type (yes/no, numeric, extractive, abstractive). `local_load` is left out: it affects speed, not quality. |
| Query model | Difficulty and 2–3 skills, linear in the standardised features, fitted jointly with the training models' cards (logistic loss on 0–1 quality, L2). Stored as `artifacts/router_v2.json`. |
| Model cards | Ability, level and their covariance, keyed by provider + model ID. Prior = the training models' average card with a floor on its variance. Updated by Bayesian logistic (Laplace) steps from calibration and ratings. |
| Calibration | Questions chosen greedily by expected information; stops when the predicted-quality uncertainty on a reference set is below a threshold, or at 60 questions or the budget cap. Rate limits are retried, interrupted runs resume, and spend is counted against the platform budget. Source `eval`, so it never trains the live learner. |
| Policies | "Calibrated" (frozen: predicted mean) and "Calibrated LinUCB" (mean plus an uncertainty bonus) added alongside the baseline policies. Same utility: 0.5·quality + 0.3·cost + 0.2·speed. |
| Safeguards | Quality floor (Policy setting, default 0.5, tuned on validation); out-of-domain check raises uncertainty for requests unlike the training data. |
| Interface | Each tier card shows Uncalibrated, Calibrating, or Calibrated with n and ±; a Calibrate button; ability per skill. |

## Data

| Set | Content | Used for |
|---|---|---|
| QASPER, expanded | ~300 papers, ~1,500 requests, 60/20/20 by paper | train: query model; validation: calibration bank and tuning; test: final numbers only |
| General-task set | ~600 items from RouterBench and EmbedLLM (MMLU, GSM8K, MBPP, open chat) | coverage of everyday chat, calibration, test E5 |
| Local models (Kaggle) | gpt-oss:20b, qwen3.5:9b, qwen3.6:27b, one weak 1–3B model, one model from a fourth family | the spread of ability needed to learn difficulty |
| EmbedLLM | 112 models × 36,054 questions, right or wrong (Apache-2.0) | optional difficulty pre-training, kept only if the ablation shows a gain |
| Judges | two judges from families not among the graded models, averaged | 0–1 quality for training and evaluation |
| Human ratings | the 108-answer blinded sheet, extended with v2 answers | judge–human agreement |

Kaggle runs all heavy work: collecting answers, judging, training, experiments. The laptop stays code-only.

## Strong and cloud tiers on Kaggle

The strong and cloud tiers can be models running on Kaggle, registered with simulated cloud prices and latency, as on the server. The experiments need a real spread of ability, not a real network. One real cloud run on the Gemini free tier checks the adapters and real latency.

## Experiments (pre-registered in `results/PROTOCOL_v2.md`)

| Exp. | Question | Compared |
|---|---|---|
| E1 | Same models as the baseline: is v2 at least as good? | baseline frozen v3, v2, single models, oracle |
| E2 | Model swap: weak local; strong local; strong tier replaced | inherited weights, cold start, v2 calibrated, full retrain |
| E3 | How many calibration questions are enough? | leave-one-model-out, n = 10 … 100 |
| E4 | Quality drop during use | baseline LinUCB vs v2 LinUCB |
| E5 | Everyday chat (out of domain) | routing quality on the general-task test set |
| Ablations | What helps? | without retrieval features; without EmbedLLM; difficulty only (no skills) |
| Judges | Are the grades trustworthy? | judge–judge agreement, judge–human κ |

Every run is saved with `scripts/snapshot_results.py` in its own `results/` folder.

## Limits that remain (reported, not hidden)

- Some questions are hard to predict before answering; the oracle gap is reported.
- A judge is still a model; agreement with a second judge and with humans is reported.
- Public benchmark questions may be in the models' training data, which can make abilities look slightly high; calibration uses mostly QASPER.
- Stand-in cloud tiers have simulated cost and latency.
- One main domain (research papers), checked against the general-task set.

## Phases

| Phase | Work | Where | Priority |
|---|---|---|---|
| 1 | v2 features, query model, model cards, information-based calibration, tests | laptop | must |
| 2 | Expanded QASPER, general-task set, two more local models, two judges, train the query model | Kaggle | must |
| 3 | v2 policies in the pipeline, calibration runner, Calibrate button, quality floor, out-of-domain check | laptop | must |
| 4 | Write and freeze `PROTOCOL_v2.md` | team | must, before any test run |
| 5 | E1–E3, then E4, E5 and the ablations | Kaggle | E1–E3 must |
| 6 | EmbedLLM pre-training, more human ratings | Kaggle | optional |
