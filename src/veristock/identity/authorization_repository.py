"""Queries enforcing organization membership and role permissions."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .authorization import (
    MembershipRole,
    Organization,
    OrganizationMembership,
    Permission,
    Role,
    RolePermission,
)


class AuthorizationRepository:
    """Tenant-aware authorization queries.

    Callers must pass the authenticated user's subject and the organization
    selected for the current request. No browser-supplied identifier is trusted
    until this query proves active membership and permission.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def has_active_membership(self, user_id: str, organization_id: str) -> bool:
        statement = (
            select(OrganizationMembership.id)
            .join(
                Organization,
                Organization.id == OrganizationMembership.organization_id,
            )
            .where(
                OrganizationMembership.user_id == user_id,
                OrganizationMembership.organization_id == organization_id,
                OrganizationMembership.status == "active",
                Organization.status == "active",
            )
            .limit(1)
        )
        return (await self.session.scalar(statement)) is not None

    async def has_permission(
        self, user_id: str, organization_id: str, permission_code: str
    ) -> bool:
        statement = (
            select(OrganizationMembership.id)
            .join(
                Organization,
                Organization.id == OrganizationMembership.organization_id,
            )
            .join(
                MembershipRole,
                MembershipRole.membership_id == OrganizationMembership.id,
            )
            .join(Role, Role.id == MembershipRole.role_id)
            .join(RolePermission, RolePermission.role_id == Role.id)
            .join(Permission, Permission.id == RolePermission.permission_id)
            .where(
                OrganizationMembership.user_id == user_id,
                OrganizationMembership.organization_id == organization_id,
                OrganizationMembership.status == "active",
                Organization.status == "active",
                Role.scope == Organization.kind,
                Permission.code == permission_code,
            )
            .limit(1)
        )
        return (await self.session.scalar(statement)) is not None

    async def list_active_organizations(self, user_id: str) -> list[Organization]:
        statement = (
            select(Organization)
            .join(
                OrganizationMembership,
                OrganizationMembership.organization_id == Organization.id,
            )
            .where(
                OrganizationMembership.user_id == user_id,
                OrganizationMembership.status == "active",
                Organization.status == "active",
            )
            .order_by(Organization.legal_name)
        )
        result = await self.session.scalars(statement)
        return list(result.all())
