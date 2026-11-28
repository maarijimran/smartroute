# SmartRoute: work log and remaining work

Last updated: 27 November 2026 (server session of 26 November; documentation aligned on 27 November). Written for the three team members, including whoever was not in the build session.

## Where things stand

The gateway, both phases of the product (chat interface and router API), role-based access control, the confidential audit log, the web interface and the evaluation scripts are written. On 26 November the first real run happened on the GPU server: real local models, the QASPER workload, 1,764 collected outcomes, a local correctness judge, a trained frozen router and a first evaluation. See "Server session, 26 November" below. Still not run: any cloud API (there are no keys yet), Docker, PostgreSQL, the OCR model (needs Linux for vLLM) and the human ratings.

## Server session, 26 November

### The server is not what SETUP.md assumed

- **Windows 11**, NVIDIA RTX 4000 Ada (20 GB), 32 GB RAM. No Docker, no WSL, no PostgreSQL. The backend runs from `backend/.venv` (Python 3.11, PyTorch 2.14 cu130) with SQLite.
- C: is nearly full, so large files live on D: (`OLLAMA_MODELS=D:\SmartRoute\ollama-models`, `HF_HOME=D:\SmartRoute\hf-cache`).
- OCR weights (`baidu/Unlimited-OCR`) are downloaded, but vLLM does not run on Windows, so `SMARTROUTE_OCR_BACKEND=off` until WSL2 or Docker is set up.

### No cloud keys yet: three local models stand in for the tiers

Registered by `scripts/register_ollama_tiers.py`. All run through Ollama on the GPU.

| Tier | Model | Context | Stand-in for | Price (per M tokens, in/out) | Latency the router sees |
|---|---|---|---|---|---|
| local | gpt-oss:20b (think low) | 16k | the local model | free | measured |
| cheap | qwen3.5:9b (think off) | 16k | a Haiku-class API | **simulated** $0.10 / $0.50 | **simulated**: 0.5 s + in/20k + out/150 tok/s |
| strong | qwen3.6:27b (think off) | 8k (spills to CPU at 16k) | an Opus-class API | **simulated** $4 / $20 | **simulated**: 1.2 s + in/8k + out/60 tok/s |

All three are marked local, so the privacy gate never blocks them. **Declare in the report** that cheap/strong cost and latency are simulated; the measured local latency is kept in `measured_latency_ms`.

### What was run

