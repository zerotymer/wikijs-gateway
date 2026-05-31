from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.locking import compute_hash
from app.main import app, get_wikijs_client
from app.models import PageResponse
from app.wikijs_client import WikiJsError

_CONTENT = "# Hello\n\n<!-- agent:start x -->\nold\n<!-- agent:end x -->\n\n## Section\n\nsome content\n"
_UPDATED_AT = "2026-05-31T00:00:00.000Z"
_PAGE_ID = 42

_SAMPLE_PAGE = PageResponse(
    id=_PAGE_ID,
    path="/agent/example",
    locale="ko",
    title="Example",
    description="desc",
    content=_CONTENT,
    editor="markdown",
    isPublished=True,
    isPrivate=False,
    updatedAt=_UPDATED_AT,
    contentHash=compute_hash(_PAGE_ID, _UPDATED_AT, _CONTENT),
    tags=[],
)

_WIKIJS_UPDATE_RESULT = {
    "responseResult": {"succeeded": True, "errorCode": 0, "message": ""},
    "page": {"id": _PAGE_ID, "path": "/agent/example", "title": "Example", "updatedAt": _UPDATED_AT},
}

_WIKIJS_CREATE_RESULT = {
    "responseResult": {"succeeded": True, "errorCode": 0, "message": ""},
    "page": {"id": 99, "path": "/agent/new-page", "title": "New Page", "updatedAt": _UPDATED_AT},
}

_VALID_HASH = compute_hash(_PAGE_ID, _UPDATED_AT, _CONTENT)

TEST_ENV = {
    "wikijs_graphql_url": "http://wiki:3000/graphql",
    "wikijs_api_token": "wiki-token",
    "wikijs_admin_api_token": "wiki-admin-token",
}


def _setup(mock_client, tmp_path=None):
    app.dependency_overrides[get_settings] = lambda: Settings(**TEST_ENV)
    app.dependency_overrides[get_wikijs_client] = lambda: mock_client
    return TestClient(app)


def _teardown():
    app.dependency_overrides.clear()


def _mock_page_client():
    mock = AsyncMock()
    mock.get_page_by_path.return_value = _SAMPLE_PAGE
    mock.update_page.return_value = _WIKIJS_UPDATE_RESULT
    return mock


# ---- patch-section ----

def test_patch_section_calls_mutation(tmp_path):
    mock = _mock_page_client()
    client = _setup(mock, tmp_path)
    try:
        resp = client.post(
            "/pages/patch-section",
            json={
                "path": "/agent/example",
                "locale": "ko",
                "baseHash": _VALID_HASH,
                "operation": {"type": "replace_between_markers", "name": "x", "content": "new content"},
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        mock.update_page.assert_called_once()
    finally:
        _teardown()


def test_patch_section_creates_audit_file(tmp_path):
    import app.main as main_module
    original_audit_dir = main_module._AUDIT_DIR
    main_module._AUDIT_DIR = str(tmp_path)
    mock = _mock_page_client()
    client = _setup(mock)
    try:
        client.post(
            "/pages/patch-section",
            json={
                "path": "/agent/example",
                "locale": "ko",
                "baseHash": _VALID_HASH,
                "operation": {"type": "replace_between_markers", "name": "x", "content": "y"},
            },
        )
        json_files = list(tmp_path.rglob("*.json"))
        assert len(json_files) == 1
    finally:
        main_module._AUDIT_DIR = original_audit_dir
        _teardown()


def test_patch_section_page_changed(tmp_path):
    mock = AsyncMock()
    stale_page = PageResponse(**{**_SAMPLE_PAGE.model_dump(), "content": "different content"})
    mock.get_page_by_path.return_value = stale_page
    client = _setup(mock, tmp_path)
    try:
        resp = client.post(
            "/pages/patch-section",
            json={
                "path": "/agent/example",
                "locale": "ko",
                "baseHash": _VALID_HASH,
                "operation": {"type": "replace_between_markers", "name": "x", "content": "y"},
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["error"] == "PAGE_CHANGED"
        assert "currentHash" in data
    finally:
        _teardown()


# ---- upsert ----

def test_upsert_creates_new_page(tmp_path):
    mock = AsyncMock()
    mock.upsert_page.return_value = (_WIKIJS_CREATE_RESULT, True)
    client = _setup(mock, tmp_path)
    try:
        resp = client.post(
            "/pages/upsert",
            json={
                "path": "/agent/new-page",
                "locale": "ko",
                "title": "New Page",
                "content": "# New Page\n",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["created"] is True
        assert data["pageId"] == 99
    finally:
        _teardown()


def test_upsert_updates_existing_page(tmp_path):
    mock = AsyncMock()
    mock.upsert_page.return_value = (_WIKIJS_UPDATE_RESULT, False)
    client = _setup(mock, tmp_path)
    try:
        resp = client.post(
            "/pages/upsert",
            json={
                "path": "/agent/example",
                "locale": "ko",
                "title": "Example",
                "content": "# Updated\n",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["created"] is False
        assert data["pageId"] == _PAGE_ID
    finally:
        _teardown()


def test_upsert_any_path_allowed(tmp_path):
    mock = AsyncMock()
    mock.upsert_page.return_value = (_WIKIJS_CREATE_RESULT, True)
    client = _setup(mock, tmp_path)
    try:
        resp = client.post(
            "/pages/upsert",
            json={
                "path": "/private/secret",
                "locale": "ko",
                "title": "Secret",
                "content": "# Secret\n",
            },
        )
        assert resp.status_code == 200
        mock.upsert_page.assert_called_once()
    finally:
        _teardown()


def test_upsert_wikijs_error(tmp_path):
    mock = AsyncMock()
    mock.upsert_page.side_effect = WikiJsError([{"message": "InternalError"}])
    client = _setup(mock, tmp_path)
    try:
        resp = client.post(
            "/pages/upsert",
            json={
                "path": "/agent/example",
                "locale": "ko",
                "title": "Example",
                "content": "# Example\n",
            },
        )
        assert resp.status_code == 502
        assert resp.json()["detail"]["error"] == "WIKIJS_ERROR"
    finally:
        _teardown()
