# ruff: noqa: E501
"""Veristock internal workforce profile endpoints."""
from datetime import date
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from veristock.identity.authorization import Organization, OrganizationMembership
from veristock.identity.authorization_dependencies import get_db_session, require_permission
from veristock.identity.models import User
from veristock.workforce.models import EmployeeProfile

router = APIRouter(prefix="/employees", tags=["workforce"])
PlatformEmployeeReader = Annotated[Organization, Depends(require_permission("employee.read"))]
PlatformEmployeeManager = Annotated[Organization, Depends(require_permission("employee.manage"))]

class EmployeeCreate(BaseModel):
    user_id: str
    employee_number: str = Field(min_length=1, max_length=40)
    display_name: str = Field(min_length=2, max_length=180)
    phone: str | None = Field(default=None, max_length=40)
    job_title: str | None = Field(default=None, max_length=120)
    hire_date: date | None = None

class EmployeeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    organization_id: str
    user_id: str
    employee_number: str
    display_name: str
    phone: str | None
    job_title: str | None
    hire_date: date | None
    employment_status: str

@router.get("", response_model=list[EmployeeRead])
async def list_employees(organization: PlatformEmployeeReader, session: Annotated[AsyncSession, Depends(get_db_session)]) -> list[EmployeeProfile]:
    if organization.kind != "platform":
        raise HTTPException(status_code=403, detail="Platform organization required")
    result = await session.scalars(select(EmployeeProfile).where(EmployeeProfile.organization_id == organization.id).order_by(EmployeeProfile.employee_number))
    return list(result.all())

class EmployeeUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=2, max_length=180)
    phone: str | None = Field(default=None, max_length=40)
    job_title: str | None = Field(default=None, max_length=120)
    employment_status: str | None = None


@router.patch("/{employee_id}", response_model=EmployeeRead)
async def update_employee(
    employee_id: str,
    payload: EmployeeUpdate,
    organization: PlatformEmployeeManager,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> EmployeeProfile:
    if organization.kind != "platform":
        raise HTTPException(status_code=403, detail="Platform organization required")
    employee = await session.scalar(select(EmployeeProfile).where(
        EmployeeProfile.id == employee_id,
        EmployeeProfile.organization_id == organization.id,
    ))
    if employee is None:
        raise HTTPException(status_code=404, detail="Employee profile not found")
    changes = payload.model_dump(exclude_unset=True)
    if "display_name" in changes and changes["display_name"] is None:
        raise HTTPException(status_code=422, detail="Employee name cannot be null")
    if changes.get("employment_status") not in (None, "active", "suspended", "terminated"):
        raise HTTPException(status_code=422, detail="Invalid employment status")
    for field, value in changes.items():
        setattr(employee, field, value)
    await session.commit()
    await session.refresh(employee)
    return employee


@router.post("", response_model=EmployeeRead, status_code=201)
async def create_employee(payload: EmployeeCreate, organization: PlatformEmployeeManager, session: Annotated[AsyncSession, Depends(get_db_session)]) -> EmployeeProfile:
    if organization.kind != "platform":
        raise HTTPException(status_code=403, detail="Platform organization required")
    user = await session.get(User, payload.user_id)
    membership = await session.scalar(select(OrganizationMembership.id).where(OrganizationMembership.user_id == payload.user_id, OrganizationMembership.organization_id == organization.id, OrganizationMembership.status == "active"))
    if user is None or user.status != "active" or membership is None:
        raise HTTPException(status_code=422, detail="Employee must be an active platform member")
    employee = EmployeeProfile(id=str(uuid4()), organization_id=organization.id, employment_status="active", **payload.model_dump())
    session.add(employee)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Employee profile already exists") from exc
    await session.refresh(employee)
    return employee
