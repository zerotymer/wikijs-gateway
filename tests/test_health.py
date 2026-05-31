from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import app, get_wikijs_client

TOKEN = "test-token-abc"

TEST_ENV = {
    "wikijs_graphql_url": "http://wiki:3000/graphql",
    "wikijs_api_token": "wiki-token",
    "gateway_token": TOKEN,
    "gateway_mode": "read_only",
}


def _override_settings():
    return Settings(**TEST_ENV)


def _make_client(reachable: bool):
    mock = AsyncMock()
    mock.ping.return_value = reachable
    return mock


def test_health_no_auth():
    app.dependency_overrides[get_settings] = _override_settings
    app.dependency_overrides[get_wikijs_client] = lambda: _make_client(False)
    try:
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/health")
        assert resp.status_code == 401
    finally:
        app.dependency_overrides.clear()


def test_health_wrong_token():
    app.dependency_overrides[get_settings] = _override_settings
    app.dependency_overrides[get_wikijs_client] = lambda: _make_client(False)
    try:
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/health", headers={"Authorization": "Bearer wrong"})
        assert resp.status_code == 403
    finally:
        app.dependency_overrides.clear()


def test_health_wikijs_unreachable():
    app.dependency_overrides[get_settings] = _override_settings
    app.dependency_overrides[get_wikijs_client] = lambda: _make_client(False)
    try:
        client = TestClient(app)
        resp = client.get("/health", headers={"Authorization": f"Bearer {TOKEN}"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["mode"] == "read_only"
        assert data["wikijsReachable"] is False
    finally:
        app.dependency_overrides.clear()


def test_health_wikijs_reachable():
    app.dependency_overrides[get_settings] = _override_settings
    app.dependency_overrides[get_wikijs_client] = lambda: _make_client(True)
    try:
        client = TestClient(app)
        resp = client.get("/health", headers={"Authorization": f"Bearer {TOKEN}"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["wikijsReachable"] is True
    finally:
        app.dependency_overrides.clear()
