"""Phase 2: the SmartRoute router API.

OpenAI-compatible, so an existing application switches by changing its base URL
and API key:

    client = OpenAI(base_url="https://<your-server>/v1", api_key="sr-...")
    client.chat.completions.create(model="smartroute/auto", messages=[...])

The developer connects their own paid cloud keys once (Keys page or
POST /api/credentials). Every call then passes through the same privacy gate,
eligibility filter and router as the chat interface.

Routing controls, all optional:
  model                      "smartroute/auto" (router decides) or a registry name
  smartroute.privacy_mode    "local_only" | "cloud_allowed"   (header X-SmartRoute-Privacy)
  smartroute.consent         true to consent to sending confidential content
                             to cloud for THIS request      (header X-SmartRoute-Consent)
  smartroute.confidential    true to label the request confidential
"""

import json
import time

from fastapi import APIRouter, Depends, Header
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core import pipeline
from ..core.policy_config import load_policy
from ..core.privacy.gate import CLOUD_ALLOWED, LOCAL_ONLY
from ..core.reward import human_score
from ..db import get_db
from ..deps import get_api_principal
from ..models import ROLE_USER, ApiKey, Feedback, ModelEntry, RoutingEvent, User
from ..schemas import FeedbackIn, OAIChatRequest

router = APIRouter(prefix="/v1", tags=["router-api"])
AUTO_MODELS = {"smartroute/auto", "smartroute", "auto"}


def _error(status: int, message: str, kind: str, code: str, meta: dict | None = None) -> JSONResponse:
    body = {"error": {"message": message, "type": kind, "code": code}}
    if meta:
        body["smartroute"] = meta
    return JSONResponse(body, status_code=status)


