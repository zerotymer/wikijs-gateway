import hashlib

import httpx
import pytest
import respx

from app.locking import compute_hash
from app.wikijs_client import WikiJsClient, WikiJsError

GRAPHQL_URL = "http://wiki:3000/graphql"
API_TOKEN = "test-wiki-token"

_SAMPLE_PAGE = {
    "id": 42,
    "path": "agent/test-page",
    "locale": "ko",
    "title": "테스트 페이지",
    "description": "설명",
    "content": "# Hello",
    "editor": "markdown",
    "isPublished": True,
    "isPrivate": False,
    "updatedAt": "2026-05-31T00:00:00.000Z",
    "scriptCss": None,
    "scriptJs": None,
    "tags": [{"tag": "agent"}, {"tag": "test"}],
}


def _graphql_response(data: dict) -> httpx.Response:
    return httpx.Response(200, json={"data": data})


def _graphql_error_response(message: str) -> httpx.Response:
    return httpx.Response(200, json={"errors": [{"message": message}]})


@pytest.fixture
def client():
    return WikiJsClient(GRAPHQL_URL, API_TOKEN)


@pytest.mark.anyio
@respx.mock
async def test_get_page_by_path_success(client):
    respx.post(GRAPHQL_URL).mock(
        return_value=_graphql_response({"pages": {"singleByPath": _SAMPLE_PAGE}})
    )
    page = await client.get_page_by_path("agent/test-page", "ko")
    assert page is not None
    assert page.id == 42
    assert page.path == "agent/test-page"
    assert page.title == "테스트 페이지"
    assert page.tags == ["agent", "test"]
    expected_hash = compute_hash(42, "2026-05-31T00:00:00.000Z", "# Hello")
    assert page.contentHash == expected_hash
    await client.aclose()


@pytest.mark.anyio
@respx.mock
async def test_get_page_by_path_not_found(client):
    respx.post(GRAPHQL_URL).mock(
        return_value=_graphql_response({"pages": {"singleByPath": None}})
    )
    page = await client.get_page_by_path("nonexistent/page", "ko")
    assert page is None
    await client.aclose()


@pytest.mark.anyio
@respx.mock
async def test_get_page_by_path_graphql_error(client):
    respx.post(GRAPHQL_URL).mock(return_value=_graphql_error_response("PageViewForbidden"))
    with pytest.raises(WikiJsError) as exc_info:
        await client.get_page_by_path("some/page", "ko")
    assert "PageViewForbidden" in str(exc_info.value)
    await client.aclose()


@pytest.mark.anyio
@respx.mock
async def test_get_page_by_path_network_error(client):
    respx.post(GRAPHQL_URL).mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(httpx.ConnectError):
        await client.get_page_by_path("some/page", "ko")
    await client.aclose()


@pytest.mark.anyio
@respx.mock
async def test_ping_success(client):
    respx.post(GRAPHQL_URL).mock(
        return_value=_graphql_response({"pages": {"list": [{"id": 1}]}})
    )
    result = await client.ping()
    assert result is True
    await client.aclose()


@pytest.mark.anyio
@respx.mock
async def test_ping_network_error(client):
    respx.post(GRAPHQL_URL).mock(side_effect=httpx.ConnectError("refused"))
    result = await client.ping()
    assert result is False
    await client.aclose()


@pytest.mark.anyio
@respx.mock
async def test_ping_graphql_error(client):
    respx.post(GRAPHQL_URL).mock(return_value=_graphql_error_response("Unauthorized"))
    result = await client.ping()
    assert result is False
    await client.aclose()


def test_compute_hash_deterministic():
    h1 = compute_hash(1, "2026-05-31T00:00:00Z", "content")
    h2 = compute_hash(1, "2026-05-31T00:00:00Z", "content")
    assert h1 == h2


def test_compute_hash_differs_on_content():
    h1 = compute_hash(1, "2026-05-31T00:00:00Z", "content A")
    h2 = compute_hash(1, "2026-05-31T00:00:00Z", "content B")
    assert h1 != h2


def test_compute_hash_format():
    h = compute_hash(1, "ts", "c")
    hex_part = hashlib.sha256(b"1\nts\nc").hexdigest()
    assert h == f"sha256:{hex_part}"
