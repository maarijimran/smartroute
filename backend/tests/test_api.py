"""HTTP-level tests: RBAC, the chat interface API and the /v1 router API."""

import json

from app.core.providers.mock import MockProvider

from .conftest import make_user

CNIC = "42101-1234567-1"
HARD = "Compare both methods, analyze the trade-offs step by step and justify which is more robust and why?"


def sse_events(response) -> list[dict]:
    out = []
    for line in response.text.splitlines():
        if line.startswith("data: ") and line != "data: [DONE]":
            out.append(json.loads(line[6:]))
    return out


def model_id(client, headers, name):
    return next(m["id"] for m in client.get("/api/models", headers=headers).json() if m["name"] == name)


# ----------------------------------------------------------------------- RBAC


def test_unauthenticated_requests_are_rejected(client):
    assert client.get("/api/auth/me").status_code == 401
    assert client.post("/v1/chat/completions", json={"messages": [{"role": "user", "content": "hi"}]}).status_code == 401


def test_only_superadmin_changes_privacy_policy(client, root):
    user = make_user(client, root)
    admin = make_user(client, root, email="admin@test.local", role="admin")
    policy = client.get("/api/policy", headers=root).json()
    policy["allow_confidential_cloud_default"] = True

    assert client.get("/api/policy", headers=user).status_code == 403
    assert client.put("/api/policy", json=policy, headers=user).status_code == 403
    assert client.get("/api/policy", headers=admin).status_code == 200  # admins may read
    assert client.put("/api/policy", json=policy, headers=admin).status_code == 403
    assert client.put("/api/policy", json=policy, headers=root).status_code == 200

    history = client.get("/api/policy/history", headers=root).json()
    assert history[0]["changes"] == {"allow_confidential_cloud_default": [False, True]}
    assert history[0]["actor"] == "root@test.local"


def test_confidential_permission_is_a_superadmin_decision(client, root):
    user = make_user(client, root)
    admin = make_user(client, root, email="admin@test.local", role="admin")
    uid = user["x-user-id"]
    grant = {"allow_confidential_cloud": True}

    assert client.patch(f"/api/users/{uid}", json=grant, headers=admin).status_code == 403
    assert client.patch(f"/api/users/{uid}", json=grant, headers=user).status_code == 403
    assert client.get("/api/auth/permissions", headers=user).json()["may_send_confidential_to_cloud"] is False
    assert client.patch(f"/api/users/{uid}", json=grant, headers=root).status_code == 200
    assert client.get("/api/auth/permissions", headers=user).json()["may_send_confidential_to_cloud"] is True
    # Admins manage ordinary users but cannot touch admins or create them.
    assert client.patch(f"/api/users/{uid}", json={"is_active": False}, headers=admin).status_code == 200
    assert client.get("/api/auth/me", headers=user).status_code == 401  # disabled immediately
    assert client.patch(f"/api/users/{admin['x-user-id']}", json={"name": "x"}, headers=admin).status_code == 403
    body = {"email": "a2@test.local", "password": "password-12", "role": "admin"}
    assert client.post("/api/users", json=body, headers=admin).status_code == 403


def test_last_superadmin_cannot_be_removed(client, root):
    me = client.get("/api/auth/me", headers=root).json()
    assert client.patch(f"/api/users/{me['id']}", json={"role": "user"}, headers=root).status_code == 409
    assert client.patch(f"/api/users/{me['id']}", json={"is_active": False}, headers=root).status_code == 409


def test_self_registration_follows_policy(client, root):
    body = {"email": "new@test.local", "password": "password-12"}
    assert client.post("/api/auth/register", json=body).status_code == 403
    policy = client.get("/api/policy", headers=root).json()
    policy["allow_self_registration"] = True
    client.put("/api/policy", json=policy, headers=root)
    assert client.post("/api/auth/register", json=body).json()["user"]["role"] == "user"


def test_tiers_and_keys_are_superadmin_only(client, root):
    user = make_user(client, root)
    admin = make_user(client, root, email="admin@test.local", role="admin")
    cheap = {"vendor": "openai", "model_id": "gpt-x-mini", "api_key": "sk-test-abcdef123456"}
    for headers in (user, admin):
        assert client.get("/api/tiers", headers=headers).status_code == 403
        assert client.put("/api/tiers/cheap", json=cheap, headers=headers).status_code == 403
        assert client.get("/api/credentials", headers=headers).status_code == 403
        assert client.post("/api/credentials", json={"vendor": "openai", "api_key": "sk-x-123456"}, headers=headers).status_code in (404, 405)
        assert client.post("/api/models", json={"name": "x", "vendor": "openai", "model_id": "x", "tier": "cheap"}, headers=headers).status_code in (404, 405)

    r = client.put("/api/tiers/cheap", json=cheap, headers=root)
    assert r.status_code == 200 and r.json()["key_hint"] == "3456" and r.json()["model"]["enabled"]
    assert "sk-test" not in client.get("/api/tiers", headers=root).text
    assert "sk-test" not in client.get("/api/credentials", headers=root).text
    # A cloud model can never take the local tier (that would bypass the privacy gate).
    assert client.put("/api/tiers/local", json={**cheap, "vendor": "openai"}, headers=root).status_code == 422
    # A new provider needs its key.
    assert client.put("/api/tiers/strong", json={"vendor": "anthropic", "model_id": "claude-x"}, headers=root).status_code == 422
    assert client.get("/api/audit/confidential", headers=user).status_code == 403


