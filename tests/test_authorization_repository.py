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
            user = User(identifier="operator@example.com", password_hash="not-a-real-hash")
            client = Organization(kind="client", legal_name="Client One")
            other_client = Organization(kind="client", legal_name="Client Two")
            platform = Organization(kind="platform", legal_name="Veristock")
            client_membership = OrganizationMembership(
                organization_id=client.id, user_id=user.id, status="active"
            )
            other_membership = OrganizationMembership(
                organization_id=other_client.id, user_id=user.id, status="active"
            )
            platform_membership = OrganizationMembership(
                organization_id=platform.id, user_id=user.id, status="active"
            )
            client_role = Role(code="client_test_admin", name="Client Test Admin", scope="client")
            platform_role = Role(
                code="platform_test_admin", name="Platform Test Admin", scope="platform"
            )
            read_permission = Permission(code="inventory.read", description="Read inventory")
            manage_permission = Permission(
                code="organization.manage", description="Manage organization"
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
                ]
            )
            await session.flush()
            session.add_all(
                [
                    MembershipRole(membership_id=client_membership.id, role_id=client_role.id),
                    MembershipRole(membership_id=platform_membership.id, role_id=platform_role.id),
                    RolePermission(role_id=client_role.id, permission_id=read_permission.id),
                    RolePermission(role_id=platform_role.id, permission_id=manage_permission.id),
                ]
            )
            await session.commit()

            authorization = AuthorizationRepository(session)
            assert await authorization.has_active_membership(user.id, client.id)
            assert not await authorization.has_permission(
                user.id, client.id, "organization.manage"
            )
            assert await authorization.has_permission(user.id, client.id, "inventory.read")
            assert not await authorization.has_permission(
                user.id, other_client.id, "inventory.read"
            )
            assert not await authorization.has_permission(
                user.id, client.id, "organization.manage"
            )
            assert await authorization.has_permission(
                user.id, platform.id, "organization.manage"
            )
            assert {org.id for org in await authorization.list_active_organizations(user.id)} == {
                client.id,
                other_client.id,
                platform.id,
            }

            client_membership.status = "suspended"
            await session.commit()
            assert not await authorization.has_active_membership(user.id, client.id)
            assert not await authorization.has_permission(user.id, client.id, "inventory.read")
    finally:
        await engine.dispose()
