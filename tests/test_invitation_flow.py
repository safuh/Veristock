"""HTTP tests for single-use organization invitations."""

from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
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
from veristock.invitations.models import OrganizationInvitation


@pytest.mark.asyncio
async def test_invitation_is_single_use_and_activates_membership(tmp_path) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'invitation-flow.db'}"
    engine = create_async_engine(database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    inviter_id = str(uuid4())
    organization_id = str(uuid4())
    membership_id = str(uuid4())
    manager_role_id = str(uuid4())
    invitee_role_id = str(uuid4())
    invite_permission_id = str(uuid4())

    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with factory() as session:
            session.add_all(
                [
                    User(
                        id=inviter_id,
                        identifier="admin@example.com",
                        password_hash="unused",
                        status="active",
                    ),
                    Organization(
                        id=organization_id,
                        kind="client",
                        legal_name="Example Client",
                        status="active",
                    ),
                    OrganizationMembership(
                        id=membership_id,
                        organization_id=organization_id,
                        user_id=inviter_id,
                        status="active",
                    ),
                    Role(
                        id=manager_role_id,
                        code="client_admin",
                        name="Client Administrator",
                        scope="client",
                    ),
                    Role(
                        id=invitee_role_id,
                        code="client_readonly",
                        name="Client Read-only",
                        scope="client",
                    ),
                    Role(
                        id=str(uuid4()),
                        code="client_manager",
                        name="Client Manager",
                        scope="client",
                    ),
                    Permission(
                        id=invite_permission_id,
                        code="employee.invite",
                        description="Invite organization members",
                    ),
                    RolePermission(
                        role_id=manager_role_id,
                        permission_id=invite_permission_id,
                    ),
                    MembershipRole(
                        membership_id=membership_id,
                        role_id=manager_role_id,
                    ),
                ]
            )
            await session.commit()

        token_service = TokenService("i" * 32)
        access_token = token_service.create(
            inviter_id, timedelta(minutes=10), token_type="access"
        )
        settings = Settings(environment=Environment.TEST, database_url=database_url)
        with TestClient(
            create_app(settings, access_token_service=token_service)
        ) as client:
            headers = {
                "Authorization": f"Bearer {access_token}",
                "X-Organization-ID": organization_id,
            }
            created = client.post(
                "/api/invitations",
                headers=headers,
                json={
                    "email": "New.Member@Example.com",
                    "role_code": "client_readonly",
                },
            )
            assert created.status_code == 201
            invite = created.json()
            assert invite["email"] == "new.member@example.com"
            assert invite["role_code"] == "client_readonly"
            assert invite["invitation_token"]

            accepted = client.post(
                "/api/invitations/accept",
                json={
                    "token": invite["invitation_token"],
                    "password": "A-long-unique-password-2026",
                },
            )
            assert accepted.status_code == 200
            accepted_body = accepted.json()
            assert accepted_body["organization_id"] == organization_id
            assert accepted_body["role_code"] == "client_readonly"

            members = client.get("/api/memberships", headers=headers)
            assert members.status_code == 200
            assert len(members.json()) == 2

            granted = client.post(
                f"/api/memberships/{accepted_body['membership_id']}/roles",
                headers=headers,
                json={"role_code": "client_manager"},
            )
            assert granted.status_code == 200
            assert "client_manager" in granted.json()["role_codes"]

            revoked_role = client.delete(
                f"/api/memberships/{accepted_body['membership_id']}/roles/client_manager",
                headers=headers,
            )
            assert revoked_role.status_code == 204

            last_admin_role = client.delete(
                f"/api/memberships/{membership_id}/roles/client_admin",
                headers=headers,
            )
            assert last_admin_role.status_code == 409

            last_admin_status = client.patch(
                f"/api/memberships/{membership_id}",
                headers=headers,
                json={"status": "suspended"},
            )
            assert last_admin_status.status_code == 409

            replay = client.post(
                "/api/invitations/accept",
                json={
                    "token": invite["invitation_token"],
                    "password": "A-long-unique-password-2026",
                },
            )
            assert replay.status_code == 400

        async with factory() as session:
            invitation = await session.scalar(
                select(OrganizationInvitation).where(
                    OrganizationInvitation.id == invite["id"]
                )
            )
            assert invitation is not None
            assert invitation.token_hash != invite["invitation_token"]
            assert invitation.accepted_at is not None

            invitee = await session.scalar(
                select(User).where(User.identifier == "new.member@example.com")
            )
            assert invitee is not None
            assert invitee.password_hash != "A-long-unique-password-2026"

            membership = await session.scalar(
                select(OrganizationMembership).where(
                    OrganizationMembership.organization_id == organization_id,
                    OrganizationMembership.user_id == invitee.id,
                )
            )
            assert membership is not None
            assert membership.status == "active"
            grant = await session.scalar(
                select(MembershipRole.id).where(
                    MembershipRole.membership_id == membership.id,
                    MembershipRole.role_id == invitee_role_id,
                )
            )
            assert grant is not None
    finally:
        await engine.dispose()