# ----------------------------------------------------------------------- chat


def test_chat_stream_and_feedback(client, root):
    user = make_user(client, root)
    session = client.post("/api/chat/sessions", json={}, headers=user).json()
    response = client.post(f"/api/chat/sessions/{session['id']}/messages", json={"content": HARD}, headers=user)
    assert response.status_code == 200
    events = sse_events(response)
    assert events[0]["type"] == "route" and events[-1]["type"] == "done"
    done = events[-1]
    assert done["meta"]["status"] == "ok" and done["meta"]["model"] == "mock-strong"
    assert "".join(e["text"] for e in events if e["type"] == "delta").strip() == done["text"].strip()

    messages = client.get(f"/api/chat/sessions/{session['id']}/messages", headers=user).json()
    assert [m["role"] for m in messages] == ["user", "assistant"]

    rating = {"event_id": done["meta"]["event_id"], "correctness": 5, "relevance": 4, "completeness": 4, "usefulness": 5}
    scored = client.post("/api/feedback", json=rating, headers=user).json()
    assert scored["quality"] == 0.875 and scored["reward"] is not None

    other = make_user(client, root, email="other@test.local")
    assert client.post("/api/feedback", json=rating, headers=other).status_code == 404
    assert client.get(f"/api/chat/sessions/{session['id']}/messages", headers=other).status_code == 404


def test_confidential_chat_is_blocked_from_cloud_audited_and_sticky(client, root):
    user = make_user(client, root)
    session = client.post("/api/chat/sessions", json={}, headers=user).json()
    url = f"/api/chat/sessions/{session['id']}/messages"
    done = sse_events(client.post(url, json={"content": f"{HARD} My CNIC is {CNIC}"}, headers=user))[-1]
    assert done["meta"]["model"] == "mock-local" and done["meta"]["sensitive"]
    assert MockProvider.dispatched == []

    # The label is sticky: a later harmless message in the same chat stays local.
    done = sse_events(client.post(url, json={"content": HARD}, headers=user))[-1]
    assert done["meta"]["model"] == "mock-local" and MockProvider.dispatched == []
    assert client.get("/api/chat/sessions", headers=user).json()[0]["confidential"] is True

    log = client.get("/api/audit/confidential", headers=root).json()
    assert len(log) == 2 and all(row["decision"] == "cloud_blocked" for row in log)
    assert all(CNIC not in json.dumps(row) for row in log)
    assert any("[NATIONAL_ID]" in row["masked_preview"] for row in log)


def test_document_upload_and_grounded_answer(client, root):
    user = make_user(client, root)
    text = ("Overfitting happens when a model memorises training data. " * 20).encode()
    files = {"file": ("notes.txt", text, "text/plain")}
    doc = client.post("/api/documents", files=files, data={"label": "public"}, headers=user)
    assert doc.status_code == 201 and doc.json()["n_chunks"] >= 1
    bad = client.post("/api/documents", files={"file": ("x.docx", b"abc", "application/octet-stream")}, headers=user)
    assert bad.status_code == 422

    session = client.post("/api/chat/sessions", json={"document_ids": [doc.json()["id"]]}, headers=user).json()
    done = sse_events(
        client.post(f"/api/chat/sessions/{session['id']}/messages", json={"content": "What is overfitting?"}, headers=user)
    )[-1]
    assert done["meta"]["status"] == "ok" and done["meta"]["sources"][0]["document"] == "notes.txt"

    other = make_user(client, root, email="other@test.local")
    stolen = client.post("/api/chat/sessions", json={"document_ids": [doc.json()["id"]]}, headers=other)
    assert stolen.status_code == 404


# ----------------------------------------------------------------- router API


def api_key(client, headers, **body) -> dict:
    created = client.post("/api/keys", json={"name": "backend", **body}, headers=headers).json()
    assert created["key"].startswith("sr-")
    return {"Authorization": f"Bearer {created['key']}"}


