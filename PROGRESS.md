# SmartRoute: work log and remaining work

Last updated: 17 November 2026. Written for the three team members, including whoever was not in the build session.

## Where things stand

The gateway, both phases of the product (chat interface and router API), role-based access control, the confidential audit log, the web interface and the evaluation scripts are written. Everything that can run without a model has been run on the laptop and passes. Nothing that needs a real model, a real API key, the QASPER dataset or Docker has been run yet. That work is waiting for the GPU server, and [SETUP.md](SETUP.md) lists it step by step.

## What was asked for

1. Follow the research guide and build the whole project.
2. Code only on the laptop: no model downloads, no datasets, no model runs. Link everything to download later in SETUP.md.
3. Two phases: a chat interface, then our own API that a developer calls from their backend after connecting their paid cloud keys.
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
- Seeded cloud models are Claude Haiku 5.5 (cheap) and Claude Opus 5.5 (strong). Any provider's models can replace them.

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

`docker-compose.yml` (PostgreSQL, Ollama with GPU, backend, frontend), two Dockerfiles, environment templates.

## How the main requirements are met

- **Superadmin control of confidential queries.** An organisation default plus a per-user override (allow, deny, inherit), both editable only by the superadmin. A master switch turns cloud off for everyone and beats any consent.
- **Tracking.** Every request that carries confidential content writes an audit row before anything is dispatched: user, source (chat or API), why it counted as confidential, the decision and its reason, whether consent was given, the destination model, and whether the content left the server.
- **No silent cloud fallback.** If no permitted model can answer, the request is refused with an explanation. The API returns HTTP 403 with `privacy_policy_block`.
- **Privacy outside the learner.** Models are removed by the eligibility filter before any policy runs, and the outbound check runs again on the exact payload before a cloud call. Exploration and retries pick only from what is left.
- **Bring your own key.** Developers store their own cloud keys (encrypted). A key created as local-only can never reach cloud, whatever the request asks.

## What was verified on the laptop

- 108 automated tests pass.
- The server was started for real and called over HTTP: login, model list, router API with and without a CNIC, streaming, audit log.
- Privacy suite with regex detectors only: 0 enforcement failures in 150 cases that must be blocked; all 80 structured identifiers detected; 3 of 50 harmless lookalikes wrongly blocked.
- The evaluation script runs end to end on synthetic outcomes.
- The web interface type-checks and builds (11 pages).

## Findings worth acting on

1. **Names need the ML detectors.** With regex only, 0 of 10 person-name cases were detected and all 10 would have gone to cloud. Presidio and GLiNER must be enabled on the server, and their recall measured there.
2. **C_ref must be calibrated.** With the default $0.002 and a strong model costing about $0.01 per request, the strong model always scores zero on cost and no router ever chooses it. Set C_ref near the strong model's typical request cost from pilot data.
3. **The quality target constrains the reward weights.** On the synthetic data even the oracle missed the "lower bound above -0.05" target, because the reward itself trades quality for cost. Synthetic numbers prove nothing about real models, but the mechanism is real: choose the weights on the validation split so the target is reachable, then freeze them.
4. **Exploration schedule versus dataset size.** The proposal decays epsilon over 1,000 scored decisions, but the workload has 600 requests. The replay code supports several passes over the stream; otherwise shorten the schedule.
5. **A CNIC written without dashes at the end of a sentence was missed** by the first version of the regex. The privacy suite caught it and it is fixed. This is the kind of error the suite exists to find, so run it after every detector change.

## Not verified yet

- Any call to a real model: Ollama, Claude, OpenAI-compatible endpoints, Gemini, Azure. The adapters were checked against the installed SDK's signatures only.
- Presidio, GLiNER and the embedding features. Their code paths have never executed.
- `scripts/build_workload.py` against the real QASPER layout.
- Docker images and `docker-compose.yml`.
- PostgreSQL. Tests use SQLite.
- The web interface by a person. A headless browser on the laptop clicked through new chat, sending, menus, the sidebar toggle, Settings and redirects; a full manual pass with real models is still needed.

## Remaining work

### On the server (see SETUP.md)

1. Bring the stack up and fix whatever the first Docker build shows.
2. Pull the local model and profile the hardware.
3. Add cloud keys, correct the prices in the registry, send a test message to each model.
4. Run the privacy suite with the full detector set and record precision and recall.
5. Build the workload, fit features, run a small pilot, set C_ref and L_ref, freeze the protocol.
6. Collect outcomes within the $55 benchmark allocation, train the frozen router, collect the blinded ratings, run the evaluation.

### Still to build

| Item | Priority in the research guide | Note |
|---|---|---|
| Click-through test of the web interface and fixes | Must | First thing to do with a browser |
| Multi-turn evaluation set | Should | Chain the three QASPER questions per paper into conversations to measure follow-up detection and context handling |
| Database migrations (Alembic) | Needed for a real deployment | Tables are created at startup today, so a schema change needs a manual migration |
| NVIDIA complexity classifier as a feature | Could | A keyword and length heuristic is used now |
| Batch API for benchmark generation | Should | Would halve benchmark cost on providers that offer it |
| Local judge model or NLI faithfulness check | Could | Automatic scores are lexical overlap only |
| LLMLingua-2 compression, semantic cache | Could | Exact cache and output caps are in place |
| Mask-then-send with consent | Could (stretch) | Not started |
| Shared rate limiter and learner state for several workers | Later | Single worker today |
| HTTPS reverse proxy, backups, monitoring | Deployment | Not configured |

## Open questions for the team

1. Which operating system does the GPU server run? SETUP.md assumes Linux with Docker.
2. Which local model do we want? The default is `llama3.1:8b`.
3. Which two cloud models are the cheap and the strong option for the experiments?
4. Will the server be reached over a domain with HTTPS, or only inside the lab network?
5. Done: the project is in a private GitHub repository. `CLAUDE.md` gives Claude Code the context of the build sessions.
