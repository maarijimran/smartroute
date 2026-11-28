# SmartRoute: context for Claude Code

Read this first. It summarises the build sessions on the development laptop (9–17 November 2026) and the first server session (26 November 2026), so work can continue on either machine without the original chats. Details live in [PROGRESS.md](PROGRESS.md) (what was built, run, verified and still open) and [SETUP.md](SETUP.md) (server steps, download links and the experiment commands).

## The project

- **What:** SmartRoute, a final-year project (FAST NUCES Karachi, FYP-I). It is a gateway that routes each request to a local model, a cheap cloud model or a strong cloud model, using a contextual bandit. Privacy is a hard rule: confidential content does not leave the server unless the superadmin allows it for that user and the user consents for that message.
- **Team:** Aman Malik, Muhammad Maarij, Syed Tuaha Ahmed. Supervisor: Dr. Farrukh Salim Sheikh.
- **Source documents** (repo root):
  - `FYP Proposal.pdf`
  - `SmartRoute_LLM_Routing_Research_Guide.pdf`, which the build follows

## Where we are now

- **Two machines:**
  - **Laptop:** code only. No model downloads, no datasets, no model runs; tests run with mock models and SQLite.
  - **GPU server:** Windows 11, RTX 4000 Ada (20 GB), 32 GB RAM. No Docker, WSL or PostgreSQL: the backend runs from `backend/.venv` with SQLite. Large files live on D: (`OLLAMA_MODELS=D:\SmartRoute\ollama-models`, `HF_HOME=D:\SmartRoute\hf-cache`).
- **First server run (26 November):**
  - **Tiers:** three local Ollama models stand in for the tiers, because there are no cloud keys yet. They are `gpt-oss:20b` (local), `qwen3.5:9b` (cheap) and `qwen3.6:27b` (strong). The cheap and strong prices and latencies are **simulated**, and the report must say so.
  - **Workload and calibration:** 588 QASPER requests. A 20-request pilot set C_ref = $0.0075 and L_ref = 10 s.
  - **Outcomes and grading:** 1,764 outcomes were collected. A local correctness judge, `gemma4:26b`, grades them.
  - **Frozen router:** trained, with weights in `backend/artifacts/`. The privacy suite ran with Presidio and GLiNER.
- **Ran for real so far:** Ollama, Presidio, GLiNER, the embedding features and QASPER.
- **Not run yet:** any cloud API, Docker, PostgreSQL, the OCR model and human ratings. vLLM needs Linux, so OCR is `off` on the Windows server.
- **Next:** see "Remaining work" in PROGRESS.md. The open items are the detector over-blocking decision, cloud keys followed by recollecting outcomes and retraining, the human ratings, retrieval, and Linux for Docker and OCR.
- **FYP-I reports** (Final Report, SRS, SDS): on hold. They will be written from scratch later, when the team asks.

## Requirements the user set (keep them)

1. **Two phases:**
   - a chat interface
   - an OpenAI-compatible router API (`/v1/chat/completions`) that developers call from their own backends with a SmartRoute key (`sr-...`)
2. **RBAC with three roles (superadmin, admin, user) in a single organisation.** Only the superadmin decides whether a user may send confidential queries to cloud models: an organisation default plus a per-user allow/deny/inherit. A cloud master switch overrides everything.
3. **Confidential queries are audited.** The audit row holds metadata, the detected entity types, a SHA-256 hash and a masked preview. The raw query text is never stored.
4. **Cloud providers:** Anthropic Claude, Google Gemini, Azure OpenAI and OpenAI-compatible endpoints. Ollama serves the local model.
7. **One model per tier, chosen only by the superadmin** (changed 27 November; this replaces "developers bring their own cloud keys"):
   - **Who sets them:** the superadmin sets the provider, model and key for the local, cheap and strong tiers in Settings → Models (`PUT /api/tiers/{tier}`).
   - **What users can do:** users and admins cannot add, change or remove provider keys or models; they only use the tiers.
   - **No cloud model is seeded.** Claude Haiku and Opus were removed, and cheap and strong start as "Not set".
   - **Changing a tier's model keeps that tier's trained router weights,** so it does not start from scratch (see Research settings).
5. **Industry-grade and self-hosted** on our server (Docker Compose: postgres, ollama, ocr, backend, frontend).
6. **OCR for photos and scanned PDFs** with `baidu/Unlimited-OCR`, served by vLLM on the server. This was added after the proposal, which excluded OCR: tell the supervisor.

