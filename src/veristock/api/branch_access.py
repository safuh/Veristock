"""Branch-level authorization helpers for field operations."""

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from veristock.identity.authorization import Organization
from veristock.identity.authorization_repository import AuthorizationRepository
from veristock.identity.models import User


async def require_branch_assignment(
    session: AsyncSession, user: User, organization: Organization, branch_id: str
) -> None:
    """Require field users to be explicitly assigned; branch managers bypass it."""
    authorization = AuthorizationRepository(session)
    if not await authorization.has_permission(user.id, organization.id, "stocktake.count"):
        return
    if await authorization.has_permission(user.id, organization.id, "branch.manage"):
        return
    if not await authorization.has_branch_assignment(user.id, organization.id, branch_id):
        raise HTTPException(
            status_code=403,
            detail="An active assignment to this branch is required",
        )