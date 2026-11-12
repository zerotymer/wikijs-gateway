"""Write routes (v2): PUT /api/v2/pages, POST /api/v2/pages/patches[/preview].

Covers auth, the v2 locking contract (409 / 428 / refetched contentHash /
per-page serialization), guard G1 and audit records.
"""
import asyncio
import json
from unittest.mock import AsyncMock

import httpx
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
_VALID_HASH = compute_hash(_PAGE_ID, _UPDATED_AT, _CONTENT)

ADMIN_TOKEN = "test-admin-token"
TEST_ENV = {
    "wikijs_graphql_url": "http://wiki:3000/graphql",
    "wikijs_api_token": "wiki-token",
    "gateway_admin_token": ADMIN_TOKEN,
}
_AUTH = {"Authorization": f"Bearer {ADMIN_TOKEN}"}
_PROBLEM = "urn:wikijs-gateway:problem:"

PATCHES = "/api/v2/pages/patches"
PREVIEW = "/api/v2/pages/patches/preview"
PAGES = "/api/v2/pages"


def _page(content: str = _CONTENT, updated_at: str = _UPDATED_AT, path: str = "agent/example") -> PageResponse:
    return PageResponse(
        id=_PAGE_ID,
        path=path,
        locale="ko",
        title="Example",
        description="desc",
        content=content,
        editor="markdown",
        isPublished=True,
        isPrivate=False,
        updatedAt=updated_at,
        contentHash=compute_hash(_PAGE_ID, updated_at, content),
        tags=[],
    )


class FakeWiki:
    """Stateful stand-in for WikiJsClient: update bumps updatedAt like Wiki.js does."""

    def __init__(self, page: PageResponse | None = None, write_delay: float = 0.0) -> None:
        self.page = page
        self.write_delay = write_delay
        self.updates = 0
        self.creates = 0
        self.fail_refetch = False
        self._reads_after_write = 0

    def _bump(self, content: str) -> None:
        self.updates += 1
        updated_at = f"2026-06-01T00:00:{self.updates:02d}.000Z"
        self.page = _page(content=content, updated_at=updated_at, path=self.page.path if self.page else "agent/new")

    async def get_page_by_path(self, path: str, locale: str):
        if self.fail_refetch and (self.updates or self.creates):
            raise RuntimeError("connection reset by peer at 10.0.0.5")
        return self.page

    async def update_page(self, page, content, metadata_overrides=None):
        await asyncio.sleep(self.write_delay)
        self._bump(content)
        return {"responseResult": {"succeeded": True}, "page": {"id": _PAGE_ID, "path": self.page.path}}

    async def create_page(self, path, locale, title, description, content, **kwargs):
        self.creates += 1
        self.page = _page(content=content, updated_at="2026-06-02T00:00:00.000Z", path=path.lstrip("/"))
        return {"responseResult": {"succeeded": True}, "page": {"id": _PAGE_ID, "path": self.page.path}}


@pytest.fixture
def audit_dir(tmp_path, monkeypatch):
    import app.main as main_module

    monkeypatch.setattr(main_module, "_AUDIT_DIR", str(tmp_path))
    return tmp_path


def _setup(wiki):
    app.dependency_overrides[get_settings] = lambda: Settings(**TEST_ENV)
    app.dependency_overrides[get_wikijs_client] = lambda: wiki
    return TestClient(app)


@pytest.fixture(autouse=True)
def _teardown():
    yield
    app.dependency_overrides.clear()


def _patch_body(base_hash: str = _VALID_HASH, path: str = "/agent/example", content: str = "new content") -> dict:
    return {
        "path": path,
        "locale": "ko",
        "baseHash": base_hash,
        "operation": {"type": "replace_between_markers", "name": "x", "content": content},
    }


def _upsert_body(**extra) -> dict:
    return {"path": "/agent/example", "locale": "ko", "title": "T", "content": "# Updated\n", **extra}


def _audit_records(audit_dir) -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted(audit_dir.rglob("*.json"))]


# ---- auth ----

@pytest.mark.parametrize("method,url,body", [
    ("post", PATCHES, _patch_body()),
    ("post", PREVIEW, _patch_body()),
    ("put", PAGES, _upsert_body()),
])
def test_write_routes_require_token(method, url, body):
    wiki = FakeWiki(_page())
    client = _setup(wiki)
    resp = getattr(client, method)(url, json=body)
    assert resp.status_code == 401
    assert resp.headers["content-type"] == "application/problem+json"
    assert resp.json()["type"] == _PROBLEM + "unauthorized"

    resp = getattr(client, method)(url, json=body, headers={"Authorization": "Bearer wrong"})
    assert resp.status_code == 403
    assert resp.json()["type"] == _PROBLEM + "forbidden"
    assert wiki.updates == 0 and wiki.creates == 0


