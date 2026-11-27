# SmartRoute jury prototypes

| File | What it is |
|---|---|
| `SmartRoute_Jury_Presentation.pptx` | 16-slide deck with speaker notes on every slide (about 20 minutes) |
| `SmartRoute_Routing_Techniques.pptx` | 60-slide deck: every routing technique from the map (A1–A8, B9–B10, C11–C13, D1–D4) simulated step by step on one shared example, with Morph transitions and speaker notes. Present it in slide-show mode to see the animation |
| `SmartRoute_Prototype.html` | Clickable prototype of the real screens. Open it in Chrome or Edge; it needs no internet and no server |
| `screens/` | Screenshots of each demo step plus the new-chat screen (light theme); `screens/dark/` has the same set in the dark theme |

## Running the live demo

1. Open `SmartRoute_Prototype.html` in Chrome or Edge, full screen (F11).
2. Press **Start** in the small dark panel at the bottom left, then **Next** for each step. Each step signs in as the right account, types the message and shows the decision. The panel shows only the step name; the narration is in the table below.
3. To answer a jury question, type your own message in the chat. The routing and privacy decision is computed live by the same rules as the gateway; only the answer text is prepared in advance.
4. **Hide** folds the panel away. **Restart** resets everything.
5. The prototype has the same layout as the web app:
   - **Sidebar:** New chat, Recents and your name at the bottom. The button at the top left collapses the sidebar.
   - **Account menu** (click your name): Settings, switch account, Light / Dark, and Sign out. The sign-in screen has a Dark/Light button at the top right, and `?theme=dark` or `?theme=light` also works.
   - **Message box:** **+** for files and the CNIC photo, the options button for Local only / Confidential / Consent, and the model picker beside the send button.
   - **Settings:** Files, API, Analytics and the admin pages (Users, Audit, Policy, Models).

### Narration

| # | Step | What to say |
|---|---|---|
| 1 | Sign in | We sign in as Ayesha, an ordinary student account. Three roles exist: user, admin and superadmin. |
| 2 | Simple → Local | A short definition question goes to the free local model on our GPU server. No API cost. |
| 3 | Complex → Strong | A multi-part comparison is routed to the strong cloud model. The **ⓘ** button under the answer shows every model, why it was eligible or removed, the rule that chose, the estimated cost and the tokens. |
| 4 | Follow-up | "Why?" alone has no meaning. The router detects a follow-up, keeps the earlier difficulty and sends the conversation history with it. |
| 5 | CNIC → Local | The message holds a CNIC. Both cloud models are removed before routing ("Not permitted") and the local model answers. The event is written to the audit log with a masked preview. |
| 6 | CNIC photo → OCR | From the **+** menu, a photo of a specimen card is read by baidu/Unlimited-OCR on our own server. The extracted text is scanned like any message, so the document is marked confidential and the answer stays local. Image metadata is removed. |
| 7 | Audit | As superadmin: every confidential request is logged with user, reason, decision, destination, a masked preview and a hash. The text itself is never stored. |
| 8 | Grant access | The superadmin allows Ayesha to send confidential content to the cloud. The change is recorded in History. |
| 9 | Consent → Cloud | Even when permitted, the user must switch on **Consent** (options button) for that message. Only then can a cloud model answer, and the audit marks it "Sent out". |
| 10 | Local only | A chat with **Local only** switched on never leaves the server, even for a hard question. |
| 11 | API | The same gateway as an OpenAI-compatible API. A CNIC sent through the API is refused with HTTP 403 and a reason when no local model is available. It never falls back to the cloud. |
| 12 | Analytics | Cost against a strong-only baseline, the share answered locally, and confidential counts. Demo data, marked "Est." |
| 13 | Policy | The superadmin controls cloud access, the organisation default, consent, the router (rules, frozen, ε-greedy, LinUCB), history budget and limits. |

Things worth trying live:

- Paste a CNIC (`42101-1234567-1`) or a phone number (`0300-1234567`) into a message.
- Press **+** → **CNIC photo** to attach the specimen card, then ask about it.
- Switch on **Local only** in the options menu, then ask a hard question.
- As Super Admin, switch off the local model in **Settings → Models**, then send a CNIC as the student. The request is refused with a reason instead of going to the cloud.

## What to say if asked

- **Are the answers real?** No. No model runs on the laptop; answers to the scripted questions are prepared in advance and anything else shows "Demo response". The routing and privacy decisions are real: they follow the gateway's rules. The **Demo** tag next to the logo says so.
- **Are the analytics numbers results?** No. They are demo data. Real results come from the GPU server (deck slide 15).
- **Is the CNIC card real?** No. It is a generic specimen with a fictional name and the demo number `42101-1234567-1`, marked SPECIMEN and "Not a real document", and it does not copy the official card design.
- **Does the OCR really run?** In the prototype the OCR result is prepared in advance. In the gateway, `baidu/Unlimited-OCR` reads the image on the GPU server and is tested with a mock on the laptop. OCR is new since the proposal (deck slide 11).
- **What is actually verified?** See deck slide 14: 108 tests pass, and the 200-case privacy suite produced no unauthorised dispatches. All of this was run with mock models and the pattern detectors only. That was the state when the deck was made. Since then the gateway has run on the GPU server with real local models and the full detectors; see `PROGRESS.md`.

## Rebuilding the techniques deck

`source/routing_techniques_deck.js` generates `SmartRoute_Routing_Techniques.pptx`. It needs Node with `pptxgenjs` and `jszip`, and the pptx skill's `apply_theme.js` (path in `PPTX_SKILL`):

```bash
PPTX_SKILL=/path/to/pptx-skill node source/routing_techniques_deck.js SmartRoute_Routing_Techniques.pptx
```

All numbers on the slides are computed in the script from the formulas, and the script stops if a result contradicts a slide's claim.
