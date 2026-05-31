from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.locking import compute_hash
from app.main import app, get_wikijs_client
from app.models import PageResponse
from app.wikijs_client import WikiJsError

TOKEN = "test-token-abc"

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

_WIKIJS_UPDATE_RESULT = {
    "responseResult": {"succeeded": True, "errorCode": 0, "message": ""},
    "page": {"id": _PAGE_ID, "path": "/agent/page1", "title": "Example", "updatedAt": _UPDATED_AT},
}

_WIKIJS_CREATE_RESULT = {
    "responseResult": {"succeeded": True, "errorCode": 0, "message": ""},
    "page": {"id": 99, "path": "/agent/new-page", "title": "New Page", "updatedAt": _UPDATED_AT},
}


def _settings(**overrides):
    base = {
        "wikijs_graphql_url": "http://wiki:3000/graphql",
        "wikijs_api_token": "wiki-token",
        "gateway_token": TOKEN,
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


# ---- bulk operations ----

def test_bulk_mixed_dry_run_mode(tmp_path):
    """dry_run mode: upsert → MODE_NOT_ALLOWED, patch-section → ok (dry), dry-run → ok."""
    mock = AsyncMock()
    mock.get_page_by_path.return_value = _SAMPLE_PAGE
    client = _setup(mock, gateway_mode="dry_run", audit_dir=str(tmp_path))
    try:
        resp = client.post(
            "/pages/bulk",
            headers={"Authorization": f"Bearer {TOKEN}"},
            json={
                "operations": [
                    {
                        "id": "op-u",
                        "type": "upsert",
                        "path": "/agent/page1",
                        "locale": "ko",
                        "title": "Title",
                        "content": "# Content",
                    },
                    {
                        "id": "op-p",
                        "type": "patch-section",
                        "path": "/agent/page1",
                        "locale": "ko",
                        "baseHash": _VALID_HASH,
                        "operation": {"type": "replace_between_markers", "name": "x", "content": "new"},
                    },
                    {
                        "id": "op-d",
                        "type": "dry-run",
                        "path": "/agent/page1",
                        "locale": "ko",
                        "baseHash": _VALID_HASH,
                        "operation": {"type": "replace_between_markers", "name": "x", "content": "new2"},
                    },
                ]
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        results = {r["id"]: r for r in data["results"]}

        assert results["op-u"]["ok"] is False
        assert results["op-u"]["error"] == "MODE_NOT_ALLOWED"

        assert results["op-p"]["ok"] is True
        assert results["op-p"]["result"]["mode"] == "dry_run"
        mock.update_page.assert_not_called()

        assert results["op-d"]["ok"] is True
        assert results["op-d"]["result"]["mode"] == "dry_run"

        assert data["summary"]["succeeded"] == 2
        assert data["summary"]["failed"] == 1
    finally:
        _teardown()


def test_bulk_write_mode_partial_fail(tmp_path):
    """write mode: correct hash succeeds, stale hash returns PAGE_CHANGED."""
    mock = AsyncMock()
    mock.get_page_by_path.return_value = _SAMPLE_PAGE
    mock.update_page.return_value = _WIKIJS_UPDATE_RESULT
    client = _setup(mock, gateway_mode="write", audit_dir=str(tmp_path))
    try:
        resp = client.post(
            "/pages/bulk",
            headers={"Authorization": f"Bearer {TOKEN}"},
            json={
                "operations": [
                    {
                        "id": "op-ok",
                        "type": "patch-section",
                        "path": "/agent/page1",
                        "locale": "ko",
                        "baseHash": _VALID_HASH,
                        "operation": {"type": "replace_between_markers", "name": "x", "content": "new"},
                    },
                    {
                        "id": "op-stale",
                        "type": "patch-section",
                        "path": "/agent/page1",
                        "locale": "ko",
                        "baseHash": "stale-hash-does-not-match",
                        "operation": {"type": "replace_between_markers", "name": "x", "content": "new"},
                    },
                ]
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        results = {r["id"]: r for r in data["results"]}

        assert results["op-ok"]["ok"] is True
        assert results["op-stale"]["ok"] is False
        assert results["op-stale"]["error"] == "PAGE_CHANGED"
        assert "currentHash" in results["op-stale"]

        assert data["summary"]["succeeded"] == 1
        assert data["summary"]["failed"] == 1
    finally:
        _teardown()


def test_bulk_write_mode_path_not_allowed(tmp_path):
    """upsert on a path outside allowlist → PATH_NOT_ALLOWED per item."""
    mock = AsyncMock()
    mock.upsert_page.return_value = (_WIKIJS_CREATE_RESULT, True)
    client = _setup(mock, gateway_mode="write", audit_dir=str(tmp_path))
    try:
        resp = client.post(
            "/pages/bulk",
            headers={"Authorization": f"Bearer {TOKEN}"},
            json={
                "operations": [
                    {
                        "id": "op-denied",
                        "type": "upsert",
                        "path": "/private/secret",
                        "locale": "ko",
                        "title": "Secret",
                        "content": "# Secret",
                    },
                ]
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        result = data["results"][0]
        assert result["ok"] is False
        assert result["error"] == "PATH_NOT_ALLOWED"
        mock.upsert_page.assert_not_called()
    finally:
        _teardown()


def test_bulk_read_only_rejects_write():
    """read_only mode: upsert item → MODE_NOT_ALLOWED, overall request succeeds (200)."""
    mock = AsyncMock()
    client = _setup(mock, gateway_mode="read_only")
    try:
        resp = client.post(
            "/pages/bulk",
            headers={"Authorization": f"Bearer {TOKEN}"},
            json={
                "operations": [
                    {
                        "id": "op-u",
                        "type": "upsert",
                        "path": "/agent/page1",
                        "locale": "ko",
                        "title": "Title",
                        "content": "# Content",
                    },
                ]
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["results"][0]["ok"] is False
        assert data["results"][0]["error"] == "MODE_NOT_ALLOWED"
        assert data["summary"]["failed"] == 1
    finally:
        _teardown()


def test_bulk_too_large():
    """operations exceeding batch_max_size → 422 BATCH_TOO_LARGE."""
    mock = AsyncMock()
    client = _setup(mock, batch_max_size="3")
    try:
        resp = client.post(
            "/pages/bulk",
            headers={"Authorization": f"Bearer {TOKEN}"},
            json={
                "operations": [
                    {
                        "id": f"op-{i}",
                        "type": "upsert",
                        "path": f"/agent/p{i}",
                        "locale": "ko",
                        "title": f"T{i}",
                        "content": "# C",
                    }
                    for i in range(4)
                ]
            },
        )
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert detail["error"] == "BATCH_TOO_LARGE"
        assert detail["received"] == 4
        assert detail["limit"] == 3
    finally:
        _teardown()
