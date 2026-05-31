from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import app, get_wikijs_client
from app.models import PageResponse
from app.wikijs_client import WikiJsError

TOKEN = "test-token-abc"

TEST_ENV = {
    "wikijs_graphql_url": "http://wiki:3000/graphql",
    "wikijs_api_token": "wiki-token",
    "gateway_token": TOKEN,
    "gateway_mode": "read_only",
    "default_locale": "ko",
}

_SAMPLE_PAGE = PageResponse(
    id=42,
    path="agent/test-page",
    locale="ko",
    title="테스트 페이지",
    description="설명",
    content="# Hello",
    editor="markdown",
    isPublished=True,
    isPrivate=False,
    updatedAt="2026-05-31T00:00:00.000Z",
    contentHash="abc123",
    tags=["agent"],
)


def _setup(mock_client):
    app.dependency_overrides[get_settings] = lambda: Settings(**TEST_ENV)
    app.dependency_overrides[get_wikijs_client] = lambda: mock_client
    return TestClient(app)


def _teardown():
    app.dependency_overrides.clear()


def test_get_page_by_path_success():
    mock = AsyncMock()
    mock.get_page_by_path.return_value = _SAMPLE_PAGE
    client = _setup(mock)
    try:
        resp = client.get(
            "/pages/by-path",
            params={"path": "agent/test-page"},
            headers={"Authorization": f"Bearer {TOKEN}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == 42
        assert data["path"] == "agent/test-page"
        assert data["contentHash"] == "abc123"
    finally:
        _teardown()


def test_get_page_by_path_uses_default_locale():
    mock = AsyncMock()
    mock.get_page_by_path.return_value = _SAMPLE_PAGE
    client = _setup(mock)
    try:
        client.get(
            "/pages/by-path",
            params={"path": "agent/test-page"},
            headers={"Authorization": f"Bearer {TOKEN}"},
        )
        mock.get_page_by_path.assert_called_once_with("agent/test-page", "ko")
    finally:
        _teardown()


def test_get_page_by_path_not_found():
    mock = AsyncMock()
    mock.get_page_by_path.return_value = None
    client = _setup(mock)
    try:
        resp = client.get(
            "/pages/by-path",
            params={"path": "nonexistent"},
            headers={"Authorization": f"Bearer {TOKEN}"},
        )
        assert resp.status_code == 404
        assert resp.json()["detail"]["error"] == "PAGE_NOT_FOUND"
    finally:
        _teardown()


def test_get_page_by_path_wikijs_error():
    mock = AsyncMock()
    mock.get_page_by_path.side_effect = WikiJsError([{"message": "PageViewForbidden"}])
    client = _setup(mock)
    try:
        resp = client.get(
            "/pages/by-path",
            params={"path": "some/page"},
            headers={"Authorization": f"Bearer {TOKEN}"},
        )
        assert resp.status_code == 502
        assert resp.json()["detail"]["error"] == "WIKIJS_ERROR"
    finally:
        _teardown()


def test_get_page_by_path_network_error():
    import httpx

    mock = AsyncMock()
    mock.get_page_by_path.side_effect = httpx.ConnectError("refused")
    client = _setup(mock)
    try:
        resp = client.get(
            "/pages/by-path",
            params={"path": "some/page"},
            headers={"Authorization": f"Bearer {TOKEN}"},
        )
        assert resp.status_code == 502
        assert resp.json()["detail"]["error"] == "WIKIJS_UNREACHABLE"
    finally:
        _teardown()


def test_get_page_by_path_no_auth():
    mock = AsyncMock()
    app.dependency_overrides[get_settings] = lambda: Settings(**TEST_ENV)
    app.dependency_overrides[get_wikijs_client] = lambda: mock
    try:
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/pages/by-path", params={"path": "some/page"})
        assert resp.status_code == 401
    finally:
        _teardown()
