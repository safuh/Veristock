"""Tenant-scoped inventory catalogue and stock visibility endpoints."""

from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from veristock.identity.authorization import Organization
from veristock.identity.authorization_dependencies import (
    get_db_session,
    require_permission,
)
from veristock.inventory.models import InventoryItem, StockBalance
from veristock.organizations.models import Branch

router = APIRouter(prefix="/inventory", tags=["inventory"])
InventoryRead = Annotated[Organization, Depends(require_permission("inventory.read"))]


class InventoryItemRead(BaseModel):
    id: str
    sku: str | None
    barcode: str | None
    name: str
    description: str | None
    base_unit_code: str
    status: str


class StockBalanceRead(BaseModel):
    item_id: str
    sku: str | None
    item_name: str
    branch_id: str
    branch_code: str
    branch_name: str
    quantity_on_hand: Decimal
    unit_code: str


class InventorySummaryRead(BaseModel):
    item_count: int
    branch_count: int
    stocked_item_count: int
    total_units_on_hand: Decimal


@router.get("/summary", response_model=InventorySummaryRead)
async def inventory_summary(
    organization: InventoryRead,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> InventorySummaryRead:
    """Return high-level inventory totals for the selected tenant only."""
    item_count = await session.scalar(
        select(func.count(InventoryItem.id)).where(
            InventoryItem.organization_id == organization.id,
            InventoryItem.status == "active",
        )
    )
    branch_count = await session.scalar(
        select(func.count(Branch.id)).where(
            Branch.organization_id == organization.id,
            Branch.status == "active",
        )
    )
    balances = await session.execute(
        select(
            func.count(distinct(StockBalance.item_id)),
            func.coalesce(func.sum(StockBalance.quantity_on_hand), 0),
        ).where(StockBalance.organization_id == organization.id)
    )
    stocked_item_count, total_units = balances.one()
    return InventorySummaryRead(
        item_count=int(item_count or 0),
        branch_count=int(branch_count or 0),
        stocked_item_count=int(stocked_item_count or 0),
        total_units_on_hand=Decimal(total_units or 0),
    )


@router.get("/items", response_model=list[InventoryItemRead])
async def list_inventory_items(
    organization: InventoryRead,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    status: str = Query(default="active", pattern="^(active|inactive|all)$"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[InventoryItem]:
    """List catalogue items belonging to the selected tenant."""
    statement = select(InventoryItem).where(
        InventoryItem.organization_id == organization.id
    )
    if status != "all":
        statement = statement.where(InventoryItem.status == status)
    result = await session.scalars(
        statement.order_by(InventoryItem.name).limit(limit).offset(offset)
    )
    return list(result.all())


@router.get("/balances", response_model=list[StockBalanceRead])
async def list_stock_balances(
    organization: InventoryRead,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    branch_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[StockBalanceRead]:
    """List current item balances with branch labels, scoped to the active tenant."""
    statement = (
        select(StockBalance, InventoryItem, Branch)
        .join(
            InventoryItem,
            (InventoryItem.id == StockBalance.item_id)
            & (InventoryItem.organization_id == organization.id),
        )
        .join(
            Branch,
            (Branch.id == StockBalance.branch_id)
            & (Branch.organization_id == organization.id),
        )
        .where(StockBalance.organization_id == organization.id)
    )
    if branch_id is not None:
        statement = statement.where(StockBalance.branch_id == branch_id)
    rows = (
        await session.execute(
            statement.order_by(Branch.code, InventoryItem.name)
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return [
        StockBalanceRead(
            item_id=item.id,
            sku=item.sku,
            item_name=item.name,
            branch_id=branch.id,
            branch_code=branch.code,
            branch_name=branch.name,
            quantity_on_hand=balance.quantity_on_hand,
            unit_code=item.base_unit_code,
        )
        for balance, item, branch in rows
    ]
