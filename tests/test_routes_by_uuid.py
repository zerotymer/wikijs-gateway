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


def _mock() -> AsyncMock:
    """Wiki.js client mock whose uuid lookup finds nothing unless a test says so."""
    mock = AsyncMock()
    mock.find_paths_by_uuid.return_value = []
    return mock


def _setup(mock_client):
    from app.config import get_settings
    app.dependency_overrides[get_settings] = lambda: Settings(**TEST_ENV)
    app.dependency_overrides[get_wikijs_client] = lambda: mock_client
    return TestClient(app)


def _teardown():
    app.dependency_overrides.clear()


def test_by_uuid_both_locales():
    mock = _mock()
    mock.get_page_by_path.side_effect = lambda path, locale: (
        _page(locale) if locale in ("en", "ko") else None
    )
    client = _setup(mock)
    try:
        resp = client.get(f"/api/v2/documents/{_UUID}", params={"type": "skill"})
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
    mock = _mock()
    mock.get_page_by_path.side_effect = lambda path, locale: (
        _page("en") if locale == "en" else None
    )
    client = _setup(mock)
    try:
        resp = client.get(f"/api/v2/documents/{_UUID}", params={"type": "skill"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["pages"]["en"] is not None
        assert data["pages"]["ko"] is None
    finally:
        _teardown()


def test_by_uuid_neither_exists_returns_404():
    mock = _mock()
    mock.get_page_by_path.return_value = None
    client = _setup(mock)
    try:
        resp = client.get(f"/api/v2/documents/{_UUID}", params={"type": "skill"})
        assert resp.status_code == 404
        assert resp.json()["type"] == "urn:wikijs-gateway:problem:page-not-found"
        assert resp.json()["uuid"] == _UUID
    finally:
        _teardown()


def test_by_uuid_without_type():
    """type 생략 시 search fallback이 prefix/uuid 경로를 찾아 type을 복원한다"""
    mock = _mock()
    mock.find_paths_by_uuid.return_value = [f"skill/{_UUID}"]
    mock.get_page_by_path.side_effect = lambda path, locale: (
        _page(locale) if locale == "en" else None
    )
    client = _setup(mock)
    try:
        resp = client.get(f"/api/v2/documents/{_UUID}", params={})
        assert resp.status_code == 200
        data = resp.json()
        assert data["type"] == "skill"
        mock.find_paths_by_uuid.assert_called_once_with(_UUID, "")
        mock.get_page_by_path.assert_any_call(f"skill/{_UUID}", "en")
    finally:
        _teardown()


def test_by_uuid_without_type_bare_path():
    """type 생략 + search가 bare uuid 경로를 반환하면 type은 None"""
    mock = _mock()
    mock.find_paths_by_uuid.return_value = [_UUID]
    mock.get_page_by_path.side_effect = lambda path, locale: (
        _page(locale, path=_UUID) if locale == "en" else None
    )
    client = _setup(mock)
    try:
        resp = client.get(f"/api/v2/documents/{_UUID}", params={})
        assert resp.status_code == 200
        data = resp.json()
        assert data["type"] is None
        mock.get_page_by_path.assert_any_call(_UUID, "en")
    finally:
        _teardown()


def test_by_uuid_without_type_search_not_found():
    """type 생략 + search 결과 없음 → bare uuid 시도 → PAGE_NOT_FOUND"""
    mock = _mock()
    mock.find_paths_by_uuid.return_value = []
    mock.get_page_by_path.return_value = None
    client = _setup(mock)
    try:
        resp = client.get(f"/api/v2/documents/{_UUID}", params={})
        assert resp.status_code == 404
        assert resp.json()["type"] == "urn:wikijs-gateway:problem:page-not-found"
        assert resp.json()["uuid"] == _UUID
    finally:
        _teardown()


def test_by_uuid_wikijs_error_propagates():
    mock = _mock()
    mock.get_page_by_path.side_effect = WikiJsError([{"message": "forbidden"}])
    client = _setup(mock)
    try:
        resp = client.get(f"/api/v2/documents/{_UUID}", params={"type": "skill"})
        assert resp.status_code == 502
        assert resp.json()["type"] == "urn:wikijs-gateway:problem:wikijs-error"
    finally:
        _teardown()


def test_by_uuid_network_error_propagates():
    mock = _mock()
    mock.get_page_by_path.side_effect = httpx.ConnectError("refused")
    client = _setup(mock)
    try:
        resp = client.get(f"/api/v2/documents/{_UUID}", params={"type": "skill"})
        assert resp.status_code == 502
        assert resp.json()["type"] == "urn:wikijs-gateway:problem:wikijs-unreachable"
    finally:
        _teardown()


def test_by_uuid_ambiguous_case_variants_returns_409():
    """Issue #19 A1: several case-insensitive matches → error, never a guess."""
    mock = _mock()
    paths = [f"skill/{_UUID.upper()}", f"skill/{_UUID}"]
    mock.find_paths_by_uuid.return_value = paths
    client = _setup(mock)
    try:
        resp = client.get(f"/api/v2/documents/{_UUID[:8].upper()}{_UUID[8:]}")
        assert resp.status_code == 409
        body = resp.json()
        assert body["type"] == "urn:wikijs-gateway:problem:ambiguous-uuid"
        assert body["candidates"] == paths
        mock.get_page_by_path.assert_not_called()
    finally:
        _teardown()


def test_by_uuid_lowercase_resolves_to_stored_path():
    """Issue #19 A1: lowercase query + type uses the stored (uppercase) path."""
    stored = f"skill/{_UUID.upper()}"
    mock = _mock()
    mock.find_paths_by_uuid.return_value = [stored]
    mock.get_page_by_path.side_effect = lambda path, locale: _page(locale, path=stored)
    client = _setup(mock)
    try:
        resp = client.get(f"/api/v2/documents/{_UUID}", params={"type": "skill"})
        assert resp.status_code == 200
        assert resp.json()["type"] == "skill"
        mock.find_paths_by_uuid.assert_called_once_with(_UUID, "skill")
        mock.get_page_by_path.assert_any_call(stored, "en")
    finally:
        _teardown()
