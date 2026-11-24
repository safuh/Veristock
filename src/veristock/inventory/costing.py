"""Deterministic FIFO cost allocation for outbound stock movements."""

from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from veristock.inventory.models import StockMovement
from veristock.inventory.procurement import InventoryCostAllocation, InventoryCostLayer


async def allocate_fifo_cost(session: AsyncSession, movement: StockMovement) -> Decimal:
    """Allocate available FIFO receipt cost and return the quantity left uncosted.

    The caller owns the surrounding stock transaction. Unknown-cost quantities are
    intentionally left unallocated rather than assigned an estimated or fabricated cost.
    """
    if movement.quantity_delta >= 0:
        return Decimal("0")
    await session.flush()
    required = abs(movement.quantity_delta)
    filters = [
        InventoryCostLayer.organization_id == movement.organization_id,
        InventoryCostLayer.branch_id == movement.branch_id,
        InventoryCostLayer.item_id == movement.item_id,
        InventoryCostLayer.unit_code == movement.unit_code,
        InventoryCostLayer.remaining_quantity > 0,
    ]
    if movement.batch_id is None:
        filters.append(InventoryCostLayer.batch_id.is_(None))
    else:
        filters.append(InventoryCostLayer.batch_id == movement.batch_id)

    layers = list(
        (
            await session.scalars(
                select(InventoryCostLayer)
                .where(*filters)
                .order_by(InventoryCostLayer.received_at, InventoryCostLayer.id)
                .with_for_update()
            )
        ).all()
    )
    for layer in layers:
        if required <= 0:
            break
        quantity = min(required, layer.remaining_quantity)
        extended = (quantity * layer.unit_cost).quantize(Decimal("0.0001"))
        layer.remaining_quantity -= quantity
        session.add(
            InventoryCostAllocation(
                id=str(uuid4()),
                organization_id=movement.organization_id,
                stock_movement_id=movement.id,
                cost_layer_id=layer.id,
                quantity=quantity,
                unit_cost=layer.unit_cost,
                extended_cost=extended,
                currency=layer.currency,
            )
        )
        required -= quantity
    await session.flush()
    return required
