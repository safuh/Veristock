from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine

from veristock.app import create_app
from veristock.core.config import Environment, Settings
from veristock.core.database import Base
from veristock.identity import create_sqlalchemy_auth_application


@pytest.mark.asyncio
async def test_auth_http_uses_sqlalchemy_composition(tmp_path: Path) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'auth.db'}"
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
    finally:
        await engine.dispose()

    settings = Settings(
        environment=Environment.TEST,
        database_url=database_url,
        allow_self_registration=True,
    )

    def application_factory(session):
        return create_sqlalchemy_auth_application(
            session,
            secret_key="x" * 32,
            access_token_lifetime=timedelta(minutes=15),
            refresh_token_lifetime=timedelta(days=7),
        )

    with TestClient(create_app(settings, application_factory)) as client:
        registered = client.post(
            "/api/auth/register",
            json={"identifier": "alice@example.com", "password": "correct horse"},
        )
        assert registered.status_code == 201

        logged_in = client.post(
            "/api/auth/login",
            json={"identifier": "alice@example.com", "password": "correct horse"},
        )
        assert logged_in.status_code == 200
        tokens = logged_in.json()

        refreshed = client.post(
            "/api/auth/refresh",
            json={"refresh_token": tokens["refresh_token"]},
        )
        assert refreshed.status_code == 200

        replay = client.post(
            "/api/auth/refresh",
            json={"refresh_token": tokens["refresh_token"]},
        )
        assert replay.status_code == 401

        logged_out = client.post(
            "/api/auth/logout",
            json={"refresh_token": refreshed.json()["refresh_token"]},
        )
        assert logged_out.status_code == 204

        revoked = client.post(
            "/api/auth/refresh",
            json={"refresh_token": refreshed.json()["refresh_token"]},
        )
        assert revoked.status_code == 401


def test_self_registration_is_disabled_by_default() -> None:
    settings = Settings(
        environment=Environment.TEST,
        database_url="sqlite+aiosqlite:///:memory:",
    )
    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/api/auth/register",
            json={"identifier": "uninvited@example.com", "password": "correct horse"},
        )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "registration_disabled"
