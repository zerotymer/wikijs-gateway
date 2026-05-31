from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import app, get_wikijs_client
from app.wikijs_client import WikiJsError

TOKEN = "test-token-abc"

_SAMPLE_SEARCH_DATA = {
    "results": [
        {
            "id": 10,
            "path": "agent/deploy-log",
            "title": "Deploy Log",
            "description": "Automated deploy records",
            "locale": "ko",
            "updatedAt": "2026-05-31T10:00:00Z",
        },
        {
            "id": 11,
            "path": "agent/rollback",
            "title": "Rollback Guide",
            "description": "How to rollback",
            "locale": "ko",
            "updatedAt": "2026-05-30T09:00:00Z",
        },
    ],
    "suggestions": [],
    "totalHits": 2,
}


def _settings(**overrides):
    base = {
        "wikijs_graphql_url": "http://wiki:3000/graphql",
        "wikijs_api_token": "wiki-token",
        "wikijs_admin_api_token": "wiki-admin-token",
        "gateway_token": TOKEN,
        "gateway_admin_token": "admin-token-unused",
        "gateway_mode": "read_only",
        "default_locale": "ko",
        "allow_path_prefixes": "/agent,/draft",
    }
    base.update(overrides)
    return Settings(**base)


def _setup(mock_client, **setting_overrides):
    app.dependency_overrides[get_settings] = lambda: _settings(**setting_overrides)
    app.dependency_overrides[get_wikijs_client] = lambda: mock_client
    return TestClient(app)


def _teardown():
    app.dependency_overrides.clear()


def test_search_returns_results():
    mock = AsyncMock()
    mock.search_pages.return_value = _SAMPLE_SEARCH_DATA
    client = _setup(mock)
    try:
        resp = client.get(
            "/pages/search",
            headers={"Authorization": f"Bearer {TOKEN}"},
            params={"query": "deploy"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["query"] == "deploy"
        assert len(data["results"]) == 2
        assert data["results"][0]["path"] == "agent/deploy-log"
        assert data["totalHits"] == 2
        mock.search_pages.assert_called_once_with("deploy", "ko")
    finally:
        _teardown()


def test_search_limit():
    mock = AsyncMock()
    mock.search_pages.return_value = _SAMPLE_SEARCH_DATA
    client = _setup(mock)
    try:
        resp = client.get(
            "/pages/search",
            headers={"Authorization": f"Bearer {TOKEN}"},
            params={"query": "deploy", "limit": 1},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["results"]) == 1
        assert data["results"][0]["id"] == 10
    finally:
        _teardown()


def test_search_read_only_allowed():
    mock = AsyncMock()
    mock.search_pages.return_value = _SAMPLE_SEARCH_DATA
    client = _setup(mock, gateway_mode="read_only")
    try:
        resp = client.get(
            "/pages/search",
            headers={"Authorization": f"Bearer {TOKEN}"},
            params={"query": "test"},
        )
        assert resp.status_code == 200
    finally:
        _teardown()


def test_search_wikijs_error():
    mock = AsyncMock()
    mock.search_pages.side_effect = WikiJsError([{"message": "SearchError"}])
    client = _setup(mock)
    try:
        resp = client.get(
            "/pages/search",
            headers={"Authorization": f"Bearer {TOKEN}"},
            params={"query": "deploy"},
        )
        assert resp.status_code == 502
        assert resp.json()["detail"]["error"] == "WIKIJS_ERROR"
    finally:
        _teardown()


def test_search_requires_token():
    mock = AsyncMock()
    client = _setup(mock)
    try:
        resp = client.get(
            "/pages/search",
            params={"query": "deploy"},
        )
        assert resp.status_code == 401
    finally:
        _teardown()


def test_search_uses_default_locale():
    mock = AsyncMock()
    mock.search_pages.return_value = {**_SAMPLE_SEARCH_DATA, "results": []}
    client = _setup(mock, default_locale="en")
    try:
        client.get(
            "/pages/search",
            headers={"Authorization": f"Bearer {TOKEN}"},
            params={"query": "test"},
        )
        mock.search_pages.assert_called_once_with("test", "en")
    finally:
        _teardown()


def test_search_locale_override():
    mock = AsyncMock()
    mock.search_pages.return_value = {**_SAMPLE_SEARCH_DATA, "results": []}
    client = _setup(mock, default_locale="ko")
    try:
        client.get(
            "/pages/search",
            headers={"Authorization": f"Bearer {TOKEN}"},
            params={"query": "test", "locale": "en"},
        )
        mock.search_pages.assert_called_once_with("test", "en")
    finally:
        _teardown()
