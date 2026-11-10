from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from veristock.app import create_app
from veristock.auth.tokens import TokenService
from veristock.core.config import Environment, Settings
from veristock.core.database import Base
from veristock.identity import Organization, OrganizationMembership, User


@pytest.mark.asyncio
async def test_identity_endpoints_require_valid_user_and_tenant_membership(
    tmp_path,
) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'identity-api.db'}"
    engine = create_async_engine(database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    user_id = str(uuid4())
    other_user_id = str(uuid4())
    organization_id = str(uuid4())
    other_organization_id = str(uuid4())
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with factory() as session:
            session.add_all(
                [
                    User(
                        id=user_id,
                        identifier="member@example.com",
                        password_hash="not-a-real-hash",
                    ),
                    User(
                        id=other_user_id,
                        identifier="outsider@example.com",
                        password_hash="not-a-real-hash",
                    ),
                    Organization(
                        id=organization_id,
                        kind="client",
                        legal_name="Member Client",
                    ),
                    Organization(
                        id=other_organization_id,
                        kind="client",
                        legal_name="Other Client",
                    ),
                    OrganizationMembership(
                        id=str(uuid4()),
                        organization_id=organization_id,
                        user_id=user_id,
                        status="active",
                    ),
                ]
            )
            await session.commit()
    finally:
        await engine.dispose()

    settings = Settings(
        environment=Environment.TEST,
        database_url=database_url,
    )
    token_service = TokenService("v" * 32)
    access_token = token_service.create(
        user_id, timedelta(minutes=10), token_type="access"
    )
    outsider_token = token_service.create(
        other_user_id, timedelta(minutes=10), token_type="access"
    )

    with TestClient(
        create_app(settings, access_token_service=token_service)
    ) as client:
        no_token = client.get("/api/identity/me")
        assert no_token.status_code == 401

        me = client.get(
            "/api/identity/me",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert me.status_code == 200
        assert me.json()["id"] == user_id
        assert [org["id"] for org in me.json()["organizations"]] == [organization_id]

        context = client.get(
            "/api/identity/context",
            headers={
                "Authorization": f"Bearer {access_token}",
                "X-Organization-ID": organization_id,
            },
        )
        assert context.status_code == 200
        assert context.json()["id"] == organization_id

        cross_tenant = client.get(
            "/api/identity/context",
            headers={
                "Authorization": f"Bearer {access_token}",
                "X-Organization-ID": other_organization_id,
            },
        )
        assert cross_tenant.status_code == 403

        outsider = client.get(
            "/api/identity/context",
            headers={
                "Authorization": f"Bearer {outsider_token}",
                "X-Organization-ID": organization_id,
            },
        )
        assert outsider.status_code == 403

        invalid_type = token_service.create(
            user_id, timedelta(minutes=10), token_type="refresh"
        )
        wrong_token_type = client.get(
            "/api/identity/me",
            headers={"Authorization": f"Bearer {invalid_type}"},
        )
        assert wrong_token_type.status_code == 401