# ---- patches ----

def test_patch_returns_refetched_hash(audit_dir):
    wiki = FakeWiki(_page())
    client = _setup(wiki)
    resp = client.post(PATCHES, headers=_AUTH, json=_patch_body())
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True and data["changed"] is True
    assert "newHash" not in data
    assert data["refetchFailed"] is False
    # Hash of the page as it is now (updatedAt bumped by the write)
    assert data["contentHash"] == wiki.page.contentHash
    assert data["contentHash"] != _VALID_HASH
    assert "Warning" not in resp.headers

    [record] = _audit_records(audit_dir)
    assert record["new_hash"] == wiki.page.contentHash
    assert record["current_hash"] == _VALID_HASH


def test_patch_hash_enables_immediate_second_patch(audit_dir):
    wiki = FakeWiki(_page())
    client = _setup(wiki)
    first = client.post(PATCHES, headers=_AUTH, json=_patch_body(content="one"))
    assert first.status_code == 200
    second = client.post(PATCHES, headers=_AUTH, json=_patch_body(base_hash=first.json()["contentHash"], content="two"))
    assert second.status_code == 200, second.json()
    assert wiki.updates == 2
    assert "two" in wiki.page.content


def test_patch_page_changed_returns_409():
    wiki = FakeWiki(_page(content="different content"))
    client = _setup(wiki)
    resp = client.post(PATCHES, headers=_AUTH, json=_patch_body())
    assert resp.status_code == 409
    assert resp.headers["content-type"] == "application/problem+json"
    data = resp.json()
    assert data["type"] == _PROBLEM + "page-changed"
    assert data["status"] == 409
    assert data["currentHash"] == wiki.page.contentHash
    assert wiki.updates == 0


def test_patch_refetch_failure_still_200(audit_dir):
    wiki = FakeWiki(_page())
    wiki.fail_refetch = True
    client = _setup(wiki)
    resp = client.post(PATCHES, headers=_AUTH, json=_patch_body())
    assert resp.status_code == 200
    data = resp.json()
    assert data["contentHash"] is None
    assert data["refetchFailed"] is True
    assert resp.headers["Warning"] == '199 - "refetch failed"'
    assert _audit_records(audit_dir)[0]["new_hash"] is None


def test_patch_page_not_found():
    client = _setup(FakeWiki(None))
    resp = client.post(PATCHES, headers=_AUTH, json=_patch_body())
    assert resp.status_code == 404
    assert resp.json()["type"] == _PROBLEM + "page-not-found"


def test_patch_marker_missing_is_patch_error():
    client = _setup(FakeWiki(_page()))
    body = _patch_body()
    body["operation"]["name"] = "nope"
    resp = client.post(PATCHES, headers=_AUTH, json=body)
    assert resp.status_code == 422
    assert resp.json()["type"] == _PROBLEM + "patch-error"


def test_patch_reserved_api_path_rejected():
    wiki = FakeWiki(_page(path="api/v2/x"))
    client = _setup(wiki)
    for path in ["/api/v2/x", "api", "API/foo"]:
        resp = client.post(PATCHES, headers=_AUTH, json=_patch_body(path=path))
        assert resp.status_code == 422, path
        assert resp.json()["type"] == _PROBLEM + "reserved-path"
    assert wiki.updates == 0


def test_patch_api_prefix_lookalike_allowed(audit_dir):
    wiki = FakeWiki(_page(path="apis/x"))
    client = _setup(wiki)
    resp = client.post(PATCHES, headers=_AUTH, json=_patch_body(path="/apis/x"))
    assert resp.status_code == 200


def test_concurrent_patches_same_page_one_wins(audit_dir):
    """Two patches with the same baseHash: the per-page lock serializes them,
    so the second sees the refreshed page and gets 409 instead of overwriting."""
    wiki = FakeWiki(_page(), write_delay=0.05)
    app.dependency_overrides[get_settings] = lambda: Settings(**TEST_ENV)
    app.dependency_overrides[get_wikijs_client] = lambda: wiki

    async def run():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://gw") as ac:
            return await asyncio.gather(
                ac.post(PATCHES, headers=_AUTH, json=_patch_body(content="A")),
                ac.post(PATCHES, headers=_AUTH, json=_patch_body(content="B")),
            )

    responses = asyncio.run(run())
    assert sorted(r.status_code for r in responses) == [200, 409]
    assert wiki.updates == 1


