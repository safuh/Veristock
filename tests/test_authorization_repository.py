from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from veristock.core.database import Base, create_session_factory
from veristock.identity import (
    AuthorizationRepository,
    MembershipRole,
    Organization,
    OrganizationMembership,
    Permission,
    Role,
    RolePermission,
    User,
)


@pytest.mark.asyncio
async def test_authorization_is_scoped_to_active_membership_and_org_kind() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = create_session_factory(engine)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        async with factory() as session:
            user_id = str(uuid4())
            client_id = str(uuid4())
            other_client_id = str(uuid4())
            platform_id = str(uuid4())
            client_membership_id = str(uuid4())
            other_membership_id = str(uuid4())
            platform_membership_id = str(uuid4())
            client_role_id = str(uuid4())
            platform_role_id = str(uuid4())
            read_permission_id = str(uuid4())
            manage_permission_id = str(uuid4())

            user = User(
                id=user_id,
                identifier="operator@example.com",
                password_hash="not-a-real-hash",
            )
            client = Organization(
                id=client_id, kind="client", legal_name="Client One"
            )
            other_client = Organization(
                id=other_client_id, kind="client", legal_name="Client Two"
            )
            platform = Organization(
                id=platform_id, kind="platform", legal_name="Veristock"
            )
            client_membership = OrganizationMembership(
                id=client_membership_id,
                organization_id=client_id,
                user_id=user_id,
                status="active",
            )
            other_membership = OrganizationMembership(
                id=other_membership_id,
                organization_id=other_client_id,
                user_id=user_id,
                status="active",
            )
            platform_membership = OrganizationMembership(
                id=platform_membership_id,
                organization_id=platform_id,
                user_id=user_id,
                status="active",
            )
            client_role = Role(
                id=client_role_id,
                code="client_test_admin",
                name="Client Test Admin",
                scope="client",
            )
            platform_role = Role(
                id=platform_role_id,
                code="platform_test_admin",
                name="Platform Test Admin",
                scope="platform",
            )
            read_permission = Permission(
                id=read_permission_id,
                code="inventory.read",
                description="Read inventory",
            )
            manage_permission = Permission(
                id=manage_permission_id,
                code="organization.manage",
                description="Manage organization",
            )
            session.add_all(
                [
                    user,
                    client,
                    other_client,
                    platform,
                    client_membership,
                    other_membership,
                    platform_membership,
                    client_role,
                    platform_role,
                    read_permission,
                    manage_permission,
                    MembershipRole(
                        membership_id=client_membership_id, role_id=client_role_id
                    ),
                    MembershipRole(
                        membership_id=platform_membership_id, role_id=platform_role_id
                    ),
                    RolePermission(
                        role_id=client_role_id, permission_id=read_permission_id
                    ),
                    RolePermission(
                        role_id=platform_role_id, permission_id=manage_permission_id
                    ),
                ]
            )
            await session.commit()

            authorization = AuthorizationRepository(session)
            assert await authorization.has_active_membership(user_id, client_id)
            assert await authorization.has_permission(
                user_id, client_id, "inventory.read"
            )
            assert not await authorization.has_permission(
                user_id, other_client_id, "inventory.read"
            )
            assert not await authorization.has_permission(
                user_id, client_id, "organization.manage"
            )
            assert await authorization.has_permission(
                user_id, platform_id, "organization.manage"
            )
            assert {
                organization.id
                for organization in await authorization.list_active_organizations(user_id)
            } == {client_id, other_client_id, platform_id}

            client_membership.status = "suspended"
            await session.commit()
            assert not await authorization.has_active_membership(user_id, client_id)
            assert not await authorization.has_permission(
                user_id, client_id, "inventory.read"
            )
    finally:
        await engine.dispose()