## Privacy invariants (do not break)

- **Order of the gate:** detection (`core/privacy/scanner.py`, `PayloadGate.assess`) is separate from enforcement (`decide_cloud`). Ineligible models are removed *before* any routing policy runs, so exploration and retries only choose from what is left.
- **Final outbound check:** a second check runs on the exact payload just before any cloud call.
- **Fail closed:**
  - a detector error blocks the cloud
  - if no permitted model can answer, the request is refused with a reason (the API returns HTTP 403 `privacy_policy_block`)
  - there is never a silent cloud fallback
- **Derived content stays confidential:** turns that are summarised or dropped from history are still scanned. Only a local model may write conversation summaries.
- **OCR stays local:** the backend refuses a non-local OCR endpoint, and the mock OCR is refused in production. Images are re-encoded, which strips EXIF/GPS, before OCR.
- **Run the privacy suite** (`scripts/run_privacy_suite.py`) after any detector change. Regex alone misses person names (0 of 10); with Presidio and GLiNER on the server it found 10 of 10 with 0 unauthorised dispatches. Those detectors over-block 14 of 50 harmless academic texts, though, because GLiNER reads numbers as cards, accounts or IDs. Whether to leave structured identifiers to regex only is an open decision (PROGRESS.md).
- **The gateway's own system prompt is not scanned** (`KIND_SYSTEM`): GLiNER read "SmartRoute" as a person's name. A caller's system prompt is still scanned.

## Layout

```
backend/app/
  config.py                 settings, env prefix SMARTROUTE_ (OCR, DB, retention ...)
  core/pipeline.py          one pipeline for chat, the API and the benchmark
  core/privacy/             scanner (regex + optional Presidio/GLiNER), gate
  core/routing/             rules, frozen ridge, epsilon-greedy, LinUCB + budget pacer
  core/tiers.py             the three tier slots, set_tier(), tier keys, weight remapping on import
  core/providers/           ollama, openai-compatible, azure, anthropic, mock
  core/context.py           follow-up detection, history window, rolling local summary
  core/ocr.py, documents.py OCR client (vLLM), PDF/TXT/image extraction, BM25
  api/                      auth, chat, documents, registry, policy, analytics, openai_compat
  evaluation/, scripts/     workload, outcomes, correctness judge, frozen training, ratings, evaluation, privacy suite
backend/artifacts/          features.json + frozen_router_v1-3.json (trained weights, in git; data/ is not)
backend/tests/              138 tests (pytest); conftest forces SQLite, OCR off, ML detectors off
results/                    one folder per run (baseline: 2026-11-26_baseline_per_tier_ridge); scripts/snapshot_results.py; never edit a committed run
kaggle/                     smartroute_backend.ipynb: backend on Kaggle (T4 x2) + Cloudflare tunnel for the laptop frontend
frontend/                   Next.js 15 + Tailwind; app/(app)/chat, app/(app)/settings/*
FYP Prototypes/             offline jury prototype (HTML), deck (pptx), screenshots, presenter README
```

## Commands

```bash
# backend
cd backend && python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt     # + requirements-ml.txt on the server
python -m pytest -q                                          # expect 138 passed
uvicorn app.main:app --host 0.0.0.0 --port 8000

# frontend
cd frontend && npm ci && npm run dev        # http://localhost:3000 ; npm run typecheck ; npm run build

# full stack on the server
cp .env.example .env    # fill in secrets first, see SETUP.md
docker compose up -d --build
```

Development login is set by `SMARTROUTE_BOOTSTRAP_ADMIN_EMAIL` and `SMARTROUTE_BOOTSTRAP_ADMIN_PASSWORD`; the laptop used `admin@smartroute.local`. Set a strong password on the server. `SMARTROUTE_SEED_MOCK_MODELS=true` and `SMARTROUTE_OCR_BACKEND=mock` exist for development only.

## Web interface conventions (the user asked for these)

- **Layout:** a chat-first layout in the style of the Claude chat app.
  - **Sidebar:** collapsible, holding only New chat, Recents and the account menu (Settings, Light/Dark/System, Sign out).
  - **Composer:** chat controls live in the message box: "+" for files, an options menu (Local only, Confidential, Consent, Keep history) and a model picker.
  - **Settings:** everything else is under `/settings` (General, Files, API, Analytics; for admins Users, Audit, Policy, Models). Old paths redirect (`next.config.mjs`).