# ---- preview ----

def test_preview_returns_diff_without_writing(audit_dir):
    wiki = FakeWiki(_page())
    client = _setup(wiki)
    resp = client.post(PREVIEW, headers=_AUTH, json=_patch_body())
    assert resp.status_code == 200
    data = resp.json()
    assert data == {"ok": True, "changed": True, "diff": data["diff"]}
    assert "+new content" in data["diff"]
    assert wiki.updates == 0
    [record] = _audit_records(audit_dir)
    assert record["operation_type"] == "preview:replace_between_markers"


def test_preview_page_changed_returns_409():
    wiki = FakeWiki(_page(content="other"))
    client = _setup(wiki)
    resp = client.post(PREVIEW, headers=_AUTH, json=_patch_body())
    assert resp.status_code == 409
    assert resp.json()["currentHash"] == wiki.page.contentHash


# ---- upsert ----

def test_upsert_creates_new_page_201(audit_dir):
    wiki = FakeWiki(None)
    client = _setup(wiki)
    resp = client.put(PAGES, headers=_AUTH, json=_upsert_body(path="/agent/new-page"))
    assert resp.status_code == 201
    data = resp.json()
    assert data["created"] is True
    assert data["contentHash"] == wiki.page.contentHash
    assert data["refetchFailed"] is False
    [record] = _audit_records(audit_dir)
    assert record["operation_type"] == "create"
    assert record["new_hash"] == wiki.page.contentHash


def test_upsert_update_requires_base_hash_428():
    wiki = FakeWiki(_page())
    client = _setup(wiki)
    resp = client.put(PAGES, headers=_AUTH, json=_upsert_body())
    assert resp.status_code == 428
    assert resp.headers["content-type"] == "application/problem+json"
    assert resp.json()["type"] == _PROBLEM + "precondition-required"
    assert wiki.updates == 0


def test_upsert_update_base_hash_mismatch_409():
    wiki = FakeWiki(_page())
    client = _setup(wiki)
    resp = client.put(PAGES, headers=_AUTH, json=_upsert_body(baseHash="sha256:stale"))
    assert resp.status_code == 409
    assert resp.json()["currentHash"] == _VALID_HASH
    assert wiki.updates == 0


def test_upsert_update_with_base_hash_200(audit_dir):
    wiki = FakeWiki(_page())
    client = _setup(wiki)
    resp = client.put(PAGES, headers=_AUTH, json=_upsert_body(baseHash=_VALID_HASH))
    assert resp.status_code == 200
    data = resp.json()
    assert data["created"] is False
    assert data["contentHash"] == wiki.page.contentHash
    [record] = _audit_records(audit_dir)
    assert record["base_hash"] == _VALID_HASH
    assert record["new_hash"] == wiki.page.contentHash


def test_upsert_reserved_api_path_rejected():
    wiki = FakeWiki(None)
    client = _setup(wiki)
    resp = client.put(PAGES, headers=_AUTH, json=_upsert_body(path="/api/v2/pages"))
    assert resp.status_code == 422
    assert resp.json()["type"] == _PROBLEM + "reserved-path"
    assert wiki.creates == 0


def test_upsert_wikijs_error_does_not_leak_details():
    mock = AsyncMock()
    mock.get_page_by_path.return_value = None
    mock.create_page.side_effect = WikiJsError([{"message": "SECRET internal stack"}])
    client = _setup(mock)
    resp = client.put(PAGES, headers=_AUTH, json=_upsert_body())
    assert resp.status_code == 502
    assert resp.headers["content-type"] == "application/problem+json"
    assert resp.json()["type"] == _PROBLEM + "wikijs-error"
    assert "SECRET" not in resp.text


def test_patch_unreachable_does_not_leak_details():
    mock = AsyncMock()
    mock.get_page_by_path.side_effect = httpx.ConnectError("refused by 10.0.0.5")
    client = _setup(mock)
    resp = client.post(PATCHES, headers=_AUTH, json=_patch_body())
    assert resp.status_code == 502
    assert resp.json()["type"] == _PROBLEM + "wikijs-unreachable"
    assert "10.0.0.5" not in resp.text
