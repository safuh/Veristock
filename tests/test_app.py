from fastapi.testclient import TestClient

from veristock.app import create_app
from veristock.core.config import Settings


def make_settings() -> Settings:
    return Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        cors_origins=["https://example.com"],
    )


def test_health_endpoint() -> None:
    with TestClient(create_app(make_settings())) as client:
        response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_request_id_is_generated_and_returned() -> None:
    with TestClient(create_app(make_settings())) as client:
        response = client.get("/api/health")

    assert response.status_code == 200
    assert response.headers.get("X-Request-ID")


def test_valid_request_id_is_propagated() -> None:
    request_id = "2f3b5b74-6a89-4e8e-a1b0-8e4ef1c4f9b1"
    with TestClient(create_app(make_settings())) as client:
        response = client.get("/api/health", headers={"X-Request-ID": request_id})

    assert response.headers["X-Request-ID"] == request_id


def test_invalid_request_id_is_replaced() -> None:
    with TestClient(create_app(make_settings())) as client:
        response = client.get("/api/health", headers={"X-Request-ID": "not-a-uuid"})

    assert response.headers["X-Request-ID"] != "not-a-uuid"


def test_not_found_uses_error_envelope() -> None:
    with TestClient(create_app(make_settings())) as client:
        response = client.get("/api/does-not-exist")

    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "not_found"
    assert body["request_id"] == response.headers["X-Request-ID"]


def test_cors_policy_is_explicit() -> None:
    with TestClient(create_app(make_settings())) as client:
        response = client.options(
            "/api/health",
            headers={
                "Origin": "https://example.com",
                "Access-Control-Request-Method": "GET",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://example.com"


def test_optional_compatible_ai_provider_is_composed_from_settings() -> None:
    settings = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        ai_provider="openai-compatible",
        ai_base_url="http://localhost:11434/v1",
        ai_model="local-model",
    )

    app = create_app(settings)

    assert app.state.ai_service.is_configured is True
    assert app.state.ai_service.provider_name == "openai-compatible"
    assert app.state.ai_service.model_name == "local-model"


def test_ai_provider_requires_base_url_and_model() -> None:
    import pytest

    with pytest.raises(ValueError, match="AI_BASE_URL and AI_MODEL"):
        Settings(
            database_url="sqlite+aiosqlite:///:memory:",
            ai_provider="openai-compatible",
        )
