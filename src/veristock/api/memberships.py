"""Tenant-scoped organization membership and role administration."""

from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from veristock.identity.authorization import (
    MembershipRole,
    Organization,
    OrganizationMembership,
    Permission,
    Role,
    RolePermission,
)
from veristock.identity.authorization_dependencies import (
    get_current_user,
    get_db_session,
    require_permission,
)
from veristock.identity.models import User

router = APIRouter(prefix="/memberships", tags=["memberships"])
MembershipManager = Annotated[
    Organization, Depends(require_permission("employee.invite"))
]


class MembershipRead(BaseModel):
    id: str
    user_id: str
    identifier: str
    status: str
    role_codes: list[str]


class RoleGrantRequest(BaseModel):
    role_code: str = Field(min_length=2, max_length=80)


class MembershipStatusUpdate(BaseModel):
    status: str


async def _active_invitation_admin_count(
    session: AsyncSession, organization_id: str
) -> int:
    statement = (
        select(func.count(func.distinct(OrganizationMembership.id)))
        .join(
            MembershipRole,
            MembershipRole.membership_id == OrganizationMembership.id,
        )
        .join(Role, Role.id == MembershipRole.role_id)
        .join(RolePermission, RolePermission.role_id == Role.id)
        .join(Permission, Permission.id == RolePermission.permission_id)
        .where(
            OrganizationMembership.organization_id == organization_id,
            OrganizationMembership.status == "active",
            Permission.code == "employee.invite",
        )
    )
    return int((await session.scalar(statement)) or 0)


async def _membership_has_invite_permission(
    session: AsyncSession, membership_id: str
) -> bool:
    statement = (
        select(MembershipRole.id)
        .join(Role, Role.id == MembershipRole.role_id)
        .join(RolePermission, RolePermission.role_id == Role.id)
        .join(Permission, Permission.id == RolePermission.permission_id)
        .where(
            MembershipRole.membership_id == membership_id,
            Permission.code == "employee.invite",
        )
        .limit(1)
    )
    return (await session.scalar(statement)) is not None


@router.get("", response_model=list[MembershipRead])
async def list_memberships(
    organization: MembershipManager,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> list[MembershipRead]:
    """List members and their tenant-scoped role codes."""
    rows = await session.execute(
        select(
            OrganizationMembership,
            User.identifier,
            Role.code,
        )
        .join(User, User.id == OrganizationMembership.user_id)
        .outerjoin(
            MembershipRole,
            MembershipRole.membership_id == OrganizationMembership.id,
        )
        .outerjoin(Role, Role.id == MembershipRole.role_id)
        .where(OrganizationMembership.organization_id == organization.id)
        .order_by(User.identifier, Role.code)
    )
    grouped: dict[str, MembershipRead] = {}
    for membership, identifier, role_code in rows:
        item = grouped.get(membership.id)
        if item is None:
            item = MembershipRead(
                id=membership.id,
                user_id=membership.user_id,
                identifier=identifier,
                status=membership.status,
                role_codes=[],
            )
            grouped[membership.id] = item
        if role_code is not None:
            item.role_codes.append(role_code)
    return list(grouped.values())


@router.post("/{membership_id}/roles", response_model=MembershipRead)
async def grant_membership_role(
    membership_id: str,
    payload: RoleGrantRequest,
    organization: MembershipManager,
    actor: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> MembershipRead:
    """Grant a role only within the selected organization and its role scope."""
    membership = await session.scalar(
        select(OrganizationMembership).where(
            OrganizationMembership.id == membership_id,
            OrganizationMembership.organization_id == organization.id,
        )
    )
    if membership is None:
        raise HTTPException(status_code=404, detail="Membership not found")
    role = await session.scalar(
        select(Role).where(
            Role.code == payload.role_code,
            Role.scope == organization.kind,
        )
    )
    if role is None:
        raise HTTPException(status_code=422, detail="Role is not valid for this organization")
    if role.code == "platform_owner":
        owner_grant = await session.scalar(
            select(MembershipRole.id)
            .join(
                OrganizationMembership,
                OrganizationMembership.id == MembershipRole.membership_id,
            )
            .join(Role, Role.id == MembershipRole.role_id)
            .where(
                OrganizationMembership.user_id == actor.id,
                OrganizationMembership.organization_id == organization.id,
                OrganizationMembership.status == "active",
                Role.code == "platform_owner",
            )
            .limit(1)
        )
        if owner_grant is None:
            raise HTTPException(
                status_code=403,
                detail="Only a platform owner may grant the platform_owner role",
            )
    existing = await session.scalar(
        select(MembershipRole.id).where(
            MembershipRole.membership_id == membership.id,
            MembershipRole.role_id == role.id,
        )
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="Role is already assigned")
    session.add(
        MembershipRole(
            id=str(uuid4()),
            membership_id=membership.id,
            role_id=role.id,
        )
    )
    await session.commit()
    identifier = await session.scalar(select(User.identifier).where(User.id == membership.user_id))
    roles = await session.scalars(
        select(Role.code)
        .join(MembershipRole, MembershipRole.role_id == Role.id)
        .where(MembershipRole.membership_id == membership.id)
        .order_by(Role.code)
    )
    return MembershipRead(
        id=membership.id,
        user_id=membership.user_id,
        identifier=identifier or "",
        status=membership.status,
        role_codes=list(roles.all()),
    )


@router.delete("/{membership_id}/roles/{role_code}", status_code=204)
async def revoke_membership_role(
    membership_id: str,
    role_code: str,
    organization: MembershipManager,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> None:
    """Revoke a tenant role without allowing the final tenant administrator to be removed."""
    membership = await session.scalar(
        select(OrganizationMembership).where(
            OrganizationMembership.id == membership_id,
            OrganizationMembership.organization_id == organization.id,
        )
    )
    if membership is None:
        raise HTTPException(status_code=404, detail="Membership not found")
    role = await session.scalar(
        select(Role).where(Role.code == role_code, Role.scope == organization.kind)
    )
    if role is None:
        raise HTTPException(status_code=404, detail="Role not found")
    grant = await session.scalar(
        select(MembershipRole).where(
            MembershipRole.membership_id == membership.id,
            MembershipRole.role_id == role.id,
        )
    )
    if grant is None:
        raise HTTPException(status_code=404, detail="Role grant not found")
    if await _membership_has_invite_permission(session, membership.id):
        admin_count = await _active_invitation_admin_count(session, organization.id)
        if membership.status == "active" and admin_count <= 1:
            raise HTTPException(
                status_code=409,
                detail="Cannot remove the last active organization administrator",
            )
    await session.delete(grant)
    await session.commit()


@router.patch("/{membership_id}", status_code=204)
async def update_membership_status(
    membership_id: str,
    payload: MembershipStatusUpdate,
    organization: MembershipManager,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> None:
    """Suspend, reactivate or revoke a membership within the selected tenant."""
    if payload.status not in {"active", "suspended", "revoked"}:
        raise HTTPException(status_code=422, detail="Invalid membership status")
    membership = await session.scalar(
        select(OrganizationMembership).where(
            OrganizationMembership.id == membership_id,
            OrganizationMembership.organization_id == organization.id,
        )
    )
    if membership is None:
        raise HTTPException(status_code=404, detail="Membership not found")
    if (
        membership.status == "active"
        and payload.status != "active"
        and await _membership_has_invite_permission(session, membership.id)
        and await _active_invitation_admin_count(session, organization.id) <= 1
    ):
        raise HTTPException(
            status_code=409,
            detail="Cannot deactivate the last active organization administrator",
        )
    membership.status = payload.status
    await session.commit()
