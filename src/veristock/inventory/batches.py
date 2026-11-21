"""Batch allocation primitives with deterministic FEFO ordering."""

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from veristock.inventory.models import BatchStockBalance, InventoryBatch


async def allocate_fefo(
    session: AsyncSession,
    *,
    organization_id: str,
    branch_id: str,
    item_id: str,
    quantity: Decimal,
    on_date: date,
) -> list[tuple[BatchStockBalance, Decimal]]:
    """Lock eligible batch balances and allocate earliest-expiry stock first."""
    rows = list(
        (
            await session.scalars(
                select(BatchStockBalance)
                .join(InventoryBatch, InventoryBatch.id == BatchStockBalance.batch_id)
                .where(
                    BatchStockBalance.organization_id == organization_id,
                    BatchStockBalance.branch_id == branch_id,
                    BatchStockBalance.item_id == item_id,
                    BatchStockBalance.quantity_on_hand > 0,
                    InventoryBatch.status == "active",
                    (InventoryBatch.expiry_date.is_(None))
                    | (InventoryBatch.expiry_date >= on_date),
                )
                .order_by(
                    InventoryBatch.expiry_date.is_(None),
                    InventoryBatch.expiry_date,
                    InventoryBatch.received_at,
                    InventoryBatch.id,
                )
                .with_for_update()
            )
        ).all()
    )
    remaining = quantity
    allocations: list[tuple[BatchStockBalance, Decimal]] = []
    for balance in rows:
        take = min(balance.quantity_on_hand, remaining)
        if take > 0:
            allocations.append((balance, take))
            remaining -= take
        if remaining == 0:
            return allocations
    raise ValueError("Insufficient unexpired batch stock")
