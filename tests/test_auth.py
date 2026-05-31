from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.locking import compute_hash
from app.main import app, get_wikijs_client
from app.models import PageResponse

READ_TOKEN = "read-token-abc"
ADMIN_TOKEN = "admin-token-xyz"

_CONTENT = "# Hello\n\n<!-- agent:start x -->\nold\n<!-- agent:end x -->\n"
_UPDATED_AT = "2026-05-31T00:00:00.000Z"
_PAGE_ID = 1

_SAMPLE_PAGE = PageResponse(
    id=_PAGE_ID,
    path="/agent/test",
    locale="ko",
    title="Test",
    description="",
    content=_CONTENT,
    editor="markdown",
    isPublished=True,
    isPrivate=False,
    updatedAt=_UPDATED_AT,
    contentHash=compute_hash(_PAGE_ID, _UPDATED_AT, _CONTENT),
    tags=[],
)

_VALID_HASH = compute_hash(_PAGE_ID, _UPDATED_AT, _CONTENT)


def _settings(**overrides):
    base = {
        "wikijs_graphql_url": "http://wiki:3000/graphql",
        "wikijs_api_token": "wiki-read-token",
        "wikijs_admin_api_token": "wiki-admin-token",
        "gateway_token": READ_TOKEN,
        "gateway_admin_token": ADMIN_TOKEN,
        "gateway_mode": "dry_run",
        "default_locale": "ko",
        "allow_path_prefixes": "/agent,/draft",
    }
    base.update(overrides)
    return Settings(**base)


@pytest.fixture()
def client():
    mock = AsyncMock()
    mock.ping.return_value = True
    mock.get_page_by_path.return_value = _SAMPLE_PAGE
    app.dependency_overrides[get_settings] = lambda: _settings()
    app.dependency_overrides[get_wikijs_client] = lambda: mock
    yield TestClient(app), mock
    app.dependency_overrides.clear()


# ---- 읽기 엔드포인트 (/health) ----

def test_read_endpoint_with_read_token_returns_200(client):
    tc, _ = client
    resp = tc.get("/health", headers={"Authorization": f"Bearer {READ_TOKEN}"})
    assert resp.status_code == 200


def test_read_endpoint_with_admin_token_returns_403(client):
    tc, _ = client
    resp = tc.get("/health", headers={"Authorization": f"Bearer {ADMIN_TOKEN}"})
    assert resp.status_code == 403


def test_read_endpoint_without_token_returns_401(client):
    tc, _ = client
    resp = tc.get("/health")
    assert resp.status_code == 401


# ---- 쓰기 엔드포인트 (/pages/dry-run) ----

_DRY_RUN_BODY = {
    "path": "/agent/test",
    "locale": "ko",
    "baseHash": _VALID_HASH,
    "operation": {
        "type": "replace_between_markers",
        "name": "x",
        "content": "new content",
    },
}


def test_write_endpoint_with_admin_token_returns_200(client):
    tc, _ = client
    resp = tc.post(
        "/pages/dry-run",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
        json=_DRY_RUN_BODY,
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_write_endpoint_with_read_token_returns_403(client):
    tc, _ = client
    resp = tc.post(
        "/pages/dry-run",
        headers={"Authorization": f"Bearer {READ_TOKEN}"},
        json=_DRY_RUN_BODY,
    )
    assert resp.status_code == 403


def test_write_endpoint_without_token_returns_401(client):
    tc, _ = client
    resp = tc.post("/pages/dry-run", json=_DRY_RUN_BODY)
    assert resp.status_code == 401
