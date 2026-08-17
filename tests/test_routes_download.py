import httpx
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import app, get_wikijs_client
from app.models import PageResponse
from app.wikijs_client import WikiJsError

TEST_ENV = {
    "wikijs_graphql_url": "http://wiki:3000/graphql",
    "wikijs_api_token": "wiki-token",
    "gateway_admin_token": "test-admin-token",
}

_UUID = "550e8400-e29b-41d4-a716-446655440000"
_CONTENT = "# Skill\n\n본문 내용\n"


def _page(locale: str, path: str = f"skill/{_UUID}") -> PageResponse:
    return PageResponse(
        id=10 if locale == "en" else 11,
        path=path,
        locale=locale,
        title=f"Test Page ({locale})",
        description="desc",
        content=_CONTENT,
        editor="markdown",
        isPublished=True,
        isPrivate=False,
        updatedAt="2026-08-17T00:00:00.000Z",
        contentHash="abc123",
        tags=[],
    )


def _setup(mock_client):
    app.dependency_overrides[get_settings] = lambda: Settings(**TEST_ENV)
    app.dependency_overrides[get_wikijs_client] = lambda: mock_client
    return TestClient(app)


def _teardown():
    app.dependency_overrides.clear()


def test_download_defaults_to_type_uppercase_and_ko():
    mock = AsyncMock()
    mock.get_page_by_path.side_effect = lambda path, locale: _page(locale)
    client = _setup(mock)
    try:
        resp = client.get("/pages/download", params={"uuid": _UUID, "type": "skill"})
        assert resp.status_code == 200
        assert resp.text == _CONTENT
        assert resp.headers["content-type"] == "text/markdown; charset=utf-8"
        assert resp.headers["content-disposition"] == 'attachment; filename="SKILL.md"'
        mock.get_page_by_path.assert_called_once_with(f"skill/{_UUID}", "ko")
    finally:
        _teardown()


def test_download_locale_selects_content_but_not_filename():
    mock = AsyncMock()
    mock.get_page_by_path.side_effect = lambda path, locale: _page(locale)
    client = _setup(mock)
    try:
        resp = client.get(
            "/pages/download", params={"uuid": _UUID, "type": "skill", "locale": "en"}
        )
        assert resp.status_code == 200
        # locale never leaks into the filename — the caller renames via `filename`
        assert resp.headers["content-disposition"] == 'attachment; filename="SKILL.md"'
        mock.get_page_by_path.assert_called_once_with(f"skill/{_UUID}", "en")
    finally:
        _teardown()


def test_download_explicit_filename():
    mock = AsyncMock()
    mock.get_page_by_path.side_effect = lambda path, locale: _page(locale)
    client = _setup(mock)
    try:
        resp = client.get(
            "/pages/download", params={"uuid": _UUID, "type": "skill", "filename": "SKILL_ko"}
        )
        assert resp.status_code == 200
        assert resp.headers["content-disposition"] == 'attachment; filename="SKILL_ko.md"'
    finally:
        _teardown()


def test_download_filename_with_md_suffix_is_not_doubled():
    mock = AsyncMock()
    mock.get_page_by_path.side_effect = lambda path, locale: _page(locale)
    client = _setup(mock)
    try:
        resp = client.get(
            "/pages/download",
            params={"uuid": _UUID, "type": "skill", "filename": "SKILL_ko.md"},
        )
        assert resp.status_code == 200
        assert resp.headers["content-disposition"] == 'attachment; filename="SKILL_ko.md"'
    finally:
        _teardown()


def test_download_resolves_type_without_type_param():
    mock = AsyncMock()
    mock.find_path_by_uuid.return_value = f"skill/{_UUID}"
    mock.get_page_by_path.side_effect = lambda path, locale: _page(locale)
    client = _setup(mock)
    try:
        resp = client.get("/pages/download", params={"uuid": _UUID})
        assert resp.status_code == 200
        assert resp.headers["content-disposition"] == 'attachment; filename="SKILL.md"'
        mock.find_path_by_uuid.assert_called_once_with(_UUID)
    finally:
        _teardown()


def test_download_unresolved_type_falls_back_to_noname():
    mock = AsyncMock()
    mock.find_path_by_uuid.return_value = _UUID  # bare uuid path, no prefix
    mock.get_page_by_path.side_effect = lambda path, locale: _page(locale, path=_UUID)
    client = _setup(mock)
    try:
        resp = client.get("/pages/download", params={"uuid": _UUID})
        assert resp.status_code == 200
        assert resp.headers["content-disposition"] == 'attachment; filename="noname.md"'
    finally:
        _teardown()


def test_download_rejects_unsafe_filenames():
    mock = AsyncMock()
    mock.get_page_by_path.side_effect = lambda path, locale: _page(locale)
    client = _setup(mock)
    try:
        for bad in ['a"; x', "../etc/passwd", "a/b", "sk\nill", "한글", "x" * 65, ".md"]:
            resp = client.get(
                "/pages/download",
                params={"uuid": _UUID, "type": "skill", "filename": bad},
            )
            assert resp.status_code == 422, bad
            assert resp.json()["detail"]["error"] == "INVALID_FILENAME", bad
        mock.get_page_by_path.assert_not_called()
    finally:
        _teardown()


def test_download_rejects_unsafe_type_derived_filename():
    """A wiki path prefix that is not header-safe falls back instead of leaking."""
    mock = AsyncMock()
    mock.find_path_by_uuid.return_value = f'a"/b/{_UUID}'
    mock.get_page_by_path.side_effect = lambda path, locale: _page(locale, path=path)
    client = _setup(mock)
    try:
        resp = client.get("/pages/download", params={"uuid": _UUID})
        assert resp.status_code == 200
        assert resp.headers["content-disposition"] == 'attachment; filename="noname.md"'
    finally:
        _teardown()


def test_download_missing_page_returns_404():
    mock = AsyncMock()
    mock.get_page_by_path.return_value = None
    client = _setup(mock)
    try:
        resp = client.get("/pages/download", params={"uuid": _UUID, "type": "skill"})
        assert resp.status_code == 404
        assert resp.json()["detail"]["error"] == "PAGE_NOT_FOUND"
        assert resp.json()["detail"]["locale"] == "ko"
    finally:
        _teardown()


def test_download_wikijs_error_propagates():
    mock = AsyncMock()
    mock.get_page_by_path.side_effect = WikiJsError([{"message": "forbidden"}])
    client = _setup(mock)
    try:
        resp = client.get("/pages/download", params={"uuid": _UUID, "type": "skill"})
        assert resp.status_code == 502
        assert resp.json()["detail"]["error"] == "WIKIJS_ERROR"
    finally:
        _teardown()


def test_download_network_error_propagates():
    mock = AsyncMock()
    mock.get_page_by_path.side_effect = httpx.ConnectError("refused")
    client = _setup(mock)
    try:
        resp = client.get("/pages/download", params={"uuid": _UUID, "type": "skill"})
        assert resp.status_code == 502
        assert resp.json()["detail"]["error"] == "WIKIJS_UNREACHABLE"
    finally:
        _teardown()


def test_download_not_exposed_as_mcp_tool():
    from app.main import mcp

    names = {t.name for t in mcp.tools}
    assert "download_page" not in names
    assert "get_page_by_uuid" in names