1. Workload: 588 requests over 120 papers (only 28 unanswerable questions existed in the sample, not 40). Features fitted on the train split (27 dimensions, 16 PCA).
2. Pilot (20 requests) → C_ref = $0.0075 (strong model's median request cost), L_ref = 10 s. Saved in the policy and `backend/data/policy.json`.
3. Outcome collection: 1,764 answers (588 × 3), `--by-model`. Qwen3.6-27B could not take 13 full-paper requests (8k context); those requests are left out of training, not counted as failures.
4. **Local correctness judge** (`app/evaluation/judge.py`, `scripts/judge_outcomes.py`): Gemma 4 26B (gemma4:26b), a different model family from every graded model, blind to the model name, temperature 0. It lists the reference's key points, marks each covered/partly/missing and flags contradictions; the grade is computed from that checklist (all covered 5, ≥75% 4, ≥40% 3, less 2, contradiction 1). Stability: 94% identical grades when re-graded with another seed. A first rubric (v2) was dropped after an audit showed it gave full marks to confident, detailed answers that missed reference points.
5. Frozen router trained on judge correctness: **v3** (active; `backend/artifacts/frozen_router_v3.json`), epsilon-greedy and LinUCB warm-started from it. v2 (word overlap) is kept for comparison; v1 is superseded (it counted context-window exclusions as failures).
6. Evaluation: `data/evaluation_report_judge.json` and `data/evaluation_report_wordoverlap.json`.

### First results (test split, 116 requests, judge correctness)

| Policy | Quality | Cost $/request | Saving vs strong | Reward |
|---|---|---|---|---|
| only Qwen3.6-27B (strong) | 0.644 | 0.00988 | 0% | 0.473 |
| only Qwen3.5-9B (cheap) | 0.647 | 0.00025 | 97.5% | 0.784 |
| only gpt-oss-20b (local) | 0.666 | 0 | 100% | 0.774 |
| frozen ridge | 0.653 | 0.00020 | 98.0% | 0.784 |
| LinUCB | 0.641 | 0.00023 | 97.6% | 0.780 |
| oracle | 0.718 | 0.00025 | 97.4% | 0.814 |

What this says, honestly:

- **The three models are equally correct on this workload** (judge means 0.70 / 0.71 / 0.70 over all answers). The 27B buys nothing, so it is almost never worth its price (reward-optimal on 0.9% of requests) and every router learns to avoid it. The cost-saving target is met, but "always use the cheap model" meets it too.
- **The router does not beat the best single model on a stable workload.** The oracle shows real headroom (+0.07 quality from picking per request), but the 27 features do not predict which model will be right on a given request.
- **Adaptation is where routing pays off:** when the cheap model's quality halves mid-stream, LinUCB keeps a reward of 0.735 and the bandit 0.694, against 0.625 for the frozen router.
- **The metric changed a conclusion:** with word overlap, the local model looked significantly worse than the strong one (−0.047, CI excluding zero); with the correctness judge it is the most accurate of the three. Word overlap was penalising its formatting, not its answers.
- Likely reasons for the flat quality: all models answer from the same BM25 excerpts, so when retrieval misses the evidence no model can answer (failure-injection items score 0.57–0.61 for all three); and a 27B open model is a much weaker "strong tier" than a frontier cloud model would be.

### Cold start vs warm start (stream experiments, `evaluate.py`)

| Learner | Reward, first eighth of the stream (warm / cold) | Cumulative regret (warm / cold) |
|---|---|---|
| LinUCB | 0.780 / 0.738 | 26.7 / 39.9 |
| epsilon-greedy | 0.768 / 0.772 | 32.9 / 30.7 |

Warm-starting from the frozen router clearly helps LinUCB (a third less regret). It makes no difference for epsilon-greedy here, because with three equally correct models a cold greedy learner falls back to the cheapest one, which is already near-optimal. After several passes both reach the same reward.

### Privacy suite with Presidio and GLiNER (200 cases)

| | Regex only (laptop) | Full detectors (server) |
|---|---|---|
| Unauthorized cloud dispatches | 0 / 150 | **0 / 150** |
| Person names detected | 0 / 10 | **10 / 10** |
| Detector recall / precision | | **1.000 / 0.865** |
| Harmless requests over-blocked | 3 / 50 | **14 / 50** |

All 14 over-blocks are "lookalikes": academic text with numbers. GLiNER labels token counts as card numbers, operation bounds as bank accounts, document counts as national IDs and dates as "OTHER". Over-blocking only keeps a request local, which is the safe direction. **Open decision:** let the checksum-validated regex be the only source for card, IBAN, CNIC, phone and email findings, and use the ML detectors only for what regex cannot find (names, addresses). That would remove most over-blocks; it trades away ML recall on unusually formatted identifiers.

### Running the app on the server

- Backend: `cd backend && .venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000` (set `HF_HOME=D:\SmartRoute\hf-cache` first). Frontend: `cd frontend && npm run dev`, with `frontend/.env.local` = `NEXT_PUBLIC_API_URL=http://127.0.0.1:8000`.
- Routing policy: **frozen** (ridge v3). All three tiers are the local Ollama models until cloud keys exist.
- Ollama: `OLLAMA_MODELS=D:\SmartRoute\ollama-models`, `OLLAMA_KEEP_ALIVE=30m`. Only one tier model fits in VRAM next to the backend's detectors, so switching tier reloads a model from D: (30-70 s). A loaded model answers in seconds.
- Human ratings: `backend/data/ratings_sheet.csv` (108 blinded answers) is ready for two raters; `ratings_key.json` must not be shown to them.
- **Trained weights are in git** (`backend/artifacts/`: `features.json` and `frozen_router_v1-3.json`; data stays out). On another machine: pull the three Ollama models, set `SMARTROUTE_EMBEDDINGS_ENABLED=true`, run `scripts/register_ollama_tiers.py --ctx-strong 8192`, `scripts/set_reward_calibration.py --c-ref 0.0075 --l-ref 10`, then `scripts/import_frozen_router.py artifacts/frozen_router_v3.json --warm-start`, and choose Frozen in Settings → Policy.

### Fixed during the session

- **Every request was confidential with the ML detectors on:** GLiNER read "SmartRoute" in the gateway's own system prompt as a person. The gate no longer scans the gateway's fixed prompt (`KIND_SYSTEM`); a caller's system prompt is still scanned. Regression test added.
- **Ordinary questions were declined** ("no excerpts to answer from"): the excerpt rules are now only in the prompt when excerpts are attached (`SYSTEM_PROMPT_GENERAL` / `SYSTEM_PROMPT_WITH_EVIDENCE`). The prompt also tells the model that the privacy controls, not the model, decide where personal data goes, after a local model refused to draft a note containing the user's own CNIC.
- **Privacy suite took 25+ minutes:** it reloaded GLiNER for each of the 200 cases. Now 27 seconds.

GLiNER ran on the CPU (now GPU, `SMARTROUTE_PII_GLINER_DEVICE`); Presidio tried to download a missing spaCy model at runtime and could exit the process (now refused, fails closed); Ollama ignored `think`, so reasoning could consume the output budget; outcome collection reloaded a model on almost every call (`--by-model` with warm-up); `localhost` cost ~2.2 s per request on Windows (now `127.0.0.1`); two tests assumed the laptop. 118 tests pass.

## Results kept for comparison (28 November)

Before the router is changed, the 26 November results are frozen as the **baseline** in [`results/2026-11-26_baseline_per_tier_ridge/`](results/2026-11-26_baseline_per_tier_ridge/README.md): setup, all result tables, weight fingerprints, the laptop privacy report and the Kaggle greeting false positives. The code that produced them is tagged `baseline-per-tier-ridge` (commit `b564724`). The raw files are still only on the server; `scripts/snapshot_results.py` adds them to that folder (see its README). Every later run gets its own folder in `results/`, so improvements can be shown against this baseline.

**Next change planned:** separate query difficulty (learned once, from models of different strength) from model ability (a few numbers per model, fitted from about 50 judge-graded calibration questions), so a tier's model can be replaced without retraining the router.

## Tier slots (27 November)

Asked for: no seeded Claude models; the superadmin alone chooses the provider, model and key for the local, cheap and strong tiers; users cannot add, change or remove keys or models; and when the superadmin changes a tier's model, routing continues from that tier's trained weights instead of starting from scratch.

- **Slots.** `app/core/tiers.py` keeps exactly one registry entry per tier. `PUT /api/tiers/{tier}` (superadmin only) edits that entry in place: provider, model, endpoint, context, prices and key. The entry keeps its name, and the frozen router, epsilon-greedy and LinUCB store their weights under that name, so the new model inherits the tier's weights. Health, latency and the response cache are reset; the change is logged in the policy history with key hints only. Enabling a second model in a tier is refused.
- **Keys.** One encrypted key per tier, set with the tier. Personal keys are no longer read, the `/api/credentials` endpoints are superadmin-only (list and delete), and the "Shared keys" policy switch is gone.
- **Seeds.** Fresh installs get `local-default` (Ollama) and unset `cheap` and `strong` slots. The old disabled `claude-haiku` and `claude-opus` rows are removed at start-up; the server keeps its `sim-cheap` and `sim-strong` slots and their weights.
- **Scripts.** `register_ollama_tiers.py` uses the same tier function. The artifacts now carry a `tiers` map, so `import_frozen_router.py` attaches the weights to whatever the slots are called on a machine. `train_frozen.py` writes that map. `collect_outcomes.py` accepts `local cheap strong` and records each answer's provider model ID.
- **Interface.** Settings → Models shows one card per tier. Settings → API keeps only the SmartRoute keys.
- **Verified on the laptop:** 126 backend tests pass (7 new in `tests/test_tiers.py`), the frontend type-checks and builds, and the Models page was checked in a browser in both themes. Switching the cheap tier from OpenAI to Gemini through the API kept its slot and required the new key. No real provider was called.
- **Caution:** the inherited weights were learned on the stand-in models. They are a starting point, not a measurement of the new model. Collect outcomes for it into a new file and retrain before reporting results for it.

## What was asked for

1. Follow the research guide and build the whole project.
2. Code only on the laptop: no model downloads, no datasets, no model runs. Link everything to download later in SETUP.md.
3. Two phases: a chat interface, then our own API that a developer calls from their backend. (Originally with their own paid cloud keys; since 27 November only the superadmin sets models and keys, see "Tier slots".)
4. Role-based access control. The superadmin decides whether users may send confidential queries to cloud APIs.
5. Log confidential queries so they can be traced.
6. Industry-grade, to run on our own server.

## Decisions taken during the session

| Question | Decision |
|---|---|
| Account structure | Single organisation with three roles: superadmin, admin, user |
| Audit log content | Metadata, detected entity types, a content hash and a masked preview. The query text itself is not stored. |
| Cloud providers at launch | OpenAI-compatible endpoints, Anthropic Claude, Google Gemini, Azure OpenAI |
| Testing on the laptop | Allowed: a project-local virtual environment with light packages, fake models, SQLite |

Defaults chosen without asking, all changeable in the Policy page:

- Confidential content may not go to cloud unless the superadmin permits the user, and a permitted user must still consent on each request.
- Uploaded documents are labelled confidential unless the user declares them public.
- The router learns answer quality and calculates cost and latency ("split" mode, from the research guide). The proposal's original form, learning the whole reward, is available as "full" mode. This is a real change from the proposal and should be declared in the evaluation protocol.
- No cloud model is seeded (the Claude Haiku and Opus seeds were removed on 27 November). The superadmin sets the cheap and strong tiers.

## What was built

### Backend (`backend/app`)

| Part | Files | What it does |
|---|---|---|
| Request pipeline | `core/pipeline.py` | Evidence, confidentiality check, eligibility filter, cache, policy choice, final outbound check, dispatch, bounded retry, logging, learning. Used by chat, the API and the benchmark. |
| Privacy | `core/privacy/scanner.py`, `core/privacy/gate.py` | Regex detectors (CNIC, Pakistani and international phones, email, card with checksum, IBAN with checksum), optional Presidio and GLiNER, union of all, fails closed. Detection and enforcement are separate functions. |
| Routing | `core/routing/` | Rules, frozen router, epsilon-greedy bandit with logged propensities, LinUCB with forgetting and a budget pacer, versioned learner state with rollback and warm start. |
| Providers | `core/providers/` | Ollama, OpenAI-compatible, Azure OpenAI, Anthropic (official SDK), and a mock provider for development. |
| Documents | `core/documents.py` | Local PDF and TXT parsing, chunking, BM25 retrieval. |
| Access control | `deps.py`, `api/auth.py`, `api/policy.py` | Login, roles, per-user confidential permission, policy editing with change history. |
| Phase 1 API | `api/chat.py`, `api/documents.py` | Chat sessions with streaming answers, uploads, ratings. |
| Phase 2 API | `api/openai_compat.py` | `/v1/chat/completions`, `/v1/models`, `/v1/feedback` with SmartRoute API keys. |
| Registry and keys | `api/registry.py` | Model registry, encrypted cloud keys (personal or platform), SmartRoute API keys. |
| Analytics and audit | `api/analytics.py`, `api/policy.py` | Measured cost, latency and local share, a labelled strong-only estimate, the confidential audit log. |
| Retention | `core/retention.py` | Chat and document expiry, metadata and audit retention. |
| Evaluation | `evaluation/`, `scripts/` | Automatic scoring, baselines, oracle, kNN, random at matched cost, bandit replay with controlled drift, clustered bootstrap intervals, inverse propensity check, 200-case privacy suite, blinded rating workflow. |

### Conversation context (added 16 November)

Before this, the full chat history was replayed to the model, but retrieval, task type and difficulty were judged from the latest message alone, and long chats simply lost their oldest turns. Now (`core/context.py`):

| Technique | What it does | Cost |
|---|---|---|
| Follow-up detection | A lexical test: does the message add nothing new, refer back ("it", "the second method"), or start with a connector ("what about")? | Microseconds, no model call |
| History-aware retrieval | A follow-up searches with the previous question's terms (weight 0.6) and the previous answer's main terms (0.3) as well as its own, and keeps the passages the previous answer used in contention | Microseconds |
| Task and difficulty inheritance | "Make it shorter" after a summary is a summary; "Why?" after a hard question is routed as hard | Microseconds |
| Token-budgeted history window | Under 2,000 tokens the history goes verbatim. Above that, the recent exchanges go verbatim and older ones are replaced by a summary, or by the most relevant older exchanges until a summary exists | Microseconds |
| Rolling summary | Written by the local model in the background after each answer, extending the previous summary, so it is ready for the next turn and never slows a reply. Kept in memory only, never in the database | One local model call per long-chat turn, off the request path |
| Router features | Two new features: the size of the history sent and whether the message is a follow-up | None |
| Provider prompt caching | Claude requests cache the conversation prefix, so the next turn re-reads it at a tenth of the input price; cost accounting now prices cached tokens correctly | Saves money |

Privacy: turns that are summarised or left out are still checked by the privacy gate on every request, so content derived from a confidential turn stays confidential. Only a local model may write summaries.

Why not have an LLM rewrite each follow-up into a standalone question? It resolves references better, but it puts a model call in front of every follow-up. Measure the lexical approach first and add rewriting only if the measurement shows it is needed.

Limits: the benchmark workload is single-turn, so the frozen router learns nothing about the two new features; the online bandit learns them from live, rated traffic. The follow-up test is a heuristic and has not been measured on real conversations.

### OCR for photos and scanned PDFs (added 16 November)

**Scope change: tell the supervisor.** The proposal excluded scanned-document OCR and image input. OCR is now included at the team's request.

- **Model and serving.** `baidu/Unlimited-OCR` (3B, MIT licence) runs as its own vLLM container on the GPU server.
- **What is read.** Photos (PNG, JPG, WebP, TIFF, BMP) are read by OCR. PDF pages without a text layer are OCR'd page by page, up to 20 per upload.
- **Privacy.** The recognised text goes through the same privacy gate and document labels as typed text, so a CNIC in a photo keeps the request local. Images are re-encoded before OCR, which strips camera and GPS metadata. In production the gateway refuses an OCR server outside the trusted boundary.
- **Laptop.** A mock OCR, clearly labelled, stands in for the model.
- **Verified so far.** 16 tests cover the clean-up of the model's markup, the locality rule, image handling, the exact request sent to vLLM, scanned PDFs, and the full path from a CNIC photo to a local answer and an audit row. The real model has not been run yet.

### Frontend (`frontend`)

Next.js pages: login, chat (privacy mode switch, document picker, per-message consent, "why this model" details, ratings), documents, keys and API quickstart, analytics, and admin pages for users, the audit log, policy and router, and the model registry.

Restyled on 17 November: short labels, no AI wording, and the mock provider replies "Demo response (model)."

Redesigned later on 17 November as a chat-first layout:
- **Theme:** warm ivory light theme and charcoal dark theme with a terracotta accent. Light / Dark / System is chosen from the account menu or Settings → General.
- **Sidebar:** collapsible, with a toggle button. It holds only New chat, the recent chats (rename and delete from each chat's menu) and the account menu (Settings, theme, Sign out).
- **Chat:** a new chat opens on a greeting with the composer centred. The composer has "+" (upload or attach files), an options menu (Local only, Confidential, Consent, Keep history) and a model picker beside the send button. Answers show copy, rate and details buttons.
- **Settings:** every other page moved under `/settings` (General, Files, API, Analytics, and for admins Users, Audit, Policy, Models). The old addresses redirect.

The jury prototype (`FYP Prototypes/SmartRoute_Prototype.html`), its screenshots and the deck were updated to the same layout and colours.

### Deployment

`docker-compose.yml` (PostgreSQL, Ollama with GPU, the vLLM OCR server, backend, frontend), two Dockerfiles, environment templates. Not built yet: the GPU server runs Windows without Docker (see SETUP.md section 3a for how it runs there).

## How the main requirements are met

- **Superadmin control of confidential queries.** An organisation default plus a per-user override (allow, deny, inherit), both editable only by the superadmin. A master switch turns cloud off for everyone and beats any consent.
- **Tracking.** Every request that carries confidential content writes an audit row before anything is dispatched: user, source (chat or API), why it counted as confidential, the decision and its reason, whether consent was given, the destination model, and whether the content left the server.
- **No silent cloud fallback.** If no permitted model can answer, the request is refused with an explanation. The API returns HTTP 403 with `privacy_policy_block`.
- **Privacy outside the learner.** Models are removed by the eligibility filter before any policy runs, and the outbound check runs again on the exact payload before a cloud call. Exploration and retries pick only from what is left.
- **Organisation keys only.** The superadmin sets one provider key per tier (stored encrypted); users and developers cannot add keys. A SmartRoute key created as local-only can never reach cloud, whatever the request asks.

## What was verified on the laptop (before the server run)

- 108 automated tests passed at the time (126 now).
- The server was started for real and called over HTTP: login, model list, router API with and without a CNIC, streaming, audit log.
- Privacy suite with regex detectors only: 0 enforcement failures in 150 cases that must be blocked; all 80 structured identifiers detected; 3 of 50 harmless lookalikes wrongly blocked.
- The evaluation script runs end to end on synthetic outcomes.
- The web interface type-checks and builds (11 pages).

## Findings worth acting on

1. **Names need the ML detectors.** With regex only, 0 of 10 person-name cases were detected and all 10 would have gone to cloud. *Resolved on the server:* with Presidio and GLiNER, 10 of 10 were detected. The cost is over-blocking (14 of 50 lookalikes), which is now the open detector decision.
2. **C_ref must be calibrated.** With the default $0.002 and a strong model costing about $0.01 per request, the strong model always scores zero on cost and no router ever chooses it. *Resolved for the stand-in tiers:* the pilot set C_ref = $0.0075 and L_ref = 10 s. Recalibrate when real cloud tiers are added.
3. **The quality target constrains the reward weights.** On the synthetic data even the oracle missed the "lower bound above -0.05" target, because the reward itself trades quality for cost. Choose the weights on the validation split so the target is reachable, then freeze them. Still relevant once real cloud tiers exist; with the stand-ins the three models are about equally correct.
4. **Exploration schedule versus dataset size.** The proposal decays epsilon over 1,000 scored decisions, but the workload has 588 requests. The stream experiments in `evaluate.py` make several passes over the test split (`--epochs`, default 8); state this in the protocol.
5. **A CNIC written without dashes at the end of a sentence was missed** by the first version of the regex. The privacy suite caught it and it is fixed. This is the kind of error the suite exists to find, so run it after every detector change.
6. **The quality metric matters.** Word overlap made the local model look significantly worse than the strong one; the correctness judge says it is the most accurate. Use the judge-trained router (v3) and judge-based numbers, and check the judge against the human ratings.

## Not verified yet

Verified on the server since the laptop phase: the Ollama adapter with real models, Presidio, GLiNER, the embedding features, `scripts/build_workload.py` against the real QASPER layout, outcome collection, the judge, frozen training and the evaluation. Still not verified:

- Any cloud API call: Claude, OpenAI-compatible endpoints, Gemini, Azure. These adapters were checked against the installed SDKs' signatures only.
- The OCR model through vLLM (weights downloaded; needs Linux).
- Docker images and `docker-compose.yml`.
- PostgreSQL. Tests and the server both use SQLite.
- The web interface by a person. A headless browser on the laptop clicked through new chat, sending, menus, the sidebar toggle, Settings and redirects; a full manual pass with real models is still needed.
- How far the judge agrees with human raters.

## Remaining work

### On the server (see SETUP.md)

Done on 26 November with local stand-in tiers: models pulled, workload built, features fitted, pilot and calibration, outcomes collected, judge run, frozen router trained, first evaluation. Still open:

1. Decide on the detector over-blocking (see "Privacy suite" above), then rerun the suite.
2. Add cloud keys, correct the prices, send a test message to each model; then collect outcomes for the real cloud tiers and retrain (a frozen router only knows the models it was trained on).
3. Two raters fill `backend/data/ratings_sheet.csv`; `scripts/ratings.py import` it and report how far the judge agrees with them.
4. Try a stronger retrieval step or more evidence per request, since retrieval looks like the bottleneck for every model.
5. Docker, PostgreSQL and OCR need Linux: WSL2 or a Linux server.
6. A click-through of the web interface with real models by a person.

### Still to build

| Item | Priority in the research guide | Note |
|---|---|---|
| Click-through test of the web interface and fixes | Must | First thing to do with a browser |
| Multi-turn evaluation set | Should | Chain the three QASPER questions per paper into conversations to measure follow-up detection and context handling |
| Database migrations (Alembic) | Needed for a real deployment | Tables are created at startup today, so a schema change needs a manual migration |
| NVIDIA complexity classifier as a feature | Could | A keyword and length heuristic is used now |
| Batch API for benchmark generation | Should | Would halve benchmark cost on providers that offer it |
| Local judge model or NLI faithfulness check | Could | Done for correctness: `gemma4:26b` checklist judge (`app/evaluation/judge.py`). A faithfulness check against the excerpts is not built |
| LLMLingua-2 compression, semantic cache | Could | Exact cache and output caps are in place |
| Mask-then-send with consent | Could (stretch) | Not started |
| Shared rate limiter and learner state for several workers | Later | Single worker today |
| HTTPS reverse proxy, backups, monitoring | Deployment | Not configured |

## Open questions for the team

1. Answered: the GPU server runs Windows 11 without Docker or WSL. Docker, PostgreSQL and OCR need WSL2 or a Linux machine. Which one?
2. Partly answered: `gpt-oss:20b` is the local tier for now (the code default is still `llama3.1:8b`). Confirm it as the final local model.
3. Which two cloud models are the cheap and the strong option for the experiments? Until keys exist, `qwen3.5:9b` and `qwen3.6:27b` stand in with simulated prices and latency.
4. Will the server be reached over a domain with HTTPS, or only inside the lab network?
5. Done: the project is in a private GitHub repository. `CLAUDE.md` gives Claude Code the context of the build sessions.
