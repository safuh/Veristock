# ruff: noqa: E501
from datetime import timedelta
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from veristock.app import create_app
from veristock.auth.tokens import TokenService
from veristock.core.config import Environment, Settings
from veristock.core.database import Base
from veristock.identity import MembershipRole, Organization, OrganizationMembership, Permission, Role, RolePermission, User
from veristock.organizations.models import Branch

@pytest.mark.asyncio
async def test_branch_api_is_tenant_scoped(tmp_path) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'tenant-admin.db'}"
    engine = create_async_engine(database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    user_id, org_id, other_org_id = str(uuid4()), str(uuid4()), str(uuid4())
    role_id, membership_id = str(uuid4()), str(uuid4())
    manage_id, read_id, other_branch_id = str(uuid4()), str(uuid4()), str(uuid4())
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with factory() as session:
            session.add_all([
                User(id=user_id, identifier="manager@example.com", password_hash="x"),
                Organization(id=org_id, kind="client", legal_name="Tenant A"),
                Organization(id=other_org_id, kind="client", legal_name="Tenant B"),
                OrganizationMembership(id=membership_id, organization_id=org_id, user_id=user_id, status="active"),
                Role(id=role_id, code="branch_manager", name="Branch Manager", scope="client"),
                Permission(id=manage_id, code="branch.manage", description="Manage branches"),
                Permission(id=read_id, code="branch.read", description="Read branches"),
                MembershipRole(membership_id=membership_id, role_id=role_id),
                RolePermission(role_id=role_id, permission_id=manage_id),
                RolePermission(role_id=role_id, permission_id=read_id),
                Branch(id=other_branch_id, organization_id=other_org_id, code="B-1", name="Other Branch"),
            ])
            await session.commit()
    finally:
        await engine.dispose()
    settings = Settings(environment=Environment.TEST, database_url=database_url)
    tokens = TokenService("x" * 32)
    token = tokens.create(user_id, timedelta(minutes=10), token_type="access")
    with TestClient(create_app(settings, access_token_service=tokens)) as client:
        headers = {"Authorization": f"Bearer {token}", "X-Organization-ID": org_id}
        created = client.post("/api/branches", headers=headers, json={"code": " wh-01 ", "name": "Main Warehouse"})
        assert created.status_code == 201
        assert created.json()["code"] == "WH-01"
        assert created.json()["organization_id"] == org_id
        listed = client.get("/api/branches", headers=headers)
        assert listed.status_code == 200
        assert [item["organization_id"] for item in listed.json()] == [org_id]
        denied = client.patch(f"/api/branches/{other_branch_id}", headers=headers, json={"name": "Tampered"})
        assert denied.status_code == 404
