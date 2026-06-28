"""MCP server tests.

The MCP layer (fastapi-mcp) reflects the REST routes into tools and forwards the
Authorization header into an internal ASGI call back to the same app. These tests
exercise that new wiring directly via `_execute_api_tool` — no SSE/session dance —
so they verify: tool exposure, read tools work without auth, admin tools enforce
GATEWAY_ADMIN_TOKEN, and write tools still leave an audit log.
"""
import asyncio
from unittest.mock import AsyncMock

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

_WIKIJS_CREATE_RESULT = {
    "responseResult": {"succeeded": True, "errorCode": 0, "message": ""},
    "page": {"id": 99, "path": "/agent/new-page", "title": "New Page", "updatedAt": _UPDATED_AT},
}


def _setup(mock_client):
    app.dependency_overrides[get_settings] = lambda: Settings(**TEST_ENV)
    app.dependency_overrides[get_wikijs_client] = lambda: mock_client


def _teardown():
    app.dependency_overrides.clear()


def _req_info(token: str | None):
    """Build an HTTPRequestInfo carrying (or omitting) a Bearer token, as the MCP
    transport would after extracting it from the incoming /mcp request."""
    headers = {"authorization": f"Bearer {token}"} if token else {}
    return HTTPRequestInfo(
        method="POST", path="/mcp", headers=headers, cookies={}, query_params={}, body=None
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


# ---- tool exposure ----

def test_mcp_exposes_seven_tools():
    names = sorted(t.name for t in mcp.tools)
    assert names == [
        "dry_run_patch",
        "get_page_by_path",
        "get_page_by_uuid",
        "get_pages_by_paths",
        "patch_section",
        "search_pages",
        "upsert_page",
    ]
    assert "health" not in names  # /health excluded from tools


# ---- read tool: no auth required ----

def test_read_tool_returns_page_without_token():
    mock = AsyncMock()
    mock.get_page_by_path.return_value = _SAMPLE_PAGE
    _setup(mock)
    try:
        result = _call_tool("get_page_by_path", {"path": "/agent/example", "locale": "ko"})
        text = result[0].text
        assert "/agent/example" in text
        assert '"id": 42' in text
    finally:
        _teardown()


# ---- admin tool: auth enforced via forwarded header ----

def test_admin_tool_without_token_rejected():
    mock = AsyncMock()
    mock.upsert_page.return_value = (_WIKIJS_CREATE_RESULT, True)
    _setup(mock)
    try:
        # no http_request_info → no Authorization header forwarded → 401 → raises
        with pytest.raises(Exception):
            _call_tool("upsert_page", {"path": "/agent/new-page", "title": "T", "content": "c"})
        mock.upsert_page.assert_not_called()
    finally:
        _teardown()


def test_admin_tool_wrong_token_rejected():
    mock = AsyncMock()
    mock.upsert_page.return_value = (_WIKIJS_CREATE_RESULT, True)
    _setup(mock)
    try:
        with pytest.raises(Exception):
            _call_tool(
                "upsert_page",
                {"path": "/agent/new-page", "title": "T", "content": "c"},
                token="wrong-token",
            )
        mock.upsert_page.assert_not_called()
    finally:
        _teardown()


def test_admin_tool_valid_token_succeeds():
    mock = AsyncMock()
    mock.upsert_page.return_value = (_WIKIJS_CREATE_RESULT, True)
    _setup(mock)
    try:
        result = _call_tool(
            "upsert_page",
            {"path": "/agent/new-page", "locale": "ko", "title": "New Page", "content": "# New\n"},
            token=ADMIN_TOKEN,
        )
        text = result[0].text
        assert '"created": true' in text
        assert '"pageId": 99' in text
        mock.upsert_page.assert_called_once()
    finally:
        _teardown()


# ---- write tool leaves an audit log ----

def test_admin_tool_writes_audit(tmp_path):
    import app.main as main_module

    original = main_module._AUDIT_DIR
    main_module._AUDIT_DIR = str(tmp_path)
    mock = AsyncMock()
    mock.upsert_page.return_value = (_WIKIJS_CREATE_RESULT, True)
    _setup(mock)
    try:
        _call_tool(
            "upsert_page",
            {"path": "/agent/new-page", "locale": "ko", "title": "New Page", "content": "# New\n"},
            token=ADMIN_TOKEN,
        )
        assert len(list(tmp_path.rglob("*.json"))) == 1
    finally:
        main_module._AUDIT_DIR = original
        _teardown()