def _text(content) -> str | None:
    """Flattens OpenAI content (string or list of parts). Returns None for non-text parts."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    pieces = []
    for part in content:
        if isinstance(part, dict) and part.get("type") == "text":
            pieces.append(part.get("text", ""))
        else:
            return None
    return "\n".join(pieces)


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in ("1", "true", "yes")


@router.get("/models")
def list_models(principal: tuple[User, ApiKey] = Depends(get_api_principal), db: Session = Depends(get_db)):
    names = db.execute(select(ModelEntry.name).where(ModelEntry.enabled.is_(True)).order_by(ModelEntry.name)).scalars()
    data = [{"id": "smartroute/auto", "object": "model", "owned_by": "smartroute"}]
    data += [{"id": name, "object": "model", "owned_by": "smartroute"} for name in names]
    return {"object": "list", "data": data}


@router.post("/chat/completions")
def chat_completions(
    body: OAIChatRequest,
    principal: tuple[User, ApiKey] = Depends(get_api_principal),
    db: Session = Depends(get_db),
    x_smartroute_privacy: str | None = Header(None),
    x_smartroute_consent: str | None = Header(None),
):
    user, key = principal
    cfg = load_policy(db)
    options = body.smartroute

    system_parts, turns = [], []
    for m in body.messages:
        text = _text(m.content)
        if text is None:
            return _error(400, "Only text content is supported.", "invalid_request_error", "unsupported_content")
        if m.role in ("system", "developer"):
            system_parts.append(text)
        elif m.role in ("user", "assistant"):
            turns.append({"role": m.role, "content": text})
        else:
            return _error(400, f"Unsupported message role '{m.role}'.", "invalid_request_error", "unsupported_role")
    if not turns or turns[-1]["role"] != "user":
        return _error(400, "The last message must be a user message.", "invalid_request_error", "invalid_messages")

    pinned = None if body.model in AUTO_MODELS else body.model
    if pinned and user.role == ROLE_USER and not cfg.users_may_pin_model:
        return _error(403, "Choosing a specific model is disabled; use 'smartroute/auto'.", "permission_error", "pin_disabled")

    # A key created as local-only is a hard restriction: a request can tighten the
    # privacy mode but never loosen it.
    requested = (options.privacy_mode if options and options.privacy_mode else x_smartroute_privacy) or ""
    requested = requested.replace("-", "_").lower()
    local_only = key.default_privacy_mode == LOCAL_ONLY or requested == LOCAL_ONLY

    request = pipeline.RouteRequest.for_user(
        user,
        turns,
        source="api",
        privacy_mode=LOCAL_ONLY if local_only else CLOUD_ALLOWED,
        consent=bool(options and options.consent) or _truthy(x_smartroute_consent),
        confidential_label=bool(options and options.confidential),
        system_prompt="\n\n".join(system_parts),
        task=options.task if options else None,
        pinned_model=pinned,
        max_tokens=body.max_completion_tokens or body.max_tokens,
        temperature=body.temperature,
        api_key_id=key.id,
        use_cache=options.cache if options else True,
    )
    plan = pipeline.prepare(db, request)
    headers = {"X-SmartRoute-Event-Id": plan.event_id}

    if plan.abstain_reason:
        outcome = pipeline.run_to_completion(plan)
        return _abstained(outcome, plan.abstain_reason, headers)

    created = int(time.time())
    completion_id = f"chatcmpl-{plan.event_id}"

    if not body.stream:
        outcome = pipeline.run_to_completion(plan)
        if outcome.status == "abstained":
            return _abstained(outcome, plan.abstain_reason or outcome.explanation, headers)
        if outcome.status in ("failed", "empty", "refused"):
            return JSONResponse(
                {
                    "error": {
                        "message": outcome.error or f"The model returned no usable answer ({outcome.status}).",
                        "type": "upstream_error",
                        "code": f"model_{outcome.status}",
                    },
                    "smartroute": outcome.public(),
                },
                status_code=502,
                headers=headers,
            )
        headers["X-SmartRoute-Model"] = outcome.model or ""
        return JSONResponse(
            {
                "id": completion_id,
                "object": "chat.completion",
                "created": created,
                "model": outcome.model,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": outcome.text},
                        "finish_reason": "length" if outcome.status == "truncated" else "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": outcome.in_tokens,
                    "completion_tokens": outcome.out_tokens,
                    "total_tokens": outcome.in_tokens + outcome.out_tokens,
                },
                "smartroute": outcome.public(),
            },
            headers=headers,
        )

    def chunk(delta: dict, finish: str | None = None, **extra) -> str:
        payload = {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": plan.decision.arm if plan.decision else "smartroute",
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
            **extra,
        }
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    def stream():
        yield chunk({"role": "assistant", "content": ""})
        outcome = None
        for kind, item in pipeline.run(plan):
            if kind == "delta":
                yield chunk({"content": item})
            else:
                outcome = item
        if outcome.status in ("ok", "truncated", "cache_hit"):
            usage = {
                "prompt_tokens": outcome.in_tokens,
                "completion_tokens": outcome.out_tokens,
                "total_tokens": outcome.in_tokens + outcome.out_tokens,
            }
            yield chunk({}, "length" if outcome.status == "truncated" else "stop", usage=usage, smartroute=outcome.public())
        else:
            message = outcome.error or plan.abstain_reason or f"The request ended with status {outcome.status}."
            error = {"message": message, "type": "upstream_error", "code": f"model_{outcome.status}"}
            yield f"data: {json.dumps({'error': error, 'smartroute': outcome.public()}, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"

    headers.update({"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
    return StreamingResponse(stream(), media_type="text/event-stream", headers=headers)


def _abstained(outcome, reason: str, headers: dict) -> JSONResponse:
    privacy = outcome.abstain_kind == "privacy"
    response = _error(
        403 if privacy else 503,
        reason,
        "privacy_policy_block" if privacy else "no_eligible_model",
        "privacy_policy_block" if privacy else "no_eligible_model",
        outcome.public(),
    )
    response.headers.update(headers)
    return response


@router.post("/feedback")
def api_feedback(
    body: FeedbackIn, principal: tuple[User, ApiKey] = Depends(get_api_principal), db: Session = Depends(get_db)
):
    """Rate an answer by its `smartroute.event_id`; ratings train the adaptive router."""
    user, _ = principal
    event = db.get(RoutingEvent, body.event_id)
    if event is None or event.user_id != user.id:
        return _error(404, "Unknown event_id.", "invalid_request_error", "not_found")
    if event.status != "ok":
        return _error(409, "Only completed answers can be rated.", "invalid_request_error", "not_rateable")
    db.add(Feedback(user_id=user.id, **body.model_dump()))
    score = human_score(body.correctness, body.relevance, body.completeness, body.usefulness)
    updated = pipeline.record_quality(db, body.event_id, human=score)
    return {"quality": updated.quality, "reward": updated.reward}
