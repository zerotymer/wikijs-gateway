from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.locking import compute_hash
from app.main import app, get_wikijs_client
from app.models import PageResponse

TOKEN = "test-token-abc"
ADMIN_TOKEN = "test-admin-token-xyz"

_CONTENT = "# Hello\n\n<!-- agent:start x -->\nold\n<!-- agent:end x -->\n\n## Section\n\nsome content\n"
_UPDATED_AT = "2026-05-31T00:00:00.000Z"
_PAGE_ID = 42
_VALID_HASH = compute_hash(_PAGE_ID, _UPDATED_AT, _CONTENT)

_SAMPLE_PAGE = PageResponse(
    id=_PAGE_ID,
    path="/agent/page1",
    locale="ko",
    title="Example",
    description="desc",
    content=_CONTENT,
    editor="markdown",
    isPublished=True,
    isPrivate=False,
    updatedAt=_UPDATED_AT,
    contentHash=_VALID_HASH,
    tags=[],
)


def _settings(**overrides):
    base = {
        "wikijs_graphql_url": "http://wiki:3000/graphql",
        "wikijs_api_token": "wiki-token",
        "wikijs_admin_api_token": "wiki-admin-token",
        "gateway_token": TOKEN,
        "gateway_admin_token": ADMIN_TOKEN,
        "gateway_mode": "dry_run",
        "default_locale": "ko",
        "allow_path_prefixes": "/agent,/draft",
        "batch_max_size": "3",
    }
    base.update(overrides)
    return Settings(**base)


def _setup(mock_client, **setting_overrides):
    app.dependency_overrides[get_settings] = lambda: _settings(**setting_overrides)
    app.dependency_overrides[get_wikijs_client] = lambda: mock_client
    return TestClient(app)


def _teardown():
    app.dependency_overrides.clear()


# ---- by-paths ----

def test_bulk_fetch_all_found():
    mock = AsyncMock()
    mock.get_page_by_path.return_value = _SAMPLE_PAGE
    client = _setup(mock)
    try:
        resp = client.post(
            "/pages/by-paths",
            headers={"Authorization": f"Bearer {TOKEN}"},
            json={"paths": [{"path": "/agent/page1", "locale": "ko"}, {"path": "/agent/page2"}]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert len(data["results"]) == 2
        assert all(r["ok"] for r in data["results"])
        assert data["results"][0]["index"] == 0
        assert data["results"][1]["index"] == 1
        assert data["summary"] == {"total": 2, "succeeded": 2, "failed": 0}
    finally:
        _teardown()


def test_bulk_fetch_partial_not_found():
    mock = AsyncMock()
    mock.get_page_by_path.side_effect = [_SAMPLE_PAGE, None]
    client = _setup(mock)
    try:
        resp = client.post(
            "/pages/by-paths",
            headers={"Authorization": f"Bearer {TOKEN}"},
            json={"paths": [{"path": "/agent/page1"}, {"path": "/agent/missing"}]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        results = data["results"]
        assert results[0]["ok"] is True
        assert results[0]["page"] is not None
        assert results[1]["ok"] is False
        assert results[1]["error"] == "PAGE_NOT_FOUND"
        assert data["summary"] == {"total": 2, "succeeded": 1, "failed": 1}
    finally:
        _teardown()


def test_bulk_fetch_too_large():
    mock = AsyncMock()
    client = _setup(mock, batch_max_size="3")
    try:
        resp = client.post(
            "/pages/by-paths",
            headers={"Authorization": f"Bearer {TOKEN}"},
            json={"paths": [{"path": f"/agent/p{i}"} for i in range(4)]},
        )
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert detail["error"] == "BATCH_TOO_LARGE"
        assert detail["received"] == 4
        assert detail["limit"] == 3
    finally:
        _teardown()


