# SmartRoute

Privacy-constrained contextual-bandit routing for hybrid local and cloud LLMs. Final year project, FAST NUCES Karachi.

SmartRoute sits between an application and its language models. For each request it checks, on the local machine, whether the content is confidential, removes every model that is not allowed or cannot take the request, and then picks the best of the remaining models for quality, cost and speed. If no permitted model can answer, it refuses and says why.

## Two ways to use it

- **Chat interface.** Upload papers, ask questions, get summaries. Each answer shows which model wrote it, why, and what it cost.
- **Router API.** An OpenAI-compatible endpoint. A developer connects their own paid cloud keys once and then calls SmartRoute from their backend with a SmartRoute key.

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
| superadmin | Privacy policy, who may send confidential content to cloud, model registry, platform keys, roles |
| admin | Manage ordinary users, view analytics and the confidential audit log |
| user | Chat, own documents, own cloud keys, own SmartRoute API keys |

## Repository layout

| Path | Contents |
|---|---|
| `backend/app/core` | Pipeline, privacy gate, routing policies, provider adapters |
| `backend/app/api` | REST endpoints, including the `/v1` router API |
| `backend/app/evaluation`, `backend/scripts` | Benchmark, privacy suite, analysis |
| `backend/tests` | 108 tests that need no model |
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

The code is complete for the core scope and tested without models. Nothing has been run against a real model, the dataset or Docker yet. See [PROGRESS.md](PROGRESS.md).
