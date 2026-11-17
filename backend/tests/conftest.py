"""Test setup: in-memory SQLite, mock models only, regex-only privacy scanner.
No model, dataset or network access is needed to run these tests."""

import os

os.environ["SMARTROUTE_ENV"] = "development"
os.environ["SMARTROUTE_DATABASE_URL"] = "sqlite://"
os.environ["SMARTROUTE_BOOTSTRAP_ADMIN_EMAIL"] = "root@test.local"
os.environ["SMARTROUTE_BOOTSTRAP_ADMIN_PASSWORD"] = "root-password-1"
os.environ["SMARTROUTE_SEED_MOCK_MODELS"] = "true"
os.environ["SMARTROUTE_RATE_LIMIT_RPM"] = "100000"
os.environ["SMARTROUTE_OCR_BACKEND"] = "off"  # tests install their own fake; ignore the dev .env

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.bootstrap import bootstrap  # noqa: E402
from app.core.cache import response_cache  # noqa: E402
from app.core.context import summarizer  # noqa: E402
from app.core.ocr import reset_ocr  # noqa: E402
from app.core.privacy import scanner as scanner_module  # noqa: E402
from app.core.providers.mock import MockProvider  # noqa: E402
from app.core.routing import state as learner_state  # noqa: E402
from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402

ROOT = {"email": "root@test.local", "password": "root-password-1"}


@pytest.fixture(autouse=True)
def fresh_state():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        bootstrap(db)
    response_cache.clear()
    summarizer.clear()
    summarizer.inline = True  # run summaries synchronously in tests
    reset_ocr()
    learner_state._cache.clear()
    MockProvider.reset()
    scanner_module.set_scanner(None)
    yield


@pytest.fixture
def db():
    with SessionLocal() as session:
        yield session


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def login(client, email, password) -> dict:
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def root(client) -> dict:
    return login(client, **ROOT)


def make_user(client, root_headers, email="user@test.local", role="user", password="user-password-1") -> dict:
    r = client.post(
        "/api/users", json={"email": email, "password": password, "role": role, "name": email}, headers=root_headers
    )
    assert r.status_code == 201, r.text
    headers = login(client, email, password)
    headers["x-user-id"] = r.json()["id"]
    return headers
