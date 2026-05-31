import pytest
import respx
import httpx
from fastapi.testclient import TestClient

from app.config import get_settings, Settings
from app.main import app

TOKEN = "test-token-abc"

TEST_ENV = {
    "wikijs_graphql_url": "http://wiki:3000/graphql",
    "wikijs_api_token": "wiki-token",
    "gateway_token": TOKEN,
    "gateway_mode": "read_only",
}


def _override_settings():
    return Settings(**TEST_ENV)


@pytest.fixture(autouse=True)
def override_settings():
    app.dependency_overrides[get_settings] = _override_settings
    yield
    app.dependency_overrides.clear()


def test_health_no_auth():
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/health")
    assert resp.status_code == 401


def test_health_wrong_token():
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/health", headers={"Authorization": "Bearer wrong"})
    assert resp.status_code == 403


@respx.mock
def test_health_wikijs_unreachable():
    respx.get("http://wiki:3000/graphql").mock(side_effect=httpx.ConnectError("refused"))
    client = TestClient(app)
    resp = client.get("/health", headers={"Authorization": f"Bearer {TOKEN}"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["mode"] == "read_only"
    assert data["wikijsReachable"] is False


@respx.mock
def test_health_wikijs_reachable():
    respx.get("http://wiki:3000/graphql").mock(return_value=httpx.Response(200))
    client = TestClient(app)
    resp = client.get("/health", headers={"Authorization": f"Bearer {TOKEN}"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["wikijsReachable"] is True
