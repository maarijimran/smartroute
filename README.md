# SmartRoute

Privacy-constrained contextual-bandit routing for hybrid local and cloud LLMs. Final year project, FAST NUCES Karachi.

SmartRoute sits between an application and its language models. For each request it checks, on the local machine, whether the content is confidential, removes every model that is not allowed or cannot take the request, and then picks the best of the remaining models for quality, cost and speed. If no permitted model can answer, it refuses and says why.

## Two ways to use it

- **Chat interface.** Upload papers, ask questions, get summaries. Each answer shows which model wrote it, why, and what it cost.
- **Router API.** An OpenAI-compatible endpoint. A developer calls SmartRoute from their backend with a SmartRoute key; the models and provider keys behind it are the organisation's.

## Request flow

```
request
  -> local retrieval (BM25)            evidence from the user's documents
  -> confidentiality check             regex + Presidio + GLiNER, fails closed
  -> eligibility filter                privacy, credentials, health, context window, budget
  -> routing policy                    rules | frozen router | epsilon-greedy | LinUCB
  -> final outbound check              re-checks the exact payload before a cloud call
  -> model                             local (Ollama) or cloud
  -> log, score, learn                 cost ledger, audit log, batched bandit update
```

Privacy is a filter in front of the router, never a term in its reward.

## Roles

| Role | Can do |
|---|---|
| superadmin | Privacy policy, who may send confidential content to cloud, the local, cheap and strong models and their provider keys, roles |
| admin | Manage ordinary users, view analytics and the confidential audit log |
| user | Chat, own documents, own SmartRoute API keys (no provider keys or models) |

## Repository layout

| Path | Contents |
|---|---|
| `backend/app/core` | Pipeline, privacy gate, routing policies, provider adapters |
| `backend/app/api` | REST endpoints, including the `/v1` router API |
| `backend/app/evaluation`, `backend/scripts` | Benchmark, privacy suite, analysis |
| `backend/artifacts` | Trained router weights: `features.json`, `frozen_router_v1-3.json` (v3, trained on judge correctness, is the one in use) |
| `backend/tests` | 126 tests that need no model |
| `frontend` | Next.js web interface |
| `SETUP.md` | Downloads, server setup, experiment steps |
| `PROGRESS.md` | What is done, what is verified, what remains |

## Quick start without any model

```bash
cd backend && python -m venv .venv
.venv/Scripts/python -m pip install -r requirements-dev.txt
cp .env.example .env
.venv/Scripts/python -m uvicorn app.main:app --port 8000
```

```bash
cd frontend && npm install && npm run dev
```

Open http://localhost:3000 and sign in with the account from `backend/.env`. Three mock models stand in for the real ones.

For the GPU server and the experiments, follow [SETUP.md](SETUP.md).

## Status

The code is complete for the core scope and tested without models. On 26 November 2026 it ran on the GPU server with three local Ollama models standing in for the local, cheap and strong tiers (cloud prices and latency simulated). That run covered the QASPER workload, 1,764 outcomes, a local correctness judge, a trained frozen router and the privacy suite with Presidio and GLiNER. Cloud APIs, Docker, PostgreSQL, OCR and human ratings are not run yet. See [PROGRESS.md](PROGRESS.md).
