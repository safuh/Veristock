"""Business enrollment and platform-side client organization administration."""

from datetime import UTC, datetime
from typing import Annotated
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from veristock.identity.authorization import (
    MembershipRole,
    Organization,
    OrganizationMembership,
    Role,
)
from veristock.identity.authorization_dependencies import (
    get_current_user,
    get_db_session,
    require_permission,
)
from veristock.identity.models import User
from veristock.organizations.models import OrganizationContact, OrganizationEnrollment

router = APIRouter(prefix="/organizations", tags=["organization-enrollment"])


class EnrollmentCreate(BaseModel):
    """Authenticated business owner's enrollment request."""

    legal_name: str = Field(min_length=2, max_length=240)
    trading_name: str | None = Field(default=None, max_length=240)
    business_registration_number: str | None = Field(default=None, max_length=100)
    timezone: str = Field(default="Africa/Nairobi", max_length=64)
    contact_name: str = Field(min_length=2, max_length=180)
    contact_email: str = Field(min_length=5, max_length=320)
    contact_phone: str | None = Field(default=None, max_length=40)
    business_description: str | None = Field(default=None, max_length=1000)

    @field_validator("contact_email")
    @classmethod
    def validate_contact_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized.count("@") != 1 or "." not in normalized.rsplit("@", 1)[-1]:
            raise ValueError("A valid contact email is required")
        return normalized

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("Unknown IANA timezone") from exc
        return value


class EnrollmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    requester_user_id: str
    legal_name: str
    trading_name: str | None
    business_registration_number: str | None
    timezone: str
    contact_name: str
    contact_email: str
    contact_phone: str | None
    business_description: str | None
    status: str
    review_note: str | None
    organization_id: str | None
    reviewed_by_user_id: str | None
    reviewed_at: datetime | None
    created_at: datetime


class EnrollmentReview(BaseModel):
    review_note: str | None = Field(default=None, max_length=1000)


class OrganizationStatusUpdate(BaseModel):
    status: str

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str) -> str:
        if value not in {"active", "suspended", "archived"}:
            raise ValueError("Status must be active, suspended or archived")
        return value


class ManagedOrganizationRead(BaseModel):
    id: str
    legal_name: str
    trading_name: str | None
    status: str
    timezone: str
    created_at: datetime
    active_members: int


PlatformOrganization = Annotated[
    Organization, Depends(require_permission("organization.manage"))
]


@router.post("/enrollments", response_model=EnrollmentRead, status_code=201)
async def submit_enrollment(
    payload: EnrollmentCreate,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> OrganizationEnrollment:
    """Submit an enrollment request; it does not grant client access."""
    contact_email = str(payload.contact_email).strip().lower()
    if contact_email != user.identifier.strip().lower():
        raise HTTPException(
            status_code=422,
            detail="Contact email must match the authenticated account",
        )

    existing = await session.scalar(
        select(OrganizationEnrollment.id).where(
            OrganizationEnrollment.requester_user_id == user.id,
            OrganizationEnrollment.status == "pending",
        )
    )
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail="You already have a pending business enrollment",
        )

    enrollment = OrganizationEnrollment(
        id=str(uuid4()),
        requester_user_id=user.id,
        legal_name=payload.legal_name.strip(),
        trading_name=payload.trading_name.strip() if payload.trading_name else None,
        business_registration_number=(
            payload.business_registration_number.strip()
            if payload.business_registration_number
            else None
        ),
        timezone=payload.timezone,
        contact_name=payload.contact_name.strip(),
        contact_email=contact_email,
        contact_phone=payload.contact_phone,
        business_description=payload.business_description,
        status="pending",
    )
    session.add(enrollment)
    await session.commit()
    await session.refresh(enrollment)
    return enrollment


