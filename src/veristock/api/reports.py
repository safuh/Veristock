"""Tenant-scoped deterministic inventory reporting endpoints."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy import and_, case, distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from veristock.identity.authorization import Organization
from veristock.identity.authorization_dependencies import (
    get_db_session,
    require_permission,
)
from veristock.inventory.models import InventoryItem, StockBalance
from veristock.organizations.models import Branch

router = APIRouter(prefix="/reports", tags=["reports"])
InventoryReporter = Annotated[
    Organization, Depends(require_permission("inventory.read"))
]


class InventoryReportMetric(BaseModel):
    """A deterministic report value suitable for display or later AI narration."""

    key: str
    label: str
    value: Decimal
    unit: str | None = None
    source_reference: str


class BranchInventoryReport(BaseModel):
    """Stock position for one active branch in the selected organization."""

    branch_id: str
    branch_code: str
    branch_name: str
    stocked_item_count: int
    total_units_on_hand: Decimal


class InventoryReportRead(BaseModel):
    """Tenant-scoped inventory snapshot with traceable source metrics."""

    model_config = ConfigDict(frozen=True)

    organization_id: str
    as_of: datetime
    active_item_count: int
    active_branch_count: int
    stocked_item_count: int
    zero_stock_item_count: int
    total_units_on_hand: Decimal
    branches: tuple[BranchInventoryReport, ...]
    metrics: tuple[InventoryReportMetric, ...]


@router.get("/inventory/summary", response_model=InventoryReportRead)
async def inventory_report(
    organization: InventoryReporter,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> InventoryReportRead:
    """Return an auditable stock snapshot for the selected tenant only."""
    active_item_count = int(
        await session.scalar(
            select(func.count(InventoryItem.id)).where(
                InventoryItem.organization_id == organization.id,
                InventoryItem.status == "active",
            )
        )
        or 0
    )
    active_branch_count = int(
        await session.scalar(
            select(func.count(Branch.id)).where(
                Branch.organization_id == organization.id,
                Branch.status == "active",
            )
        )
        or 0
    )

    stocked_item_count, total_units = (
        await session.execute(
            select(
                func.count(distinct(StockBalance.item_id)),
                func.coalesce(func.sum(StockBalance.quantity_on_hand), 0),
            )
            .join(
                InventoryItem,
                (InventoryItem.id == StockBalance.item_id)
                & (InventoryItem.organization_id == organization.id)
                & (InventoryItem.status == "active"),
            )
            .where(
                StockBalance.organization_id == organization.id,
                StockBalance.quantity_on_hand > 0,
            )
        )
    ).one()
    stocked_item_count = int(stocked_item_count or 0)
    total_units = Decimal(total_units or 0)

    active_stock_item = and_(
        InventoryItem.id.is_not(None),
        StockBalance.quantity_on_hand > 0,
    )
    branch_rows = (
        await session.execute(
            select(
                Branch.id,
                Branch.code,
                Branch.name,
                func.count(
                    distinct(
                        case(
                            (active_stock_item, StockBalance.item_id),
                            else_=None,
                        )
                    )
                ),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                InventoryItem.id.is_not(None),
                                StockBalance.quantity_on_hand,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ),
            )
            .outerjoin(
                StockBalance,
                (StockBalance.branch_id == Branch.id)
                & (StockBalance.organization_id == organization.id),
            )
            .outerjoin(
                InventoryItem,
                (InventoryItem.id == StockBalance.item_id)
                & (InventoryItem.organization_id == organization.id)
                & (InventoryItem.status == "active"),
            )
            .where(
                Branch.organization_id == organization.id,
                Branch.status == "active",
            )
            .group_by(Branch.id, Branch.code, Branch.name)
            .order_by(Branch.code)
        )
    ).all()

    branches = tuple(
        BranchInventoryReport(
            branch_id=branch_id,
            branch_code=branch_code,
            branch_name=branch_name,
            stocked_item_count=int(branch_stocked_count or 0),
            total_units_on_hand=Decimal(branch_total or 0),
        )
        for (
            branch_id,
            branch_code,
            branch_name,
            branch_stocked_count,
            branch_total,
        ) in branch_rows
    )
    zero_stock_item_count = max(active_item_count - stocked_item_count, 0)
    metrics = (
        InventoryReportMetric(
            key="inventory.active_items",
            label="Active catalogue items",
            value=Decimal(active_item_count),
            unit="items",
            source_reference="inventory:summary:active-items",
        ),
        InventoryReportMetric(
            key="inventory.active_branches",
            label="Active branches",
            value=Decimal(active_branch_count),
            unit="branches",
            source_reference="inventory:summary:active-branches",
        ),
        InventoryReportMetric(
            key="inventory.stocked_items",
            label="Items with stock",
            value=Decimal(stocked_item_count),
            unit="items",
            source_reference="inventory:summary:stocked-items",
        ),
        InventoryReportMetric(
            key="inventory.zero_stock_items",
            label="Active items with no stock in any branch",
            value=Decimal(zero_stock_item_count),
            unit="items",
            source_reference="inventory:summary:zero-stock-items",
        ),
        InventoryReportMetric(
            key="inventory.total_units",
            label="Total units on hand across branches",
            value=total_units,
            unit="base units",
            source_reference="inventory:summary:total-units",
        ),
    )
    return InventoryReportRead(
        organization_id=organization.id,
        as_of=datetime.now(UTC),
        active_item_count=active_item_count,
        active_branch_count=active_branch_count,
        stocked_item_count=stocked_item_count,
        zero_stock_item_count=zero_stock_item_count,
        total_units_on_hand=total_units,
        branches=branches,
        metrics=metrics,
    )
