"""Branch-level authorization helpers for field operations."""

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from veristock.identity.authorization import (
    Organization,
    OrganizationMembership,
)
from veristock.identity.authorization_repository import AuthorizationRepository
from veristock.identity.models import User
from veristock.organizations.models import Branch, BranchMembership


async def accessible_branch_ids(
    session: AsyncSession, user: User, organization: Organization
) -> set[str] | None:
    """Return a field user's assigned branches, or None for tenant-wide staff.

    A user with stocktake.count is branch-scoped unless they also hold
    branch.manage. Empty sets deliberately mean no branch access.
    """
    authorization = AuthorizationRepository(session)
    if not await authorization.has_permission(user.id, organization.id, "stocktake.count"):
        return None
    if await authorization.has_permission(user.id, organization.id, "branch.manage"):
        return None

    statement = (
        select(BranchMembership.branch_id)
        .join(
            OrganizationMembership,
            OrganizationMembership.id == BranchMembership.membership_id,
        )
        .join(Branch, Branch.id == BranchMembership.branch_id)
        .where(
            BranchMembership.organization_id == organization.id,
            OrganizationMembership.organization_id == organization.id,
            OrganizationMembership.user_id == user.id,
            OrganizationMembership.status == "active",
            Branch.organization_id == organization.id,
            Branch.status == "active",
        )
    )
    result = await session.scalars(statement)
    return set(result.all())


async def require_branch_assignment(
    session: AsyncSession, user: User, organization: Organization, branch_id: str
) -> None:
    """Require field users to be explicitly assigned; branch managers bypass it."""
    allowed = await accessible_branch_ids(session, user, organization)
    if allowed is not None and branch_id not in allowed:
        raise HTTPException(
            status_code=403,
            detail="An active assignment to this branch is required",
        )