- **Colours:** CSS variables in `frontend/app/globals.css`, mapped in `tailwind.config.ts`.
  - **Light:** ivory `#faf9f5`, text `#141413`.
  - **Dark:** charcoal `#262624`, sidebar `#1f1e1d`, cards `#30302e`.
  - **Accent:** terracotta `#c96442` / `#d97757`.
  - **Fonts:** serif for answers and headings.
- **Branding:** keep the SmartRoute name and its own route-mark logo. Do not use Anthropic's name or logo.
- **Wording:** short labels, one or two words. No "AI" wording in the interface. The mock model answers `Demo response (<model>).`
- **New chat flow:** the first message creates the session and updates the URL with `window.history.replaceState` (`/chat?c=<id>`) so the stream is not interrupted. Pages that use `useSearchParams` are wrapped in `<Suspense>`.
- **Prototype:** `FYP Prototypes/SmartRoute_Prototype.html` mirrors the app and must stay a single offline file. Its URL parameters are `?step=N&panel=0&theme=dark|light&menu=acct|plus&sidebar=0`. It keeps the "Demo" tag and the SPECIMEN marks on the fake CNIC card.

## Research settings to remember

- **Reward:** R = 0.5·Q + 0.3·cost term + 0.2·latency term. In "split" mode the router learns quality and calculates cost and latency. This differs from the proposal, so declare it in the protocol.
- **Calibration:** `C_ref` = $0.0075 (the strong tier's median request cost in the pilot) and `L_ref` = 10 s. Set them with `scripts/set_reward_calibration.py`. The code default of 0.002 makes the strong model unpickable. Recalibrate when real cloud tiers replace the stand-ins.
- **Frozen ridge router weights** (`backend/artifacts/`):
  - **v1:** quality is word overlap. Superseded, because it counted context-window exclusions as failures.
  - **v2:** quality is word overlap. Kept for comparison.
  - **v3:** quality is judged correctness by `gemma4:26b`, using checklist rubric v3. **This version is active**, and epsilon-greedy and LinUCB are warm-started from it.
  - **Training data:** all three use 27 features, 16 of them PCA dimensions of the sentence embedding. v1 was trained on 353 requests, v2 and v3 on 345.
  - **Loading on another machine:** `scripts/import_frozen_router.py artifacts/frozen_router_v3.json --warm-start`. The full sequence is in PROGRESS.md under "Running the app on the server".
- **Weights belong to tiers, not to providers:**
  - Each tier is one fixed registry entry, its "slot".
  - Changing the tier's provider or model edits the slot in place and keeps its name; the learners store their weights under that name, so a new cheap model starts from the trained cheap weights. Health and latency reset; the change is logged in the policy history with key hints only.
  - Slot names differ by machine: the server's are `local-default`, `sim-cheap` and `sim-strong`, and a fresh install's are `local-default`, `cheap` and `strong`.
  - `import_frozen_router.py` attaches weights by tier using the `tiers` map in the artifact.
  - Retrain on outcomes from the new model when the evaluation needs it. `collect_outcomes.py` takes tier names and refuses to mix two models' answers under one tier in a file.
- **Quality metric:** the judge replaced word overlap, and that changed a conclusion. Word overlap said the local model was significantly worse; the judge says it is the most accurate. Report judge-based numbers, and the agreement with human raters once the ratings exist.
- **Evaluation:**
  - QASPER workload with a 60/20/20 split by paper. In practice 588 requests: 120 papers, but only 28 unanswerable questions in the sample.
  - clustered bootstrap intervals and an IPS check
  - a 200-case privacy suite
  - blinded human ratings: `backend/data/ratings_sheet.csv`, 108 answers, ready for two raters
  - benchmark budget about USD 55 of the USD 100 platform budget, for when cloud keys exist
- **Local model context:** each Ollama model needs `{"options":{"num_ctx":N}}` in its registry params, equal to its context window, or Ollama truncates silently. `register_ollama_tiers.py` sets 16k for local and cheap, and 8k for strong, because the 27B model spills to the CPU at 16k.

## Working with this user

- They want to be asked when something is genuinely unclear, and they want suggestions with a short explanation of why while building.
- They care that it looks and feels professional. Keep the interface terse.
- Keep secrets out of git: `.env` files are ignored, and cloud keys are entered by the superadmin per tier in Settings → Models and stored encrypted.
- Update PROGRESS.md when something significant is finished or verified.
