import hashlib

import httpx
import pytest
import respx

from app.locking import compute_hash
from app.wikijs_client import WikiJsClient, WikiJsError, _normalize_path

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


def test_normalize_path_strips_leading_slash():
    assert _normalize_path("/agent/test") == "agent/test"
    assert _normalize_path("agent/test") == "agent/test"
    assert _normalize_path("/home") == "home"
    assert _normalize_path("home") == "home"


def test_normalize_path_preserves_nested():
    assert _normalize_path("/ops/runbook/guide") == "ops/runbook/guide"


@pytest.mark.anyio
@respx.mock
async def test_get_page_by_path_wikijs_6003_returns_none(client):
    """Wiki.js returns error code 6003 (PageNotFound) instead of null for missing pages."""
    respx.post(GRAPHQL_URL).mock(
        return_value=httpx.Response(200, json={
            "errors": [{"message": "This page does not exist.", "extensions": {"exception": {"code": 6003}}}]
        })
    )
    page = await client.get_page_by_path("nonexistent/path", "ko")
    assert page is None
    await client.aclose()


@pytest.mark.anyio
@respx.mock
async def test_get_page_by_path_wikijs_6013_returns_none(client):
    """Issue #23: 6013 (PageViewForbidden) is reported as missing, not as an upstream error."""
    respx.post(GRAPHQL_URL).mock(
        return_value=httpx.Response(200, json={
            "errors": [{"message": "Forbidden", "extensions": {"exception": {"code": 6013}}}]
        })
    )
    page = await client.get_page_by_path("trash/some-page", "en")
    assert page is None
    await client.aclose()


@pytest.mark.anyio
@respx.mock
async def test_get_page_by_path_leading_slash_normalized(client):
    """Leading slash in path is stripped before sending to Wiki.js."""
    route = respx.post(GRAPHQL_URL).mock(
        return_value=_graphql_response({"pages": {"singleByPath": _SAMPLE_PAGE}})
    )
    await client.get_page_by_path("/agent/test-page", "ko")
    request_body = route.calls[0].request.read()
    import json
    body = json.loads(request_body)
    assert body["variables"]["path"] == "agent/test-page"
    await client.aclose()


_TEST_UUID = "550e8400-e29b-41d4-a716-446655440000"

# pages.list returns path even when the search index does not cover the UUID.
_LIST_ITEMS = [
    {"id": 1, "path": "home", "locale": "ko"},
    {"id": 2, "path": "guide/intro", "locale": "ko"},
    {"id": 10, "path": f"skill/{_TEST_UUID}", "locale": "en"},
]


@pytest.mark.anyio
@respx.mock
async def test_find_paths_by_uuid_found_with_prefix(client):
    respx.post(GRAPHQL_URL).mock(
        return_value=_graphql_response({"pages": {"list": _LIST_ITEMS}})
    )
    assert await client.find_paths_by_uuid(_TEST_UUID) == [f"skill/{_TEST_UUID}"]
    await client.aclose()


@pytest.mark.anyio
@respx.mock
async def test_find_paths_by_uuid_not_found(client):
    respx.post(GRAPHQL_URL).mock(
        return_value=_graphql_response({"pages": {"list": _LIST_ITEMS[:2]}})
    )
    assert await client.find_paths_by_uuid(_TEST_UUID) == []
    await client.aclose()


@pytest.mark.anyio
@respx.mock
async def test_find_paths_by_uuid_found_bare(client):
    bare_items = [{"id": 10, "path": _TEST_UUID, "locale": "en"}]
    respx.post(GRAPHQL_URL).mock(
        return_value=_graphql_response({"pages": {"list": bare_items}})
    )
    assert await client.find_paths_by_uuid(_TEST_UUID) == [_TEST_UUID]
    await client.aclose()


_UPPER = "71A7E480-BCF2-11EE-8610-10791AE23500"
_LOWER = _UPPER.lower()


@pytest.mark.anyio
@pytest.mark.parametrize("query,type_", [(_LOWER, ""), (_LOWER, "skill"), (_LOWER, "SKILL")])
@respx.mock
async def test_find_paths_by_uuid_case_insensitive_fallback(client, query, type_):
    """Issue #19 A1: wiki stores the uppercase path, caller sends lowercase."""
    items = [{"id": 1, "path": f"skill/{_UPPER}", "locale": "en"},
             {"id": 2, "path": f"skill/{_UPPER}", "locale": "ko"}]
    respx.post(GRAPHQL_URL).mock(return_value=_graphql_response({"pages": {"list": items}}))
    assert await client.find_paths_by_uuid(query, type_) == [f"skill/{_UPPER}"]
    await client.aclose()


