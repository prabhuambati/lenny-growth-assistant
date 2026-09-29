"""Foundation tests: startup, /health, /config/model. No RAG/agent coverage."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.database import get_db
from app.main import app


@pytest.fixture
def db_session():
    db = MagicMock()
    db.execute.return_value = None
    return db


@pytest.fixture
def client(db_session):
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        with patch("app.main.init_db"):
            with TestClient(app) as test_client:
                yield test_client
    finally:
        app.dependency_overrides.clear()


def test_health_ok_when_db_and_ollama_up(client):
    with patch("app.routers.health.OllamaClient") as ollama_cls:
        ollama_cls.return_value.is_reachable = AsyncMock(return_value=True)
        response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["error"] is None
    assert body["data"]["status"] == "ok"
    assert body["data"]["database"] is True
    assert body["data"]["ollama"] is True
    assert body["data"]["active_provider"] == get_settings().model_provider


def test_health_degraded_when_ollama_down(client):
    with patch("app.routers.health.OllamaClient") as ollama_cls:
        ollama_cls.return_value.is_reachable = AsyncMock(return_value=False)
        response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["error"] is None
    assert body["data"]["status"] == "degraded"
    assert body["data"]["ollama"] is False


def test_get_config_model(client):
    response = client.get("/config/model")
    assert response.status_code == 200
    body = response.json()
    assert body["error"] is None
    assert body["data"]["active_provider"] in {"ollama", "anthropic", "openai"}
    assert body["data"]["available_providers"] == ["ollama", "anthropic", "openai", "gemini"]


def test_put_config_model_rejects_unreachable_cloud(client):
    with patch("app.routers.config.build_client") as build_client:
        build_client.return_value.is_reachable = AsyncMock(return_value=False)
        response = client.put("/config/model", json={"provider": "anthropic"})

    assert response.status_code == 422
    body = response.json()
    assert body["data"] is None
    assert body["error"]["code"] == "PROVIDER_UNAVAILABLE"


def test_put_config_model_switches_when_reachable(client):
    original = get_settings().model_provider
    try:
        with patch("app.routers.config.build_client") as build_client:
            build_client.return_value.is_reachable = AsyncMock(return_value=True)
            response = client.put("/config/model", json={"provider": "ollama"})

        assert response.status_code == 200
        body = response.json()
        assert body["error"] is None
        assert body["data"]["active_provider"] == "ollama"
    finally:
        get_settings().model_provider = original


def test_put_config_model_rejects_gemini_without_key(client):
    original = get_settings().model_provider
    get_settings().gemini_api_key = None
    try:
        response = client.put("/config/model", json={"provider": "gemini"})

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "PROVIDER_UNAVAILABLE"
    finally:
        get_settings().model_provider = original
