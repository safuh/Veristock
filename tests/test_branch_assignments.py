"""Branch assignment administration API tests."""

from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from veristock.app import create_app
from veristock.auth.tokens import TokenService
from veristock.core.config import Environment, Settings
from veristock.core.database import Base
from veristock.identity import (
    MembershipRole,
    Organization,
    OrganizationMembership,
    Permission,
    Role,
    RolePermission,
    User,
)
from veristock.organizations.models import Branch


@pytest.mark.asyncio
async def test_branch_members_can_be_assigned_and_removed_within_tenant(tmp_path) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'branch-assignment.db'}"
    engine = create_async_engine(database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    actor_id, member_id, org_id, other_org_id = (
        str(uuid4()), str(uuid4()), str(uuid4()), str(uuid4())
    )
    actor_membership_id, member_membership_id = str(uuid4()), str(uuid4())
    role_id, permission_id, grant_id = str(uuid4()), str(uuid4()), str(uuid4())
    branch_id, other_branch_id = str(uuid4()), str(uuid4())
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with factory() as session:
            session.add_all([
                User(id=actor_id, identifier="admin@example.com", password_hash="x"),
                User(id=member_id, identifier="counter@example.com", password_hash="x"),
                Organization(id=org_id, kind="client", legal_name="Tenant A"),
                Organization(id=other_org_id, kind="client", legal_name="Tenant B"),
                OrganizationMembership(id=actor_membership_id, organization_id=org_id, user_id=actor_id, status="active"),
                OrganizationMembership(id=member_membership_id, organization_id=org_id, user_id=member_id, status="active"),
                Role(id=role_id, code="client_admin", name="Client Admin", scope="client"),
                Permission(id=permission_id, code="assignment.manage", description="Manage branch assignments"),
                MembershipRole(id=grant_id, membership_id=actor_membership_id, role_id=role_id),
                RolePermission(id=str(uuid4()), role_id=role_id, permission_id=permission_id),
                Branch(id=branch_id, organization_id=org_id, code="HQ", name="Head Office"),
                Branch(id=other_branch_id, organization_id=other_org_id, code="OTHER", name="Other Tenant"),
            ])
            await session.commit()
    finally:
        await engine.dispose()

    settings = Settings(environment=Environment.TEST, database_url=database_url)
    tokens = TokenService("x" * 32)
    token = tokens.create(actor_id, timedelta(minutes=10), token_type="access")
    with TestClient(create_app(settings, access_token_service=tokens)) as client:
        headers = {"Authorization": f"Bearer {token}", "X-Organization-ID": org_id}
        created = client.post(
            f"/api/branches/{branch_id}/members",
            headers=headers,
            json={"membership_id": member_membership_id},
        )
        assert created.status_code == 201
        assert created.json()["membership_id"] == member_membership_id
        listed = client.get(f"/api/branches/{branch_id}/members", headers=headers)
        assert listed.status_code == 200
        assert [row["identifier"] for row in listed.json()] == ["counter@example.com"]
        duplicate = client.post(
            f"/api/branches/{branch_id}/members",
            headers=headers,
            json={"membership_id": member_membership_id},
        )
        assert duplicate.status_code == 409
        cross_tenant = client.post(
            f"/api/branches/{other_branch_id}/members",
            headers=headers,
            json={"membership_id": member_membership_id},
        )
        assert cross_tenant.status_code == 404
        removed = client.delete(
            f"/api/branches/{branch_id}/members/{member_membership_id}",
            headers=headers,
        )
        assert removed.status_code == 204
        assert client.get(f"/api/branches/{branch_id}/members", headers=headers).json() == []
