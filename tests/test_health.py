from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import app, get_wikijs_client

TEST_ENV = {
    "wikijs_graphql_url": "http://wiki:3000/graphql",
    "wikijs_api_token": "wiki-token",
    "gateway_admin_token": "test-admin-token",
}


def _client(reachable: bool) -> TestClient:
    mock = AsyncMock()
    mock.ping.return_value = reachable
    app.dependency_overrides[get_settings] = lambda: Settings(**TEST_ENV)
    app.dependency_overrides[get_wikijs_client] = lambda: mock
    return TestClient(app)


@pytest.fixture(autouse=True)
def _teardown():
    yield
    app.dependency_overrides.clear()


def test_health_live():
    resp = _client(False).get("/health/live")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert resp.headers["x-served-by"] == "wikijs-gateway"


def test_health_ready_reachable():
    resp = _client(True).get("/health/ready")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "wikijsReachable": True}


def test_health_ready_unreachable_503():
    resp = _client(False).get("/health/ready")
    assert resp.status_code == 503
    assert resp.headers["content-type"] == "application/problem+json"
    assert resp.json()["type"] == "urn:wikijs-gateway:problem:wikijs-unreachable"


def test_health_not_under_public_prefix():
    client = _client(True)
    assert client.get("/api/v2/health/live").status_code == 404
    assert "/health/live" not in client.get("/api/v2/openapi.json").json()["paths"]
