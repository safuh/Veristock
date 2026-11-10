# ruff: noqa: E501
"""Tenant-scoped organization, branch and contact endpoints."""
from typing import Annotated
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from veristock.identity.authorization import Organization
from veristock.identity.authorization_dependencies import (
    get_current_organization,
    get_db_session,
    require_permission,
)
from veristock.organizations.models import Branch, OrganizationContact

router = APIRouter(tags=["organizations"])



class OrganizationCreate(BaseModel):
    legal_name: str = Field(min_length=2, max_length=240)
    trading_name: str | None = Field(default=None, max_length=240)
    timezone: str = Field(default="Africa/Nairobi", max_length=64)
    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("Unknown IANA timezone") from exc
        return value



class OrganizationRead(BaseModel):
    id: str
    kind: str
    legal_name: str
    trading_name: str | None
    timezone: str
    status: str



class OrganizationUpdate(BaseModel):
    legal_name: str | None = Field(default=None, min_length=2, max_length=240)
    trading_name: str | None = Field(default=None, max_length=240)
    timezone: str | None = Field(default=None, max_length=64)

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str | None) -> str | None:
        if value is not None:
            try:
                ZoneInfo(value)
            except ZoneInfoNotFoundError as exc:
                raise ValueError("Unknown IANA timezone") from exc
        return value




class BranchCreate(BaseModel):
    code: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=2, max_length=180)
    address_line_1: str | None = Field(default=None, max_length=240)
    address_line_2: str | None = Field(default=None, max_length=240)
    town: str | None = Field(default=None, max_length=120)
    county: str | None = Field(default=None, max_length=120)
    postal_code: str | None = Field(default=None, max_length=24)
    phone: str | None = Field(default=None, max_length=40)
    @field_validator("code")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        return value.strip().upper()



class BranchUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=180)
    address_line_1: str | None = Field(default=None, max_length=240)
    address_line_2: str | None = Field(default=None, max_length=240)
    town: str | None = Field(default=None, max_length=120)
    county: str | None = Field(default=None, max_length=120)
    postal_code: str | None = Field(default=None, max_length=24)
    phone: str | None = Field(default=None, max_length=40)
    status: str | None = None



class BranchRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    organization_id: str
    code: str
    name: str
    address_line_1: str | None
    address_line_2: str | None
    town: str | None
    county: str | None
    postal_code: str | None
    phone: str | None
    status: str



class ContactCreate(BaseModel):
    full_name: str = Field(min_length=2, max_length=180)
    title: str | None = Field(default=None, max_length=120)
    email: str | None = Field(default=None, max_length=320)
    phone: str | None = Field(default=None, max_length=40)
    is_primary: bool = False
    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str | None) -> str | None:
        if value and ("@" not in value or value.startswith("@") or value.endswith("@")):
            raise ValueError("A valid email address is required")
        return value



class ContactUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=180)
    title: str | None = Field(default=None, max_length=120)
    email: str | None = Field(default=None, max_length=320)
    phone: str | None = Field(default=None, max_length=40)
    is_primary: bool | None = None
    status: str | None = None



class ContactRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    organization_id: str
    full_name: str
    title: str | None
    email: str | None
    phone: str | None
    is_primary: bool
    status: str

PlatformOrganization = Annotated[Organization, Depends(require_permission("organization.manage"))]
TenantOrganization = Annotated[Organization, Depends(require_permission("organization.read"))]
BranchManager = Annotated[Organization, Depends(require_permission("branch.manage"))]



@router.post("/organizations", response_model=OrganizationRead, status_code=201)
async def create_client_organization(payload: OrganizationCreate, platform: PlatformOrganization, session: Annotated[AsyncSession, Depends(get_db_session)]) -> OrganizationRead:
    """Provision a client tenant from an authorized platform context."""
    if platform.kind != "platform":
        raise HTTPException(status_code=403, detail="Platform organization required")
    organization = Organization(id=str(uuid4()), kind="client", legal_name=payload.legal_name.strip(), trading_name=payload.trading_name, timezone=payload.timezone, status="active")
    session.add(organization)
    await session.commit()
    await session.refresh(organization)
    return OrganizationRead.model_validate(organization, from_attributes=True)