def test_router_api_non_streaming_and_streaming(client, root):
    user = make_user(client, root)
    key = api_key(client, user)
    body = {"model": "smartroute/auto", "messages": [{"role": "system", "content": "Be brief."}, {"role": "user", "content": HARD}]}

    response = client.post("/v1/chat/completions", json=body, headers=key)
    assert response.status_code == 200
    data = response.json()
    assert data["object"] == "chat.completion" and data["model"] == "mock-strong"
    assert data["choices"][0]["message"]["content"] and data["usage"]["total_tokens"] > 0
    assert data["smartroute"]["event_id"] == response.headers["x-smartroute-event-id"]
    # The caller's system prompt is forwarded instead of SmartRoute's own.
    assert MockProvider.dispatched[-1]["messages"][0] == {"role": "system", "content": "Be brief."}

    streamed = client.post("/v1/chat/completions", json={**body, "stream": True, "smartroute": {"cache": False}}, headers=key)
    chunks = sse_events(streamed)
    assert streamed.text.rstrip().endswith("data: [DONE]")
    assert chunks[-1]["choices"][0]["finish_reason"] == "stop" and chunks[-1]["usage"]["completion_tokens"] > 0
    assert "".join(c["choices"][0]["delta"].get("content", "") for c in chunks).strip()

    assert "smartroute/auto" in [m["id"] for m in client.get("/v1/models", headers=key).json()["data"]]
    rating = {"event_id": data["smartroute"]["event_id"], "correctness": 4, "relevance": 4, "completeness": 4, "usefulness": 4}
    assert client.post("/v1/feedback", json=rating, headers=key).json()["quality"] == 0.75


def test_router_api_privacy_controls(client, root):
    user = make_user(client, root)
    key = api_key(client, user)
    confidential = {"messages": [{"role": "user", "content": f"{HARD} CNIC {CNIC}"}]}

    # Confidential content is answered locally, not sent to the developer's cloud key.
    data = client.post("/v1/chat/completions", json=confidential, headers=key).json()
    assert data["model"] == "mock-local" and MockProvider.dispatched == []

    # With no local model the API refuses with a privacy error instead of using cloud.
    client.patch(f"/api/models/{model_id(client, root, 'mock-local')}", json={"enabled": False}, headers=root)
    refused = client.post("/v1/chat/completions", json=confidential, headers=key)
    assert refused.status_code == 403 and refused.json()["error"]["type"] == "privacy_policy_block"
    assert MockProvider.dispatched == []
    client.patch(f"/api/models/{model_id(client, root, 'mock-local')}", json={"enabled": True}, headers=root)

    # Consent alone is not enough; the superadmin must permit the user.
    with_consent = {**confidential, "model": "mock-strong", "smartroute": {"consent": True}}
    assert client.post("/v1/chat/completions", json=with_consent, headers=key).status_code == 403
    client.patch(f"/api/users/{user['x-user-id']}", json={"allow_confidential_cloud": True}, headers=root)
    allowed = client.post("/v1/chat/completions", json=with_consent, headers=key)
    assert allowed.status_code == 200 and len(MockProvider.dispatched) == 1
    log = client.get("/api/audit/confidential?left_boundary=true", headers=root).json()
    assert len(log) == 1 and log[0]["destination_model"] == "mock-strong" and log[0]["source"] == "api"


def test_local_only_key_cannot_be_loosened_and_revoked_key_stops_working(client, root):
    user = make_user(client, root)
    key = api_key(client, user, default_privacy_mode="local_only")
    body = {"messages": [{"role": "user", "content": HARD}], "smartroute": {"privacy_mode": "cloud_allowed"}}
    data = client.post("/v1/chat/completions", json=body, headers=key).json()
    assert data["model"] == "mock-local" and MockProvider.dispatched == []

    key_id = client.get("/api/keys", headers=user).json()[0]["id"]
    assert client.delete(f"/api/keys/{key_id}", headers=user).status_code == 204
    assert client.post("/v1/chat/completions", json=body, headers=key).status_code == 401


def test_pinning_can_be_disabled_by_the_superadmin(client, root):
    user = make_user(client, root)
    key = api_key(client, user)
    policy = client.get("/api/policy", headers=root).json()
    policy["users_may_pin_model"] = False
    client.put("/api/policy", json=policy, headers=root)
    body = {"model": "mock-strong", "messages": [{"role": "user", "content": "hi"}]}
    assert client.post("/v1/chat/completions", json=body, headers=key).status_code == 403


def test_analytics_summary(client, root):
    user = make_user(client, root)
    session = client.post("/api/chat/sessions", json={}, headers=user).json()
    client.post(f"/api/chat/sessions/{session['id']}/messages", json={"content": HARD}, headers=user)
    client.post(f"/api/chat/sessions/{session['id']}/messages", json={"content": "What is a token?"}, headers=user)
    mine = client.get("/api/analytics/summary", headers=user).json()
    assert mine["measured"]["requests"] == 2 and mine["measured"]["local_share"] == 0.5
    assert mine["estimated"]["reference_model"] == "mock-strong"
    assert 0 < mine["estimated"]["saving_vs_strong_only"] < 1
    assert client.get("/api/analytics/summary?scope=all", headers=user).status_code == 403
    assert client.get("/api/analytics/summary?scope=all", headers=root).json()["measured"]["requests"] == 2
    assert len(client.get("/api/analytics/events", headers=user).json()) == 2
