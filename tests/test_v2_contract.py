"""Cross-cutting v2 contract checks: base path, removed v1 paths, OpenAPI
location, X-Served-By on every response, problem+json errors, traceparent."""
import json
from unittest.mock import AsyncMock

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.locking import compute_hash
from app.main import app, get_wikijs_client
from app.middleware import current_traceparent
from app.models import PageResponse
from app.wikijs_client import WikiJsClient

TEST_ENV = {
    "wikijs_graphql_url": "http://wiki:3000/graphql",
    "wikijs_api_token": "wiki-token",
    "gateway_admin_token": "test-admin-token",
}
_AUTH = {"Authorization": "Bearer test-admin-token"}
_TRACEPARENT = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"

_PAGE = PageResponse(
    id=1, path="agent/a", locale="ko", title="A", description="", content="# A\n",
    editor="markdown", isPublished=True, isPrivate=False, updatedAt="2026-01-01T00:00:00Z",
    contentHash=compute_hash(1, "2026-01-01T00:00:00Z", "# A\n"), tags=[],
)


@pytest.fixture
def client():
    mock = AsyncMock()
    mock.get_page_by_path.return_value = _PAGE
    app.dependency_overrides[get_settings] = lambda: Settings(**TEST_ENV)
    app.dependency_overrides[get_wikijs_client] = lambda: mock
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_openapi_only_under_v2(client):
    resp = client.get("/api/v2/openapi.json")
    assert resp.status_code == 200
    assert resp.headers["x-served-by"] == "wikijs-gateway"
    spec = resp.json()
    assert spec["info"]["version"] == "2.0.0"
    assert all(p.startswith("/api/v2/") for p in spec["paths"])
    for gone in ["/openapi.json", "/docs", "/redoc", "/api/v2/docs"]:
        assert client.get(gone).status_code == 404, gone


@pytest.mark.parametrize("method,path", [
    ("get", "/health"),
    ("get", "/pages/by-path?path=a"),
    ("get", "/pages/by-uuid?uuid=x"),
    ("get", "/pages/download?uuid=x"),
    ("get", "/pages/search?query=x"),
    ("post", "/pages/by-paths"),
    ("post", "/pages/dry-run"),
    ("post", "/pages/patch-section"),
    ("post", "/pages/upsert"),
    ("post", "/mcp"),
])
def test_v1_paths_are_gone(client, method, path):
    resp = getattr(client, method)(path)
    assert resp.status_code == 404
    assert resp.headers["content-type"] == "application/problem+json"
    assert resp.headers["x-served-by"] == "wikijs-gateway"


def test_get_page_sets_etag(client):
    resp = client.get("/api/v2/pages", params={"path": "agent/a"})
    assert resp.status_code == 200
    assert resp.headers["etag"] == f'"{_PAGE.contentHash}"'
    assert resp.headers["x-served-by"] == "wikijs-gateway"


def test_validation_error_is_problem_json(client):
    resp = client.get("/api/v2/pages")  # missing required `path`
    assert resp.status_code == 422
    assert resp.headers["content-type"] == "application/problem+json"
    assert resp.headers["x-served-by"] == "wikijs-gateway"
    body = resp.json()
    assert body["type"] == "urn:wikijs-gateway:problem:validation-error"
    assert body["status"] == 422
    assert body["errors"][0]["loc"] == ["query", "path"]


def test_body_validation_error_on_write(client):
    resp = client.put("/api/v2/pages", headers=_AUTH, json={"path": "a"})
    assert resp.status_code == 422
    assert resp.json()["type"] == "urn:wikijs-gateway:problem:validation-error"


def test_method_not_allowed_is_problem_json(client):
    resp = client.delete("/api/v2/pages")
    assert resp.status_code == 405
    assert resp.headers["content-type"] == "application/problem+json"
    assert resp.headers["x-served-by"] == "wikijs-gateway"


def test_unhandled_error_is_problem_json():
    mock = AsyncMock()
    mock.search_pages.return_value = None  # .get() on None -> AttributeError in the route
    app.dependency_overrides[get_settings] = lambda: Settings(**TEST_ENV)
    app.dependency_overrides[get_wikijs_client] = lambda: mock
    try:
        resp = TestClient(app, raise_server_exceptions=False).get("/api/v2/pages/search", params={"q": "x"})
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 500
    assert resp.headers["content-type"] == "application/problem+json"
    assert resp.headers["x-served-by"] == "wikijs-gateway"
    assert "AttributeError" not in resp.text


# ---- traceparent ----

@respx.mock
def test_traceparent_forwarded_to_wikijs_and_audited(tmp_path, monkeypatch):
    import app.main as main_module

    monkeypatch.setattr(main_module, "_AUDIT_DIR", str(tmp_path))
    route = respx.post("http://wiki:3000/graphql").mock(
        side_effect=[
            httpx.Response(200, json={"data": {"pages": {"singleByPath": None}}}),
            httpx.Response(200, json={"data": {"pages": {"create": {
                "responseResult": {"succeeded": True, "errorCode": 0, "message": ""},
                "page": {"id": 7, "path": "agent/t", "title": "T", "updatedAt": "x"},
            }}}}),
            httpx.Response(200, json={"data": {"pages": {"singleByPath": {
                "id": 7, "path": "agent/t", "title": "T", "description": "", "content": "c",
                "editor": "markdown", "locale": "ko", "isPublished": True, "isPrivate": False,
                "updatedAt": "2026-01-01T00:00:00Z", "scriptCss": None, "scriptJs": None, "tags": [],
            }}}}),
        ]
    )
    wiki = WikiJsClient("http://wiki:3000/graphql", "wiki-token")
    app.dependency_overrides[get_settings] = lambda: Settings(**TEST_ENV)
    app.dependency_overrides[get_wikijs_client] = lambda: wiki
    try:
        resp = TestClient(app).put(
            "/api/v2/pages",
            headers={**_AUTH, "traceparent": _TRACEPARENT},
            json={"path": "agent/t", "locale": "ko", "title": "T", "content": "c"},
        )
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 201
    assert resp.json()["contentHash"] == compute_hash(7, "2026-01-01T00:00:00Z", "c")
    assert route.call_count == 3
    assert all(c.request.headers["traceparent"] == _TRACEPARENT for c in route.calls)
    [record] = [json.loads(p.read_text()) for p in tmp_path.rglob("*.json")]
    assert record["traceparent"] == _TRACEPARENT


@respx.mock
def test_malformed_traceparent_not_forwarded(client):
    route = respx.post("http://wiki:3000/graphql").mock(
        return_value=httpx.Response(200, json={"data": {"pages": {"singleByPath": None}}})
    )
    wiki = WikiJsClient("http://wiki:3000/graphql", "wiki-token")
    app.dependency_overrides[get_wikijs_client] = lambda: wiki
    resp = client.get("/api/v2/pages", params={"path": "x"}, headers={"traceparent": "garbage"})
    assert resp.status_code == 404
    assert "traceparent" not in route.calls[0].request.headers
    assert current_traceparent.get() is None