@router.get("/organizations/current", response_model=OrganizationRead)
async def read_current_organization(organization: TenantOrganization) -> OrganizationRead:
    return OrganizationRead.model_validate(organization, from_attributes=True)



@router.patch("/organizations/current", response_model=OrganizationRead)
async def update_current_organization(
    payload: OrganizationUpdate,
    organization: PlatformOrganization,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> OrganizationRead:
    """Update the selected tenant profile without allowing kind/status mutation."""
    changes = payload.model_dump(exclude_unset=True)
    if any(changes.get(field) is None for field in ("legal_name", "timezone") if field in changes):
        raise HTTPException(status_code=422, detail="Required organization fields cannot be null")
    for field, value in changes.items():
        setattr(organization, field, value)
    await session.commit()
    await session.refresh(organization)
    return OrganizationRead.model_validate(organization, from_attributes=True)




@router.get("/branches", response_model=list[BranchRead])
async def list_branches(organization: Annotated[Organization, Depends(get_current_organization)], _: Annotated[Organization, Depends(require_permission("branch.read"))], session: Annotated[AsyncSession, Depends(get_db_session)]) -> list[Branch]:
    result = await session.scalars(select(Branch).where(Branch.organization_id == organization.id).order_by(Branch.code))
    return list(result.all())



@router.post("/branches", response_model=BranchRead, status_code=201)
async def create_branch(payload: BranchCreate, organization: BranchManager, session: Annotated[AsyncSession, Depends(get_db_session)]) -> Branch:
    branch = Branch(id=str(uuid4()), organization_id=organization.id, **payload.model_dump())
    session.add(branch)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Branch code already exists") from exc
    await session.refresh(branch)
    return branch



@router.patch("/branches/{branch_id}", response_model=BranchRead)
async def update_branch(branch_id: str, payload: BranchUpdate, organization: BranchManager, session: Annotated[AsyncSession, Depends(get_db_session)]) -> Branch:
    branch = await session.scalar(select(Branch).where(Branch.id == branch_id, Branch.organization_id == organization.id))
    if branch is None:
        raise HTTPException(status_code=404, detail="Branch not found")
    changes = payload.model_dump(exclude_unset=True)
    if "name" in changes and changes["name"] is None:
        raise HTTPException(status_code=422, detail="Branch name cannot be null")
    if changes.get("status") not in (None, "active", "inactive"):
        raise HTTPException(status_code=422, detail="Invalid branch status")
    for field, value in changes.items():
        setattr(branch, field, value)
    await session.commit()
    await session.refresh(branch)
    return branch



@router.get("/contacts", response_model=list[ContactRead])
async def list_contacts(organization: Annotated[Organization, Depends(get_current_organization)], _: TenantOrganization, session: Annotated[AsyncSession, Depends(get_db_session)]) -> list[OrganizationContact]:
    result = await session.scalars(select(OrganizationContact).where(OrganizationContact.organization_id == organization.id).order_by(OrganizationContact.is_primary.desc(), OrganizationContact.full_name))
    return list(result.all())



@router.post("/contacts", response_model=ContactRead, status_code=201)
async def create_contact(payload: ContactCreate, organization: PlatformOrganization, session: Annotated[AsyncSession, Depends(get_db_session)]) -> OrganizationContact:
    contact = OrganizationContact(id=str(uuid4()), organization_id=organization.id, **payload.model_dump())
    session.add(contact)
    await session.commit()
    await session.refresh(contact)
    return contact



@router.patch("/contacts/{contact_id}", response_model=ContactRead)
async def update_contact(contact_id: str, payload: ContactUpdate, organization: PlatformOrganization, session: Annotated[AsyncSession, Depends(get_db_session)]) -> OrganizationContact:
    contact = await session.scalar(select(OrganizationContact).where(OrganizationContact.id == contact_id, OrganizationContact.organization_id == organization.id))
    if contact is None:
        raise HTTPException(status_code=404, detail="Contact not found")
    changes = payload.model_dump(exclude_unset=True)
    if "full_name" in changes and changes["full_name"] is None:
        raise HTTPException(status_code=422, detail="Contact name cannot be null")
    if changes.get("status") not in (None, "active", "inactive"):
        raise HTTPException(status_code=422, detail="Invalid contact status")
    for field, value in changes.items():
        setattr(contact, field, value)
    await session.commit()
    await session.refresh(contact)
    return contact
