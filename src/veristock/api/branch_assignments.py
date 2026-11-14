"""Tenant-scoped staff-to-branch assignment administration."""

from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from veristock.identity.authorization import Organization, OrganizationMembership
from veristock.identity.authorization_dependencies import (
    get_current_user,
    get_db_session,
    require_permission,
)
from veristock.identity.models import User
from veristock.organizations.models import Branch, BranchMembership

router = APIRouter(prefix="/branches/{branch_id}/members", tags=["branch assignments"])
BranchAssignmentManager = Annotated[
    Organization, Depends(require_permission("assignment.manage"))
]


class BranchMemberCreate(BaseModel):
    membership_id: str


class BranchMemberRead(BaseModel):
    membership_id: str
    user_id: str
    identifier: str
    assigned_at: str


@router.get("", response_model=list[BranchMemberRead])
async def list_branch_members(
    branch_id: str,
    organization: BranchAssignmentManager,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> list[BranchMemberRead]:
    """List active members explicitly assigned to a branch in this tenant."""
    branch = await session.scalar(
        select(Branch).where(
            Branch.id == branch_id,
            Branch.organization_id == organization.id,
        )
    )
    if branch is None:
        raise HTTPException(status_code=404, detail="Branch not found")
    rows = await session.execute(
        select(BranchMembership, OrganizationMembership, User)
        .join(
            OrganizationMembership,
            OrganizationMembership.id == BranchMembership.membership_id,
        )
        .join(User, User.id == OrganizationMembership.user_id)
        .where(
            BranchMembership.organization_id == organization.id,
            BranchMembership.branch_id == branch.id,
            OrganizationMembership.status == "active",
            User.status == "active",
        )
        .order_by(User.identifier)
    )
    return [
        BranchMemberRead(
            membership_id=membership.id,
            user_id=user.id,
            identifier=user.identifier,
            assigned_at=assignment.created_at.isoformat(),
        )
        for assignment, membership, user in rows
    ]


@router.post("", response_model=BranchMemberRead, status_code=201)
async def assign_branch_member(
    branch_id: str,
    payload: BranchMemberCreate,
    organization: BranchAssignmentManager,
    actor: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> BranchMemberRead:
    """Assign an active member of this tenant to one of its active branches."""
    branch = await session.scalar(
        select(Branch).where(
            Branch.id == branch_id,
            Branch.organization_id == organization.id,
            Branch.status == "active",
        )
    )
    if branch is None:
        raise HTTPException(status_code=404, detail="Active branch not found")
    membership = await session.scalar(
        select(OrganizationMembership)
        .join(User, User.id == OrganizationMembership.user_id)
        .where(
            OrganizationMembership.id == payload.membership_id,
            OrganizationMembership.organization_id == organization.id,
            OrganizationMembership.status == "active",
            User.status == "active",
        )
    )
    if membership is None:
        raise HTTPException(status_code=404, detail="Active organization member not found")
    assignment = BranchMembership(
        id=str(uuid4()),
        organization_id=organization.id,
        branch_id=branch.id,
        membership_id=membership.id,
        assigned_by_user_id=actor.id,
    )
    session.add(assignment)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Member is already assigned to this branch") from exc
    user = await session.get(User, membership.user_id)
    return BranchMemberRead(
        membership_id=membership.id,
        user_id=membership.user_id,
        identifier=user.identifier if user else "",
        assigned_at=assignment.created_at.isoformat() if assignment.created_at else "",
    )


@router.delete("/{membership_id}", status_code=204)
async def remove_branch_member(
    branch_id: str,
    membership_id: str,
    organization: BranchAssignmentManager,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> None:
    """Remove a member's branch assignment without changing tenant membership."""
    assignment = await session.scalar(
        select(BranchMembership).where(
            BranchMembership.organization_id == organization.id,
            BranchMembership.branch_id == branch_id,
            BranchMembership.membership_id == membership_id,
        )
    )
    if assignment is None:
        raise HTTPException(status_code=404, detail="Branch assignment not found")
    await session.delete(assignment)
    await session.commit()
