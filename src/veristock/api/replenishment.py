"""Tenant-scoped replenishment policy management."""

from datetime import datetime
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from veristock.identity.authorization import Organization
from veristock.identity.authorization_dependencies import (
    get_current_user,
    get_db_session,
    require_permission,
)
from veristock.identity.models import User
from veristock.inventory.models import InventoryItem
from veristock.inventory.policies import ReplenishmentPolicy
from veristock.organizations.models import Branch

router = APIRouter(prefix="/inventory/replenishment-policies", tags=["inventory"])
PolicyReader = Annotated[
    Organization, Depends(require_permission("inventory.read"))
]
PolicyManager = Annotated[
    Organization, Depends(require_permission("inventory.manage"))
]


class ReplenishmentPolicyWrite(BaseModel):
    """Validated lead-time and safety-stock planning inputs."""

    model_config = ConfigDict(extra="forbid")

    lead_time_days: int = Field(default=0, ge=0, le=180)
    safety_stock_days: int = Field(default=0, ge=0, le=180)


class ReplenishmentPolicyRead(BaseModel):
    """Persisted branch/item policy with update provenance."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    branch_id: str
    item_id: str
    lead_time_days: int
    safety_stock_days: int
    updated_by_user_id: str
    updated_at: datetime


@router.get("", response_model=list[ReplenishmentPolicyRead])
async def list_replenishment_policies(
    organization: PolicyReader,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    branch_id: str | None = None,
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[ReplenishmentPolicy]:
    """List policies for the active tenant, optionally narrowed to one branch."""
    statement = select(ReplenishmentPolicy).where(
        ReplenishmentPolicy.organization_id == organization.id
    )
    if branch_id is not None:
        statement = statement.where(ReplenishmentPolicy.branch_id == branch_id)
    result = await session.scalars(
        statement.order_by(
            ReplenishmentPolicy.branch_id,
            ReplenishmentPolicy.item_id,
        )
        .limit(limit)
        .offset(offset)
    )
    return list(result.all())


@router.put(
    "/{branch_id}/{item_id}",
    response_model=ReplenishmentPolicyRead,
    status_code=status.HTTP_200_OK,
)
async def upsert_replenishment_policy(
    branch_id: str,
    item_id: str,
    payload: ReplenishmentPolicyWrite,
    organization: PolicyManager,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ReplenishmentPolicy:
    """Create or replace one policy after validating both resources' tenant."""
    scope = await session.execute(
        select(Branch.id, InventoryItem.id)
        .join(
            InventoryItem,
            InventoryItem.organization_id == Branch.organization_id,
        )
        .where(
            Branch.id == branch_id,
            Branch.organization_id == organization.id,
            Branch.status == "active",
            InventoryItem.id == item_id,
            InventoryItem.organization_id == organization.id,
            InventoryItem.status == "active",
        )
    )
    if scope.one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Active branch or item not found in this organization",
        )

    policy = await session.scalar(
        select(ReplenishmentPolicy).where(
            ReplenishmentPolicy.organization_id == organization.id,
            ReplenishmentPolicy.branch_id == branch_id,
            ReplenishmentPolicy.item_id == item_id,
        )
    )
    if policy is None:
        policy = ReplenishmentPolicy(
            id=str(uuid4()),
            organization_id=organization.id,
            branch_id=branch_id,
            item_id=item_id,
            updated_by_user_id=user.id,
            **payload.model_dump(),
        )
        session.add(policy)
    else:
        policy.lead_time_days = payload.lead_time_days
        policy.safety_stock_days = payload.safety_stock_days
        policy.updated_by_user_id = user.id

    await session.commit()
    await session.refresh(policy)
    return policy
