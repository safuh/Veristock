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


@pytest.mark.asyncio
async def test_app_composes_authentication_from_jwt_settings(tmp_path: Path) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'configured-auth.db'}"
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
    finally:
        await engine.dispose()

    settings = Settings(
        environment=Environment.TEST,
        database_url=database_url,
        jwt_secret_key="z" * 48,
        allow_self_registration=True,
    )
    with TestClient(create_app(settings)) as client:
        registered = client.post(
            "/api/auth/register",
            json={"identifier": "configured@example.com", "password": "correct horse"},
        )
        assert registered.status_code == 201

        logged_in = client.post(
            "/api/auth/login",
            json={"identifier": "configured@example.com", "password": "correct horse"},
        )
        assert logged_in.status_code == 200
        access_token = logged_in.json()["access_token"]

        current_user = client.get(
            "/api/identity/me",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert current_user.status_code == 200
        assert current_user.json()["identifier"] == "configured@example.com"


@pytest.mark.asyncio
async def test_browser_auth_uses_httponly_refresh_cookie_and_csrf(tmp_path: Path) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'browser-auth.db'}"
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
    finally:
        await engine.dispose()

    settings = Settings(
        environment=Environment.TEST,
        database_url=database_url,
        jwt_secret_key="b" * 48,
        allow_self_registration=True,
    )
    with TestClient(create_app(settings)) as client:
        registered = client.post(
            "/api/auth/register",
            json={"identifier": "browser@example.com", "password": "correct horse"},
        )
        assert registered.status_code == 201

        logged_in = client.post(
            "/api/auth/browser/login",
            json={"identifier": "browser@example.com", "password": "correct horse"},
        )
        assert logged_in.status_code == 200
        assert "refresh_token" not in logged_in.json()
        assert any(
            "veristock_refresh=" in value and "HttpOnly" in value
            for value in logged_in.headers.get_list("set-cookie")
        )

        old_refresh = client.cookies.get("veristock_refresh")
        csrf_token = client.cookies.get("veristock_csrf")
        assert old_refresh
        assert csrf_token

        missing_csrf = client.post("/api/auth/browser/refresh")
        assert missing_csrf.status_code == 403

        refreshed = client.post(
            "/api/auth/browser/refresh",
            headers={"X-CSRF-Token": csrf_token},
        )
        assert refreshed.status_code == 200
        assert "refresh_token" not in refreshed.json()
        new_refresh = client.cookies.get("veristock_refresh")
        new_csrf = client.cookies.get("veristock_csrf")
        assert new_refresh and new_refresh != old_refresh
        assert new_csrf and new_csrf != csrf_token

        replay = client.post(
            "/api/auth/refresh",
            json={"refresh_token": old_refresh},
        )
        assert replay.status_code == 401

        blocked_logout = client.post("/api/auth/browser/logout")
        assert blocked_logout.status_code == 403

        logged_out = client.post(
            "/api/auth/browser/logout",
            headers={"X-CSRF-Token": new_csrf},
        )
        assert logged_out.status_code == 204
        assert client.cookies.get("veristock_refresh") is None

        revoked = client.post(
            "/api/auth/refresh",
            json={"refresh_token": new_refresh},
        )
        assert revoked.status_code == 401