@pytest.mark.anyio
@respx.mock
async def test_find_paths_by_uuid_exact_case_wins(client):
    """An exact-case path beats case variants, so a base file is never ambiguous."""
    items = [{"id": 1, "path": f"skill/{_UPPER}", "locale": "en"},
             {"id": 2, "path": f"skill/{_LOWER}", "locale": "en"}]
    respx.post(GRAPHQL_URL).mock(return_value=_graphql_response({"pages": {"list": items}}))
    assert await client.find_paths_by_uuid(_LOWER, "skill") == [f"skill/{_LOWER}"]
    assert await client.find_paths_by_uuid(_UPPER) == [f"skill/{_UPPER}"]
    await client.aclose()


@pytest.mark.anyio
@respx.mock
async def test_find_paths_by_uuid_fallback_returns_all_case_variants(client):
    mixed = _UPPER[:8].lower() + _UPPER[8:]
    items = [{"id": 1, "path": f"skill/{_UPPER}", "locale": "en"},
             {"id": 2, "path": f"skill/{_LOWER}", "locale": "en"}]
    respx.post(GRAPHQL_URL).mock(return_value=_graphql_response({"pages": {"list": items}}))
    assert await client.find_paths_by_uuid(mixed) == sorted([f"skill/{_UPPER}", f"skill/{_LOWER}"])
    await client.aclose()


@pytest.mark.anyio
@respx.mock
async def test_find_paths_by_uuid_uses_list_not_search(client):
    """The UUID lookup must hit pages.list — the search index doesn't cover paths."""
    route = respx.post(GRAPHQL_URL).mock(
        return_value=_graphql_response({"pages": {"list": _LIST_ITEMS}})
    )
    await client.find_paths_by_uuid(_TEST_UUID)
    import json
    body = json.loads(route.calls[0].request.read())
    assert "list" in body["query"]
    assert "search" not in body["query"]
    await client.aclose()


@pytest.mark.anyio
@respx.mock
async def test_find_paths_by_uuid_graphql_error(client):
    respx.post(GRAPHQL_URL).mock(return_value=_graphql_error_response("Forbidden"))
    with pytest.raises(WikiJsError):
        await client.find_paths_by_uuid(_TEST_UUID)
    await client.aclose()


# Fields of Wiki.js 2.x `type PageSearchResult` (server/graph/schemas/page.graphql).
_PAGE_SEARCH_RESULT_FIELDS = {"id", "title", "description", "path", "locale"}


def test_search_query_requests_only_schema_fields():
    """Issue #19 A2: asking for a field the schema lacks makes Wiki.js reject the query."""
    import re
    from app.wikijs_client import _QUERY_SEARCH_PAGES
    block = re.search(r"results\s*\{([^}]*)\}", _QUERY_SEARCH_PAGES).group(1)
    assert set(block.split()) <= _PAGE_SEARCH_RESULT_FIELDS


@pytest.mark.anyio
@respx.mock
async def test_search_accepts_string_ids(client):
    """PageSearchResult.id is String! in the schema."""
    data = {"results": [{"id": "10", "path": "a", "title": "A", "description": "", "locale": "en"}],
            "suggestions": [], "totalHits": 1}
    respx.post(GRAPHQL_URL).mock(return_value=_graphql_response({"pages": {"search": data}}))
    assert (await client.search_pages("a", "en"))["results"][0]["id"] == "10"
    await client.aclose()


@pytest.mark.anyio
@respx.mock
async def test_http_400_with_graphql_errors_is_wikijs_error(client):
    """Wiki.js sends query validation errors as HTTP 400 + errors body — not 'unreachable'."""
    respx.post(GRAPHQL_URL).mock(return_value=httpx.Response(
        400, json={"errors": [{"message": 'Cannot query field "updatedAt" on type "PageSearchResult".'}]}))
    with pytest.raises(WikiJsError):
        await client.search_pages("catalog", "en")
    await client.aclose()


@pytest.mark.anyio
@respx.mock
async def test_http_400_without_errors_body_is_transport_error(client):
    respx.post(GRAPHQL_URL).mock(return_value=httpx.Response(400, text="bad"))
    with pytest.raises(httpx.HTTPStatusError):
        await client.search_pages("catalog", "en")
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
