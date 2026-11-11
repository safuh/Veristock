"""Invitation creation, revocation and acceptance endpoints."""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from veristock.auth import PasswordHasher
from veristock.core.database import Base
from veristock.identity.authorization import (
    MembershipRole,
    Organization,
    OrganizationMembership,
    Role,
)
from veristock.identity.authorization_dependencies import (
    get_current_organization,
    get_current_user,
    get_db_session,
    require_permission,
)
from veristock.identity.models import User
from veristock.invitations.models import OrganizationInvitation

router = APIRouter(prefix="/invitations", tags=["invitations"])
InvitationManager = Annotated[
    Organization, Depends(require_permission("employee.invite"))
]


class InvitationCreate(BaseModel):
    email: EmailStr
    role_code: str = Field(min_length=2, max_length=80)


class InvitationCreated(BaseModel):
    id: str
    email: str
    role_code: str
    expires_at: datetime
    invitation_token: str


class InvitationAccept(BaseModel):
    token: str = Field(min_length=32, max_length=256)
    password: str = Field(min_length=12, max_length=256)


class InvitationAccepted(BaseModel):
    subject: str
    organization_id: str
    membership_id: str
    role_code: str


def _token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@router.post("", response_model=InvitationCreated, status_code=201)
async def create_invitation(
    payload: InvitationCreate,
    organization: InvitationManager,
    inviter: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> InvitationCreated:
    """Create a 72-hour single-use invite; return its secret once for delivery."""
    email = str(payload.email).strip().lower()
    role = await session.scalar(select(Role).where(
        Role.code == payload.role_code,
        Role.scope == organization.kind,
    ))
    if role is None:
        raise HTTPException(status_code=422, detail="Role is not valid for this organization")
    user = await session.scalar(select(User).where(func.lower(User.identifier) == email))
    if user is not None:
        membership = await session.scalar(select(OrganizationMembership).where(
            OrganizationMembership.organization_id == organization.id,
            OrganizationMembership.user_id == user.id,
        ))
        if membership is not None and membership.status == "active":
            raise HTTPException(status_code=409, detail="User is already an active member")

    now = datetime.now(UTC)
    pending = await session.scalars(select(OrganizationInvitation).where(
        OrganizationInvitation.organization_id == organization.id,
        OrganizationInvitation.email == email,
        OrganizationInvitation.accepted_at.is_(None),
        OrganizationInvitation.revoked_at.is_(None),
    ))
    for old_invitation in pending:
        old_invitation.revoked_at = now

    token = secrets.token_urlsafe(32)
    invitation = OrganizationInvitation(
        id=str(uuid4()),
        organization_id=organization.id,
        email=email,
        role_id=role.id,
        token_hash=_token_digest(token),
        invited_by_user_id=inviter.id,
        expires_at=now + timedelta(hours=72),
    )
    session.add(invitation)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Invitation could not be created") from exc
    await session.refresh(invitation)
    return InvitationCreated(
        id=invitation.id,
        email=email,
        role_code=role.code,
        expires_at=invitation.expires_at,
        invitation_token=token,
    )


@router.post("/{invitation_id}/revoke", status_code=204)
async def revoke_invitation(
    invitation_id: str,
    organization: InvitationManager,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> None:
    """Revoke a pending invitation belonging to the selected organization."""
    invitation = await session.scalar(select(OrganizationInvitation).where(
        OrganizationInvitation.id == invitation_id,
        OrganizationInvitation.organization_id == organization.id,
        OrganizationInvitation.accepted_at.is_(None),
        OrganizationInvitation.revoked_at.is_(None),
    ))
    if invitation is None:
        raise HTTPException(status_code=404, detail="Pending invitation not found")
    invitation.revoked_at = datetime.now(UTC)
    await session.commit()


@router.post("/accept", response_model=InvitationAccepted)
async def accept_invitation(
    payload: InvitationAccept,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> InvitationAccepted:
    """Redeem a valid invite and activate its organization membership."""
    invitation = await session.scalar(select(OrganizationInvitation).where(
        OrganizationInvitation.token_hash == _token_digest(payload.token)
    ))
    now = datetime.now(UTC)
    if (
        invitation is None
        or invitation.accepted_at is not None
        or invitation.revoked_at is not None
        or invitation.expires_at <= now
    ):
        raise HTTPException(status_code=400, detail="Invitation is invalid or expired")

    organization = await session.get(Organization, invitation.organization_id)
    role = await session.get(Role, invitation.role_id)
    if organization is None or organization.status != "active" or role is None:
        raise HTTPException(status_code=400, detail="Invitation is no longer valid")

    user = await session.scalar(select(User).where(
        func.lower(User.identifier) == invitation.email
    ))
    if user is None:
        user = User(
            id=str(uuid4()),
            identifier=invitation.email,
            password_hash=PasswordHasher().hash(payload.password),
            status="active",
        )
        session.add(user)
        await session.flush()
    elif user.status != "active":
        raise HTTPException(status_code=403, detail="User account is inactive")

    membership = await session.scalar(select(OrganizationMembership).where(
        OrganizationMembership.organization_id == organization.id,
        OrganizationMembership.user_id == user.id,
    ))
    if membership is None:
        membership = OrganizationMembership(
            id=str(uuid4()),
            organization_id=organization.id,
            user_id=user.id,
            status="active",
        )
        session.add(membership)
        await session.flush()
    elif membership.status == "revoked":
        membership.status = "active"
    elif membership.status == "suspended":
        raise HTTPException(status_code=403, detail="Organization membership is suspended")
    else:
        membership.status = "active"

    existing_grant = await session.scalar(select(MembershipRole.id).where(
        MembershipRole.membership_id == membership.id,
        MembershipRole.role_id == role.id,
    ))
    if existing_grant is None:
        session.add(MembershipRole(
            id=str(uuid4()),
            membership_id=membership.id,
            role_id=role.id,
        ))

    invitation.accepted_at = now
    await session.commit()
    return InvitationAccepted(
        subject=user.id,
        organization_id=organization.id,
        membership_id=membership.id,
        role_code=role.code,
    )
