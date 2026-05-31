import httpx
import pytest
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import app, get_wikijs_client
from app.models import PageResponse
from app.wikijs_client import WikiJsError

TEST_ENV = {
    "wikijs_graphql_url": "http://wiki:3000/graphql",
    "wikijs_api_token": "wiki-token",
    "gateway_admin_token": "test-admin-token",
}

_UUID = "550e8400-e29b-41d4-a716-446655440000"


def _page(locale: str, path: str = f"skill/{_UUID}") -> PageResponse:
    return PageResponse(
        id=10 if locale == "en" else 11,
        path=path,
        locale=locale,
        title=f"Test Page ({locale})",
        description="desc",
        content="# Hello",
        editor="markdown",
        isPublished=True,
        isPrivate=False,
        updatedAt="2026-05-31T00:00:00.000Z",
        contentHash="abc123",
        tags=[],
    )


def _setup(mock_client):
    from app.config import get_settings
    app.dependency_overrides[get_settings] = lambda: Settings(**TEST_ENV)
    app.dependency_overrides[get_wikijs_client] = lambda: mock_client
    return TestClient(app)


def _teardown():
    app.dependency_overrides.clear()


def test_by_uuid_both_locales():
    mock = AsyncMock()
    mock.get_page_by_path.side_effect = lambda path, locale: (
        _page(locale) if locale in ("en", "ko") else None
    )
    client = _setup(mock)
    try:
        resp = client.get("/pages/by-uuid", params={"uuid": _UUID, "type": "skill"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["uuid"] == _UUID
        assert data["type"] == "skill"
        assert data["pages"]["en"]["locale"] == "en"
        assert data["pages"]["ko"]["locale"] == "ko"
        mock.get_page_by_path.assert_any_call(f"skill/{_UUID}", "en")
        mock.get_page_by_path.assert_any_call(f"skill/{_UUID}", "ko")
    finally:
        _teardown()


def test_by_uuid_only_en_exists():
    mock = AsyncMock()
    mock.get_page_by_path.side_effect = lambda path, locale: (
        _page("en") if locale == "en" else None
    )
    client = _setup(mock)
    try:
        resp = client.get("/pages/by-uuid", params={"uuid": _UUID, "type": "skill"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["pages"]["en"] is not None
        assert data["pages"]["ko"] is None
    finally:
        _teardown()


def test_by_uuid_neither_exists_returns_404():
    mock = AsyncMock()
    mock.get_page_by_path.return_value = None
    client = _setup(mock)
    try:
        resp = client.get("/pages/by-uuid", params={"uuid": _UUID, "type": "skill"})
        assert resp.status_code == 404
        assert resp.json()["detail"]["error"] == "PAGE_NOT_FOUND"
        assert resp.json()["detail"]["uuid"] == _UUID
    finally:
        _teardown()


def test_by_uuid_without_type():
    """type 생략 시 path = uuid 단독 사용"""
    mock = AsyncMock()
    mock.get_page_by_path.side_effect = lambda path, locale: (
        _page(locale, path=_UUID) if locale == "en" else None
    )
    client = _setup(mock)
    try:
        resp = client.get("/pages/by-uuid", params={"uuid": _UUID})
        assert resp.status_code == 200
        data = resp.json()
        assert data["type"] is None
        mock.get_page_by_path.assert_any_call(_UUID, "en")
    finally:
        _teardown()


def test_by_uuid_wikijs_error_propagates():
    mock = AsyncMock()
    mock.get_page_by_path.side_effect = WikiJsError([{"message": "forbidden"}])
    client = _setup(mock)
    try:
        resp = client.get("/pages/by-uuid", params={"uuid": _UUID, "type": "skill"})
        assert resp.status_code == 502
        assert resp.json()["detail"]["error"] == "WIKIJS_ERROR"
    finally:
        _teardown()


def test_by_uuid_network_error_propagates():
    mock = AsyncMock()
    mock.get_page_by_path.side_effect = httpx.ConnectError("refused")
    client = _setup(mock)
    try:
        resp = client.get("/pages/by-uuid", params={"uuid": _UUID, "type": "skill"})
        assert resp.status_code == 502
        assert resp.json()["detail"]["error"] == "WIKIJS_UNREACHABLE"
    finally:
        _teardown()
