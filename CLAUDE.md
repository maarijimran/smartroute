# SmartRoute: context for Claude Code

Read this first. It summarises the build sessions held on the development laptop (9–17 November 2026), so work can continue on the GPU server without the original chat. Details live in [PROGRESS.md](PROGRESS.md) (what was built, verified and still open) and [SETUP.md](SETUP.md) (server steps and every download link).

## The project

- **What:** SmartRoute, a final-year project (FAST NUCES Karachi, FYP-I). It is a gateway that routes each request to a local model, a cheap cloud model or a strong cloud model, using a contextual bandit. Privacy is a hard rule: confidential content does not leave the server unless the superadmin allows it for that user and the user consents for that message.
- **Team:** Aman Malik, Muhammad Maarij, Syed Tuaha Ahmed. Supervisor: Dr. Farrukh Salim Sheikh.
- **Source documents** (repo root):
  - `FYP Proposal.pdf`
  - `SmartRoute_LLM_Routing_Research_Guide.pdf`, which the build follows

## Where we are now

- **Laptop phase:** all code was written on a laptop that ran no models and downloaded no datasets.
- **Next:** this repository is pulled onto the GPU server to:
  - install the ML extras (`backend/requirements-ml.txt`)
  - pull the models
  - run the real experiments
- **Order of work on the server:** SETUP.md, then "Remaining work" in PROGRESS.md.
- **Never run with real models or data so far:** Ollama, any cloud API, Presidio/GLiNER, the OCR model, QASPER, Docker and PostgreSQL. Expect first-run fixes there.

## Requirements the user set (keep them)

1. **Two phases:**
   - a chat interface
   - an OpenAI-compatible router API (`/v1/chat/completions`) that developers call from their own backends after storing their own paid cloud keys
2. **RBAC with three roles (superadmin, admin, user) in a single organisation.** Only the superadmin decides whether a user may send confidential queries to cloud models: an organisation default plus a per-user allow/deny/inherit. A cloud master switch overrides everything.
3. **Confidential queries are audited.** The audit row holds metadata, the detected entity types, a SHA-256 hash and a masked preview. The raw query text is never stored.
4. **Cloud providers:** Anthropic Claude, Google Gemini, Azure OpenAI and OpenAI-compatible endpoints. Ollama serves the local model.
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
- **Run the privacy suite** (`scripts/run_privacy_suite.py`) after any detector change. Regex alone misses person names; Presidio and GLiNER must be enabled on the server.

## Layout

```
backend/app/
  config.py                 settings, env prefix SMARTROUTE_ (OCR, DB, retention ...)
  core/pipeline.py          one pipeline for chat, the API and the benchmark
  core/privacy/             scanner (regex + optional Presidio/GLiNER), gate
  core/routing/             rules, frozen ridge, epsilon-greedy, LinUCB + budget pacer
  core/providers/           ollama, openai-compatible, azure, anthropic, mock
  core/context.py           follow-up detection, history window, rolling local summary
  core/ocr.py, documents.py OCR client (vLLM), PDF/TXT/image extraction, BM25
  api/                      auth, chat, documents, registry, policy, analytics, openai_compat
  evaluation/, scripts/     workload, outcomes, frozen training, ratings, evaluation, privacy suite
backend/tests/              108 tests (pytest); conftest forces SQLite + OCR off
frontend/                   Next.js 15 + Tailwind; app/(app)/chat, app/(app)/settings/*
FYP Prototypes/             offline jury prototype (HTML), deck (pptx), screenshots, presenter README
```

## Commands

```bash
# backend
cd backend && python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt     # + requirements-ml.txt on the server
python -m pytest -q                                          # expect 108 passed
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
- **Calibration:** `C_ref` must be set near the strong model's typical request cost from pilot data. The default 0.002 makes the strong model unpickable. Also set `L_ref` from the pilot.
- **Evaluation:**
  - QASPER workload with a 60/20/20 split by paper
  - clustered bootstrap intervals and an IPS check
  - a 200-case privacy suite
  - blinded human ratings
  - benchmark budget about USD 55 of the USD 100 platform budget
- **Local model context:** the local model needs `{"options":{"num_ctx":8192}}` in its registry params, matching its context window, or Ollama truncates silently.

## Working with this user

- They want to be asked when something is genuinely unclear, and they want suggestions with a short explanation of why while building.
- They care that it looks and feels professional. Keep the interface terse.
- Keep secrets out of git: `.env` files are ignored, and cloud keys are entered in Settings → API and stored encrypted.
- Update PROGRESS.md when something significant is finished or verified.