@router.get("/enrollments", response_model=list[EnrollmentRead])
async def list_enrollments(
    platform: PlatformOrganization,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    status: str = Query(default="pending", pattern="^(pending|approved|rejected|all)$"),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[OrganizationEnrollment]:
    """List enrollment requests for platform operations staff."""
    if platform.kind != "platform":
        raise HTTPException(status_code=403, detail="Platform organization required")
    statement = select(OrganizationEnrollment)
    if status != "all":
        statement = statement.where(OrganizationEnrollment.status == status)
    result = await session.scalars(
        statement.order_by(OrganizationEnrollment.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result.all())


@router.post(
    "/enrollments/{enrollment_id}/approve",
    response_model=EnrollmentRead,
)
async def approve_enrollment(
    enrollment_id: str,
    payload: EnrollmentReview,
    platform: PlatformOrganization,
    actor: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> OrganizationEnrollment:
    """Provision a client tenant and its first administrator atomically."""
    if platform.kind != "platform":
        raise HTTPException(status_code=403, detail="Platform organization required")

    enrollment = await session.scalar(
        select(OrganizationEnrollment)
        .where(
            OrganizationEnrollment.id == enrollment_id,
            OrganizationEnrollment.status == "pending",
        )
        .with_for_update()
    )
    if enrollment is None:
        raise HTTPException(status_code=404, detail="Pending enrollment not found")

    requester = await session.get(User, enrollment.requester_user_id)
    client_admin_role = await session.scalar(
        select(Role).where(Role.code == "client_admin", Role.scope == "client")
    )
    if requester is None or requester.status != "active":
        raise HTTPException(status_code=409, detail="Applicant account is not active")
    if client_admin_role is None:
        raise HTTPException(status_code=500, detail="Client administrator role is not configured")

    organization = Organization(
        id=str(uuid4()),
        kind="client",
        legal_name=enrollment.legal_name,
        trading_name=enrollment.trading_name,
        timezone=enrollment.timezone,
        status="active",
    )
    membership = OrganizationMembership(
        id=str(uuid4()),
        organization_id=organization.id,
        user_id=requester.id,
        status="active",
    )
    contact = OrganizationContact(
        id=str(uuid4()),
        organization_id=organization.id,
        full_name=enrollment.contact_name,
        email=enrollment.contact_email,
        phone=enrollment.contact_phone,
        is_primary=True,
        status="active",
    )
    session.add_all(
        [
            organization,
            membership,
            contact,
            MembershipRole(
                id=str(uuid4()),
                membership_id=membership.id,
                role_id=client_admin_role.id,
            ),
        ]
    )
    enrollment.status = "approved"
    enrollment.organization_id = organization.id
    enrollment.reviewed_by_user_id = actor.id
    enrollment.reviewed_at = datetime.now(UTC)
    enrollment.review_note = payload.review_note
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=409,
            detail="Enrollment could not be provisioned; check for duplicate records",
        ) from exc
    await session.refresh(enrollment)
    return enrollment


@router.post(
    "/enrollments/{enrollment_id}/reject",
    response_model=EnrollmentRead,
)
async def reject_enrollment(
    enrollment_id: str,
    payload: EnrollmentReview,
    platform: PlatformOrganization,
    actor: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> OrganizationEnrollment:
    """Reject a pending enrollment without creating a client tenant."""
    if platform.kind != "platform":
        raise HTTPException(status_code=403, detail="Platform organization required")
    enrollment = await session.scalar(
        select(OrganizationEnrollment)
        .where(
            OrganizationEnrollment.id == enrollment_id,
            OrganizationEnrollment.status == "pending",
        )
        .with_for_update()
    )
    if enrollment is None:
        raise HTTPException(status_code=404, detail="Pending enrollment not found")
    enrollment.status = "rejected"
    enrollment.reviewed_by_user_id = actor.id
    enrollment.reviewed_at = datetime.now(UTC)
    enrollment.review_note = payload.review_note
    await session.commit()
    await session.refresh(enrollment)
    return enrollment


@router.get("", response_model=list[ManagedOrganizationRead])
async def list_client_organizations(
    platform: PlatformOrganization,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    status: str = Query(default="all", pattern="^(active|suspended|archived|all)$"),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[ManagedOrganizationRead]:
    """List client tenants and active membership counts for platform staff."""
    if platform.kind != "platform":
        raise HTTPException(status_code=403, detail="Platform organization required")
    statement = (
        select(
            Organization,
            func.count(OrganizationMembership.id).label(
                "active_members"
            ),
        )
        .outerjoin(
            OrganizationMembership,
            (OrganizationMembership.organization_id == Organization.id)
            & (OrganizationMembership.status == "active"),
        )
        .where(Organization.kind == "client")
        .group_by(Organization.id)
    )
    if status != "all":
        statement = statement.where(Organization.status == status)
    rows = (
        await session.execute(
            statement.order_by(Organization.created_at.desc()).limit(limit).offset(offset)
        )
    ).all()
    return [
        ManagedOrganizationRead(
            id=organization.id,
            legal_name=organization.legal_name,
            trading_name=organization.trading_name,
            status=organization.status,
            timezone=organization.timezone,
            created_at=organization.created_at,
            active_members=active_members,
        )
        for organization, active_members in rows
    ]


@router.patch("/{organization_id}/status", response_model=ManagedOrganizationRead)
async def update_client_organization_status(
    organization_id: str,
    payload: OrganizationStatusUpdate,
    platform: PlatformOrganization,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ManagedOrganizationRead:
    """Suspend, reactivate or archive a client tenant from platform operations."""
    if platform.kind != "platform":
        raise HTTPException(status_code=403, detail="Platform organization required")
    organization = await session.scalar(
        select(Organization).where(
            Organization.id == organization_id,
            Organization.kind == "client",
        )
    )
    if organization is None:
        raise HTTPException(status_code=404, detail="Client organization not found")
    organization.status = payload.status
    await session.commit()
    active_members = await session.scalar(
        select(func.count(OrganizationMembership.id)).where(
            OrganizationMembership.organization_id == organization.id,
            OrganizationMembership.status == "active",
        )
    )
    return ManagedOrganizationRead(
        id=organization.id,
        legal_name=organization.legal_name,
        trading_name=organization.trading_name,
        status=organization.status,
        timezone=organization.timezone,
        created_at=organization.created_at,
        active_members=int(active_members or 0),
    )
