"""MCP server tests.

The MCP layer (fastapi-mcp) reflects the v2 REST routes into tools and forwards
the Authorization header into an internal ASGI call back to the same app. Most
tests exercise that wiring via `_execute_api_tool` (no session dance); the
tools/list and isError checks go through the low-level MCP request handlers so
they see exactly what an MCP client would.
"""
import asyncio
import json
from unittest.mock import AsyncMock

import mcp.types as types
import pytest
from fastapi_mcp.types import HTTPRequestInfo

from app.config import Settings, get_settings
from app.locking import compute_hash
from app.main import app, get_wikijs_client, mcp
from app.models import PageResponse

ADMIN_TOKEN = "test-admin-token"

TEST_ENV = {
    "wikijs_graphql_url": "http://wiki:3000/graphql",
    "wikijs_api_token": "wiki-token",
    "gateway_admin_token": ADMIN_TOKEN,
}

_CONTENT = "# Hello\n\n<!-- agent:start x -->\nold\n<!-- agent:end x -->\n"
_UPDATED_AT = "2026-05-31T00:00:00.000Z"
_PAGE_ID = 42

_SAMPLE_PAGE = PageResponse(
    id=_PAGE_ID,
    path="agent/example",
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

_WIKIJS_CREATE_RESULT = {
    "responseResult": {"succeeded": True, "errorCode": 0, "message": ""},
    "page": {"id": 99, "path": "agent/new-page", "title": "New Page", "updatedAt": _UPDATED_AT},
}

# Snapshot: MCP tool names must stay stable across the v2 path change.
_TOOL_SNAPSHOT = [
    "dry_run_patch",
    "get_page_by_path",
    "get_page_by_uuid",
    "get_pages_by_paths",
    "patch_section",
    "search_pages",
    "upsert_page",
]


def _new_page_mock():
    mock = AsyncMock()
    # None before the create, the new page on the post-write refetch
    mock.get_page_by_path.side_effect = [None, _SAMPLE_PAGE]
    mock.create_page.return_value = _WIKIJS_CREATE_RESULT
    return mock


@pytest.fixture
def wiki():
    holder = {}
    app.dependency_overrides[get_settings] = lambda: Settings(**TEST_ENV)
    app.dependency_overrides[get_wikijs_client] = lambda: holder["mock"]
    yield holder
    app.dependency_overrides.clear()


def _req_info(token: str | None):
    """Build an HTTPRequestInfo carrying (or omitting) a Bearer token, as the MCP
    transport would after extracting it from the incoming /api/v2/mcp request."""
    headers = {"authorization": f"Bearer {token}"} if token else {}
    return HTTPRequestInfo(
        method="POST", path="/api/v2/mcp", headers=headers, cookies={}, query_params={}, body=None
    )


def _call_tool(tool_name: str, arguments: dict, token: str | None = None):
    return asyncio.run(
        mcp._execute_api_tool(
            client=mcp._http_client,
            tool_name=tool_name,
            arguments=arguments,
            operation_map=mcp.operation_map,
            http_request_info=_req_info(token) if token is not None else None,
        )
    )


# ---- mount + tool exposure ----

def test_mcp_mounted_under_v2():
    mcp_paths = {r.path for r in app.routes if getattr(r, "name", "") == "handle_mcp_streamable_http"}
    assert mcp_paths == {"/api/v2/mcp"}


def test_tools_list_snapshot():
    result = asyncio.run(mcp.server.request_handlers[types.ListToolsRequest](None))
    names = sorted(t.name for t in result.root.tools)
    assert names == _TOOL_SNAPSHOT
    for excluded in ["download_page", "health_live", "health_ready"]:
        assert excluded not in names


def test_tools_target_v2_paths():
    assert all(op["path"].startswith("/api/v2/") for op in mcp.operation_map.values())


# ---- read tool: no auth required ----

def test_read_tool_returns_page_without_token(wiki):
    wiki["mock"] = AsyncMock(get_page_by_path=AsyncMock(return_value=_SAMPLE_PAGE))
    result = _call_tool("get_page_by_path", {"path": "agent/example", "locale": "ko"})
    text = result[0].text
    assert "agent/example" in text
    assert '"id": 42' in text


def test_uuid_tool_maps_path_param(wiki):
    mock = AsyncMock()
    mock.get_page_by_path.return_value = _SAMPLE_PAGE
    mock.find_paths_by_uuid.return_value = ["skill/abc"]
    wiki["mock"] = mock
    _call_tool("get_page_by_uuid", {"uuid": "abc", "type": "skill"})
    mock.get_page_by_path.assert_any_call("skill/abc", "ko")


# ---- write tools: auth enforced via forwarded header ----

@pytest.mark.parametrize("tool,args", [
    ("upsert_page", {"path": "agent/new-page", "title": "T", "content": "c"}),
    ("patch_section", {"path": "agent/example", "baseHash": "x",
                       "operation": {"type": "replace_between_markers", "name": "x", "content": "y"}}),
    ("dry_run_patch", {"path": "agent/example", "baseHash": "x",
                       "operation": {"type": "replace_between_markers", "name": "x", "content": "y"}}),
])
@pytest.mark.parametrize("token", [None, "wrong-token"])
def test_write_tools_rejected_without_valid_token(wiki, tool, args, token):
    mock = _new_page_mock()
    wiki["mock"] = mock
    with pytest.raises(Exception):
        _call_tool(tool, args, token=token)
    mock.get_page_by_path.assert_not_called()
    mock.create_page.assert_not_called()
    mock.update_page.assert_not_called()


def test_admin_tool_valid_token_succeeds(wiki):
    mock = _new_page_mock()
    wiki["mock"] = mock
    result = _call_tool(
        "upsert_page",
        {"path": "agent/new-page", "locale": "ko", "title": "New Page", "content": "# New\n"},
        token=ADMIN_TOKEN,
    )
    data = json.loads(result[0].text)
    assert data["created"] is True
    assert data["pageId"] == 99
    assert data["contentHash"] == _SAMPLE_PAGE.contentHash
    mock.create_page.assert_called_once()


def test_admin_tool_writes_audit(wiki, tmp_path, monkeypatch):
    import app.main as main_module

    monkeypatch.setattr(main_module, "_AUDIT_DIR", str(tmp_path))
    wiki["mock"] = _new_page_mock()
    _call_tool(
        "upsert_page",
        {"path": "agent/new-page", "locale": "ko", "title": "New Page", "content": "# New\n"},
        token=ADMIN_TOKEN,
    )
    assert len(list(tmp_path.rglob("*.json"))) == 1


# ---- errors surface as isError results ----

def test_page_changed_surfaces_as_is_error(wiki, monkeypatch):
    mock = AsyncMock()
    mock.get_page_by_path.return_value = _SAMPLE_PAGE
    wiki["mock"] = mock

    # The low-level handler has no live MCP request context here, so supply
    # the forwarded Authorization header the way the transport would.
    original = mcp._execute_api_tool

    async def with_auth(**kwargs):
        kwargs["http_request_info"] = _req_info(ADMIN_TOKEN)
        return await original(**kwargs)

    monkeypatch.setattr(mcp, "_execute_api_tool", with_auth)
    request = types.CallToolRequest(
        method="tools/call",
        params=types.CallToolRequestParams(
            name="patch_section",
            arguments={
                "path": "agent/example",
                "locale": "ko",
                "baseHash": "sha256:stale",
                "operation": {"type": "replace_between_markers", "name": "x", "content": "y"},
            },
        ),
    )
    result = asyncio.run(mcp.server.request_handlers[types.CallToolRequest](request)).root
    assert result.isError is True
    text = result.content[0].text
    assert "409" in text
    assert "urn:wikijs-gateway:problem:page-changed" in text
    assert _SAMPLE_PAGE.contentHash in text
    mock.update_page.assert_not_called()
