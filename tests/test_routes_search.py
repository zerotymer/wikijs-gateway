from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import app, get_wikijs_client
from app.wikijs_client import WikiJsError

_SAMPLE_SEARCH_DATA = {
    "results": [
        {
            "id": 10,
            "path": "agent/deploy-log",
            "title": "Deploy Log",
            "description": "Automated deploy records",
            "locale": "ko",
        },
        {
            "id": 11,
            "path": "agent/rollback",
            "title": "Rollback Guide",
            "description": "How to rollback",
            "locale": "ko",
        },
    ],
    "suggestions": [],
    "totalHits": 2,
}

TEST_ENV = {
    "wikijs_graphql_url": "http://wiki:3000/graphql",
    "wikijs_api_token": "wiki-token",
    "gateway_admin_token": "test-admin-token",
}


def _setup(mock_client):
    app.dependency_overrides[get_settings] = lambda: Settings(**TEST_ENV)
    app.dependency_overrides[get_wikijs_client] = lambda: mock_client
    return TestClient(app)


def _teardown():
    app.dependency_overrides.clear()


def test_search_returns_results():
    mock = AsyncMock()
    mock.search_pages.return_value = _SAMPLE_SEARCH_DATA
    client = _setup(mock)
    try:
        resp = client.get("/api/v2/pages/search", params={"q": "deploy"})
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
        resp = client.get("/api/v2/pages/search", params={"q": "deploy", "limit": 1})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["results"]) == 1
        assert data["results"][0]["id"] == 10
    finally:
        _teardown()


def test_search_wikijs_error():
    mock = AsyncMock()
    mock.search_pages.side_effect = WikiJsError([{"message": "SearchError"}])
    client = _setup(mock)
    try:
        resp = client.get("/api/v2/pages/search", params={"q": "deploy"})
        assert resp.status_code == 502
        assert resp.json()["type"] == "urn:wikijs-gateway:problem:wikijs-error"
    finally:
        _teardown()


def test_search_uses_default_locale():
    mock = AsyncMock()
    mock.search_pages.return_value = {**_SAMPLE_SEARCH_DATA, "results": []}
    client = _setup(mock)
    try:
        client.get("/api/v2/pages/search", params={"q": "test"})
        mock.search_pages.assert_called_once_with("test", "ko")
    finally:
        _teardown()


def test_search_locale_override():
    mock = AsyncMock()
    mock.search_pages.return_value = {**_SAMPLE_SEARCH_DATA, "results": []}
    client = _setup(mock)
    try:
        client.get("/api/v2/pages/search", params={"q": "test", "locale": "en"})
        mock.search_pages.assert_called_once_with("test", "en")
    finally:
        _teardown()
