"""Purchase-order issue and partial goods-receipt workflows."""

from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from veristock.api.branch_access import require_branch_assignment
from veristock.identity.authorization import Organization
from veristock.identity.authorization_dependencies import (
    get_current_user,
    get_db_session,
    require_permission,
)
from veristock.identity.models import User
from veristock.inventory.models import (
    BatchStockBalance,
    InventoryBatch,
    InventoryItem,
    Sale,
    SaleLine,
    StockBalance,
    StockMovement,
    Supplier,
)
from veristock.inventory.procurement import (
    GoodsReceipt,
    GoodsReceiptLine,
    InventoryCostAllocation,
    InventoryCostLayer,
    InventoryCostRestoration,
    InventoryValuationSnapshot,
    PurchaseOrder,
    PurchaseOrderLine,
)
from veristock.organizations.models import Branch

router = APIRouter(prefix="/procurement", tags=["procurement"])
Manager = Annotated[Organization, Depends(require_permission("inventory.manage"))]
Reader = Annotated[Organization, Depends(require_permission("inventory.read"))]


class PurchaseLineInput(BaseModel):
    item_id: str
    quantity: Decimal = Field(gt=0, max_digits=18, decimal_places=4)
    unit_cost: Decimal = Field(ge=0, max_digits=18, decimal_places=4)


class PurchaseOrderInput(BaseModel):
    reference: str = Field(min_length=2, max_length=80)
    supplier_id: str
    branch_id: str
    currency: str = Field(default="KES", min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")
    idempotency_key: str = Field(min_length=8, max_length=128)
    notes: str | None = Field(default=None, max_length=1000)
    expected_delivery_date: date | None = None
    lines: list[PurchaseLineInput] = Field(min_length=1, max_length=200)


class ReceiptLineInput(BaseModel):
    purchase_order_line_id: str
    quantity: Decimal = Field(gt=0, max_digits=18, decimal_places=4)
    lot_code: str | None = Field(default=None, min_length=1, max_length=100)
    manufactured_date: date | None = None
    expiry_date: date | None = None


class GoodsReceiptInput(BaseModel):
    reference: str = Field(min_length=2, max_length=80)
    supplier_delivery_reference: str | None = Field(default=None, max_length=120)
    idempotency_key: str = Field(min_length=8, max_length=128)
    lines: list[ReceiptLineInput] = Field(min_length=1, max_length=200)


def _po_read(po: PurchaseOrder) -> dict[str, object]:
    return {
        "id": po.id,
        "reference": po.reference,
        "supplier_id": po.supplier_id,
        "branch_id": po.branch_id,
        "status": po.status,
        "currency": po.currency,
        "notes": po.notes,
        "created_at": po.created_at,
        "issued_at": po.issued_at,
        "expected_delivery_date": po.expected_delivery_date,
        "completed_at": po.completed_at,
        "delivery_status": (
            "not_scheduled"
            if po.expected_delivery_date is None
            else "pending"
            if po.completed_at is None
            else "on_time"
            if po.completed_at.date() <= po.expected_delivery_date
            else "late"
        ),
        "lines": [
            {
                "id": line.id,
                "item_id": line.item_id,
                "ordered_quantity": line.ordered_quantity,
                "received_quantity": line.received_quantity,
                "outstanding_quantity": line.ordered_quantity - line.received_quantity,
                "unit_code": line.unit_code,
                "unit_cost": line.unit_cost,
            }
            for line in po.lines
        ],
    }


@router.post("/purchase-orders", status_code=201)
async def create_purchase_order(
    payload: PurchaseOrderInput,
    organization: Manager,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict[str, object]:
    await require_branch_assignment(session, user, organization, payload.branch_id)
    prior = await session.scalar(
        select(PurchaseOrder)
        .where(
            PurchaseOrder.organization_id == organization.id,
            PurchaseOrder.idempotency_key == payload.idempotency_key,
        )
        .options(selectinload(PurchaseOrder.lines))
    )
    normalized = sorted((x.item_id, x.quantity, x.unit_cost) for x in payload.lines)
    if prior:
        existing = sorted((x.item_id, x.ordered_quantity, x.unit_cost) for x in prior.lines)
        if (
            prior.reference != payload.reference.strip()
            or prior.supplier_id != payload.supplier_id
            or prior.branch_id != payload.branch_id
            or prior.currency != payload.currency
            or prior.notes != payload.notes
            or prior.expected_delivery_date != payload.expected_delivery_date
            or existing != normalized
        ):
            raise HTTPException(
                status_code=409, detail="Idempotency key belongs to another purchase order"
            )
        return _po_read(prior)
    supplier = await session.scalar(
        select(Supplier).where(
            Supplier.id == payload.supplier_id,
            Supplier.organization_id == organization.id,
            Supplier.status == "active",
        )
    )
    branch = await session.scalar(
        select(Branch).where(
            Branch.id == payload.branch_id,
            Branch.organization_id == organization.id,
            Branch.status == "active",
        )
    )
    if supplier is None or branch is None:
        raise HTTPException(status_code=404, detail="Active supplier or branch not found")
    if supplier.default_currency != payload.currency:
        raise HTTPException(
            status_code=422, detail="Purchase order currency must match supplier default currency"
        )
    po = PurchaseOrder(
        id=str(uuid4()),
        organization_id=organization.id,
        supplier_id=supplier.id,
        branch_id=branch.id,
        reference=payload.reference.strip(),
        status="draft",
        currency=payload.currency,
        notes=payload.notes,
        expected_delivery_date=payload.expected_delivery_date,
        idempotency_key=payload.idempotency_key,
        created_by_user_id=user.id,
    )
    seen: set[str] = set()
    for line in payload.lines:
        if line.item_id in seen:
            raise HTTPException(status_code=422, detail="Duplicate item in purchase order")
        seen.add(line.item_id)
        item = await session.scalar(
            select(InventoryItem).where(
                InventoryItem.id == line.item_id,
                InventoryItem.organization_id == organization.id,
                InventoryItem.status == "active",
            )
        )
        if item is None:
            raise HTTPException(status_code=404, detail="Active inventory item not found")
        po.lines.append(
            PurchaseOrderLine(
                id=str(uuid4()),
                organization_id=organization.id,
                item_id=item.id,
                ordered_quantity=line.quantity,
                received_quantity=Decimal("0"),
                unit_code=item.base_unit_code,
                unit_cost=line.unit_cost,
            )
        )
    session.add(po)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=409, detail="Purchase order reference or idempotency key already exists"
        ) from exc
    await session.refresh(po, attribute_names=["lines"])
    return _po_read(po)


@router.get("/purchase-orders")
async def list_purchase_orders(
    organization: Reader,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    status: str | None = None,
) -> list[dict[str, object]]:
    query = (
        select(PurchaseOrder)
        .where(PurchaseOrder.organization_id == organization.id)
        .options(selectinload(PurchaseOrder.lines))
        .order_by(PurchaseOrder.created_at.desc())
    )
    if status:
        if status not in {"draft", "issued", "partially_received", "received", "cancelled"}:
            raise HTTPException(status_code=422, detail="Invalid purchase order status")
        query = query.where(PurchaseOrder.status == status)
    return [_po_read(x) for x in (await session.scalars(query)).all()]


@router.post("/purchase-orders/{purchase_order_id}/issue")
async def issue_purchase_order(
    purchase_order_id: str,
    organization: Manager,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict[str, object]:
    po = await session.scalar(
        select(PurchaseOrder)
        .where(
            PurchaseOrder.id == purchase_order_id, PurchaseOrder.organization_id == organization.id
        )
        .options(selectinload(PurchaseOrder.lines))
        .with_for_update()
    )
    if po is None:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    await require_branch_assignment(session, user, organization, po.branch_id)
    if po.status == "issued":
        return _po_read(po)
    if po.status != "draft":
        raise HTTPException(status_code=409, detail="Only draft purchase orders can be issued")
    po.status = "issued"
    po.issued_by_user_id = user.id
    po.issued_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(po, attribute_names=["lines"])
    return _po_read(po)


@router.get("/valuation/cost-layers")
async def list_inventory_cost_layers(
    organization: Reader,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    branch_id: str | None = None,
    item_id: str | None = None,
    limit: int = 100,
) -> dict[str, object]:
    """List known receipt cost bases, not a complete on-hand valuation."""
    statement = select(InventoryCostLayer).where(
        InventoryCostLayer.organization_id == organization.id
    )
    if branch_id is not None:
        await require_branch_assignment(session, user, organization, branch_id)
        statement = statement.where(InventoryCostLayer.branch_id == branch_id)
    if item_id is not None:
        statement = statement.where(InventoryCostLayer.item_id == item_id)
    statement = statement.order_by(InventoryCostLayer.received_at.desc()).limit(
        min(max(limit, 1), 500)
    )
    layers = list((await session.scalars(statement)).all())
    return {
        "items": [
            {
                "id": layer.id,
                "branch_id": layer.branch_id,
                "item_id": layer.item_id,
                "batch_id": layer.batch_id,
                "goods_receipt_line_id": layer.goods_receipt_line_id,
                "purchase_order_line_id": layer.purchase_order_line_id,
                "received_quantity": layer.received_quantity,
                "remaining_quantity": layer.remaining_quantity,
                "unit_code": layer.unit_code,
                "unit_cost": layer.unit_cost,
                "currency": layer.currency,
                "received_at": layer.received_at,
                "remaining_cost": layer.remaining_quantity * layer.unit_cost,
            }
            for layer in layers
        ],
        "count": len(layers),
        "valuation_status": "receipt_cost_layers_only",
    }


@router.get("/valuation/on-hand")
async def get_on_hand_inventory_valuation(
    organization: Reader,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    branch_id: str | None = None,
    item_id: str | None = None,
) -> dict[str, object]:
    """Report carrying cost by unit/currency and explicitly identify uncosted stock."""
    from sqlalchemy import func

    balance_statement = (
        select(
            StockBalance.branch_id,
            StockBalance.item_id,
            InventoryItem.name,
            InventoryItem.sku,
            StockBalance.quantity_on_hand,
            InventoryItem.base_unit_code,
        )
        .join(
            InventoryItem,
            (InventoryItem.id == StockBalance.item_id)
            & (InventoryItem.organization_id == StockBalance.organization_id),
        )
        .where(StockBalance.organization_id == organization.id)
    )
    if branch_id is not None:
        await require_branch_assignment(session, user, organization, branch_id)
        balance_statement = balance_statement.where(StockBalance.branch_id == branch_id)
    if item_id is not None:
        balance_statement = balance_statement.where(StockBalance.item_id == item_id)
    balances = (await session.execute(balance_statement)).all()

    layer_statement = select(
        InventoryCostLayer.branch_id,
        InventoryCostLayer.item_id,
        InventoryCostLayer.unit_code,
        InventoryCostLayer.currency,
        func.sum(InventoryCostLayer.remaining_quantity),
        func.sum(InventoryCostLayer.remaining_quantity * InventoryCostLayer.unit_cost),
    ).where(
        InventoryCostLayer.organization_id == organization.id,
        InventoryCostLayer.remaining_quantity > 0,
    )
    if branch_id is not None:
        layer_statement = layer_statement.where(InventoryCostLayer.branch_id == branch_id)
    if item_id is not None:
        layer_statement = layer_statement.where(InventoryCostLayer.item_id == item_id)
    layer_statement = layer_statement.group_by(
        InventoryCostLayer.branch_id,
        InventoryCostLayer.item_id,
        InventoryCostLayer.unit_code,
        InventoryCostLayer.currency,
    )
    layer_rows = (await session.execute(layer_statement)).all()
    layers_by_scope: dict[tuple[str, str], list[dict[str, object]]] = {}
    costed_by_scope: dict[tuple[str, str], Decimal] = {}
    for row_branch, row_item, unit, currency, quantity, value in layer_rows:
        key = (row_branch, row_item)
        quantity_value = Decimal(quantity or 0)
        layers_by_scope.setdefault(key, []).append(
            {
                "unit_code": unit,
                "currency": currency,
                "costed_quantity": quantity_value,
                "carrying_value": Decimal(value or 0),
            }
        )
        costed_by_scope[key] = costed_by_scope.get(key, Decimal("0")) + quantity_value

    items: list[dict[str, object]] = []
    has_uncosted_stock = False
    for row_branch, row_item, name, sku, raw_on_hand, unit in balances:
        on_hand = Decimal(raw_on_hand or 0)
        costed = costed_by_scope.get((row_branch, row_item), Decimal("0"))
        uncosted = max(on_hand - costed, Decimal("0"))
        has_uncosted_stock = has_uncosted_stock or uncosted > 0
        items.append(
            {
                "branch_id": row_branch,
                "item_id": row_item,
                "sku": sku,
                "name": name,
                "unit_code": unit,
                "quantity_on_hand": on_hand,
                "costed_quantity": costed,
                "uncosted_quantity": uncosted,
                "cost_layers": layers_by_scope.get((row_branch, row_item), []),
                "valuation_complete": uncosted == 0,
            }
        )
    return {
        "items": items,
        "count": len(items),
        "valuation_method": "fifo_receipt_cost_layers",
        "valuation_status": "partial" if has_uncosted_stock else "costed_stock_only",
        "currency_aggregation": "separate_currency_buckets_no_conversion",
    }


@router.get("/valuation/cogs")
async def get_sales_cogs(
    organization: Reader,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    branch_id: str | None = None,
    item_id: str | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    limit: int = Query(default=500, ge=1, le=2000),
) -> dict[str, object]:
    """Report posted-sale revenue and FIFO COGS without mixing currencies."""
    from sqlalchemy.orm import selectinload

    if from_date and to_date and from_date > to_date:
        raise HTTPException(status_code=422, detail="from_date must not follow to_date")
    sales_query = (
        select(Sale)
        .options(selectinload(Sale.lines))
        .where(
            Sale.organization_id == organization.id,
            Sale.status == "posted",
        )
    )
    if branch_id is not None:
        await require_branch_assignment(session, user, organization, branch_id)
        sales_query = sales_query.where(Sale.branch_id == branch_id)
    if item_id is not None:
        sales_query = sales_query.where(Sale.lines.any(SaleLine.item_id == item_id))
    if from_date is not None:
        sales_query = sales_query.where(
            Sale.posted_at >= datetime.combine(from_date, time.min, tzinfo=UTC)
        )
    if to_date is not None:
        sales_query = sales_query.where(
            Sale.posted_at < datetime.combine(to_date + timedelta(days=1), time.min, tzinfo=UTC)
        )
    sales = list(
        (await session.scalars(sales_query.order_by(Sale.posted_at.desc()).limit(limit))).all()
    )
    sale_ids = [sale.id for sale in sales]
    line_rows = [
        line for sale in sales for line in sale.lines if item_id is None or line.item_id == item_id
    ]
    allocations_by_sale_item: dict[tuple[str, str, str, str], tuple[Decimal, Decimal]] = {}
    if sale_ids and line_rows:
        allocation_rows = (
            await session.execute(
                select(
                    StockMovement.source_id,
                    StockMovement.item_id,
                    StockMovement.unit_code,
                    InventoryCostAllocation.quantity,
                    InventoryCostAllocation.extended_cost,
                    InventoryCostAllocation.currency,
                )
                .join(
                    InventoryCostAllocation,
                    InventoryCostAllocation.stock_movement_id == StockMovement.id,
                )
                .where(
                    StockMovement.organization_id == organization.id,
                    StockMovement.source_type == "sale",
                    StockMovement.source_id.in_(sale_ids),
                )
            )
        ).all()
        for (
            sale_id,
            movement_item_id,
            unit_code,
            quantity,
            extended_cost,
            currency,
        ) in allocation_rows:
            key = (sale_id, movement_item_id, unit_code, currency)
            prior_quantity, prior_cost = allocations_by_sale_item.get(key, (Decimal(0), Decimal(0)))
            allocations_by_sale_item[key] = (prior_quantity + quantity, prior_cost + extended_cost)

    buckets: dict[tuple[str, str, str, str], dict[str, Decimal | int]] = {}
    incomplete_lines: list[dict[str, object]] = []
    for sale in sales:
        for line in sale.lines:
            if item_id is not None and line.item_id != item_id:
                continue
            if line.unit_price is None or line.currency is None:
                incomplete_lines.append(
                    {
                        "sale_id": sale.id,
                        "sale_reference": sale.reference,
                        "item_id": line.item_id,
                        "reason": "selling_price_or_currency_missing",
                    }
                )
            else:
                key = (sale.branch_id, line.item_id, line.unit_code, line.currency)
                bucket = buckets.setdefault(
                    key,
                    {
                        "revenue": Decimal(0),
                        "cogs": Decimal(0),
                        "revenue_line_count": 0,
                        "costed_line_count": 0,
                        "costed_quantity": Decimal(0),
                        "incomplete_line_count": 0,
                    },
                )
                bucket["revenue"] += line.quantity * line.unit_price
                bucket["revenue_line_count"] += 1
            cost_by_currency = [
                (currency, quantity, amount)
                for (sid, iid, unit, currency), (
                    quantity,
                    amount,
                ) in allocations_by_sale_item.items()
                if sid == sale.id and iid == line.item_id and unit == line.unit_code
            ]
            costed_quantity = sum((quantity for _, quantity, _ in cost_by_currency), Decimal(0))
            for currency, allocated_quantity, amount in cost_by_currency:
                key = (sale.branch_id, line.item_id, line.unit_code, currency)
                bucket = buckets.setdefault(
                    key,
                    {
                        "revenue": Decimal(0),
                        "cogs": Decimal(0),
                        "revenue_line_count": 0,
                        "costed_line_count": 0,
                        "costed_quantity": Decimal(0),
                        "incomplete_line_count": 0,
                    },
                )
                bucket["cogs"] += amount
                bucket["costed_line_count"] += 1
                bucket["costed_quantity"] += allocated_quantity
                if allocated_quantity != line.quantity:
                    bucket["incomplete_line_count"] += 1
            if line.unit_price is not None and line.currency is not None:
                revenue_key = (sale.branch_id, line.item_id, line.unit_code, line.currency)
                matching_currency_quantity = sum(
                    (
                        quantity
                        for currency, quantity, _ in cost_by_currency
                        if currency == line.currency
                    ),
                    Decimal(0),
                )
                if matching_currency_quantity != line.quantity:
                    buckets[revenue_key]["incomplete_line_count"] += 1
            if costed_quantity < line.quantity:
                incomplete_lines.append(
                    {
                        "sale_id": sale.id,
                        "sale_reference": sale.reference,
                        "item_id": line.item_id,
                        "reason": "fifo_cost_allocation_missing_or_partial",
                        "quantity": line.quantity,
                        "costed_quantity": costed_quantity,
                    }
                )

    summaries = []
    for (row_branch, row_item, unit, currency), values in sorted(buckets.items()):
        revenue = Decimal(str(values["revenue"]))
        cogs = Decimal(str(values["cogs"]))
        summaries.append(
            {
                "branch_id": row_branch,
                "item_id": row_item,
                "unit_code": unit,
                "currency": currency,
                "revenue": revenue,
                "cogs": cogs,
                "gross_profit": revenue - cogs
                if values["revenue_line_count"] > 0
                and values["costed_line_count"] > 0
                and values["incomplete_line_count"] == 0
                else None,
                "gross_margin_percent": ((revenue - cogs) / revenue * Decimal(100))
                if revenue > 0
                and values["costed_line_count"] > 0
                and values["incomplete_line_count"] == 0
                else None,
                "revenue_line_count": values["revenue_line_count"],
                "costed_line_count": values["costed_line_count"],
                "costed_quantity": values["costed_quantity"],
                "incomplete_line_count": values["incomplete_line_count"],
                "profit_comparable": values["revenue_line_count"] > 0
                and values["costed_line_count"] > 0
                and values["incomplete_line_count"] == 0,
            }
        )
    return {
        "items": summaries,
        "count": len(summaries),
        "incomplete_lines": incomplete_lines,
        "incomplete_line_count": len(incomplete_lines),
        "currency_aggregation": "separate_currency_buckets_no_conversion",
        "valuation_method": "fifo_cost_allocations",
        "scope_note": (
            "Only posted sales are included. Reversed sales are excluded; rows with missing "
            "price or FIFO cost are flagged. Gross profit is only comparable when revenue "
            "and COGS share a currency bucket."
        ),
    }


class ValuationSnapshotInput(BaseModel):
    idempotency_key: str = Field(min_length=8, max_length=128)


@router.post("/valuation/snapshots", status_code=201)
async def create_valuation_snapshot(
    organization: Manager,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    payload: ValuationSnapshotInput,
) -> dict[str, object]:
    """Capture an immutable on-hand valuation snapshot; retries return the original."""
    existing = await session.scalar(
        select(InventoryValuationSnapshot).where(
            InventoryValuationSnapshot.organization_id == organization.id,
            InventoryValuationSnapshot.idempotency_key == payload.idempotency_key,
        )
    )
    if existing is not None:
        return _snapshot_read(existing)

    balances = (
        await session.execute(
            select(
                StockBalance.branch_id,
                StockBalance.item_id,
                InventoryItem.sku,
                InventoryItem.name,
                InventoryItem.base_unit_code,
                StockBalance.quantity_on_hand,
            )
            .join(InventoryItem, InventoryItem.id == StockBalance.item_id)
            .where(StockBalance.organization_id == organization.id)
        )
    ).all()
    layer_rows = (
        await session.execute(
            select(
                InventoryCostLayer.branch_id,
                InventoryCostLayer.item_id,
                InventoryCostLayer.unit_code,
                InventoryCostLayer.currency,
                InventoryCostLayer.remaining_quantity,
                InventoryCostLayer.unit_cost,
                InventoryCostLayer.received_at,
                InventoryCostLayer.batch_id,
            )
            .where(
                InventoryCostLayer.organization_id == organization.id,
                InventoryCostLayer.remaining_quantity > 0,
            )
            .order_by(InventoryCostLayer.received_at, InventoryCostLayer.id)
        )
    ).all()
    grouped: dict[tuple[str, str], list[dict[str, object]]] = {}
    costed: dict[tuple[str, str], Decimal] = {}
    for branch, item, unit, currency, qty, unit_cost, received_at, batch_id in layer_rows:
        key = (branch, item)
        quantity = Decimal(qty)
        grouped.setdefault(key, []).append(
            {
                "unit_code": unit,
                "currency": currency,
                "remaining_quantity": str(quantity),
                "unit_cost": str(Decimal(unit_cost)),
                "carrying_value": str(quantity * Decimal(unit_cost)),
                "received_at": received_at.isoformat(),
                "batch_id": batch_id,
            }
        )
        costed[key] = costed.get(key, Decimal(0)) + quantity
    snapshot_data: list[dict[str, object]] = []
    incomplete = False
    for branch, item, sku, name, unit, raw_quantity in balances:
        on_hand = Decimal(raw_quantity or 0)
        costed_quantity = costed.get((branch, item), Decimal(0))
        uncosted = max(on_hand - costed_quantity, Decimal(0))
        incomplete = incomplete or uncosted > 0
        snapshot_data.append(
            {
                "branch_id": branch,
                "item_id": item,
                "sku": sku,
                "name": name,
                "unit_code": unit,
                "quantity_on_hand": str(on_hand),
                "costed_quantity": str(costed_quantity),
                "uncosted_quantity": str(uncosted),
                "cost_layers": grouped.get((branch, item), []),
                "valuation_complete": uncosted == 0,
            }
        )
    captured_at = datetime.now(UTC)
    snapshot = InventoryValuationSnapshot(
        organization_id=organization.id,
        captured_by_user_id=user.id,
        idempotency_key=payload.idempotency_key,
        captured_at=captured_at,
        line_count=len(snapshot_data),
        valuation_status="partial" if incomplete else "costed_stock_only",
        snapshot_data=snapshot_data,
    )
    session.add(snapshot)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        existing = await session.scalar(
            select(InventoryValuationSnapshot).where(
                InventoryValuationSnapshot.organization_id == organization.id,
                InventoryValuationSnapshot.idempotency_key == payload.idempotency_key,
            )
        )
        if existing is None:
            raise HTTPException(status_code=409, detail="Snapshot idempotency conflict") from None
        return _snapshot_read(existing)
    await session.refresh(snapshot)
    return _snapshot_read(snapshot)


def _snapshot_read(snapshot: InventoryValuationSnapshot) -> dict[str, object]:
    return {
        "id": snapshot.id,
        "captured_at": snapshot.captured_at,
        "line_count": snapshot.line_count,
        "valuation_status": snapshot.valuation_status,
        "items": snapshot.snapshot_data,
        "currency_aggregation": "separate_currency_buckets_no_conversion",
        "immutable": True,
    }


@router.get("/valuation/snapshots")
async def list_valuation_snapshots(
    organization: Reader,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, object]:
    rows = (
        await session.scalars(
            select(InventoryValuationSnapshot)
            .where(InventoryValuationSnapshot.organization_id == organization.id)
            .order_by(InventoryValuationSnapshot.captured_at.desc())
            .limit(limit)
        )
    ).all()
    return {"items": [_snapshot_read(row) for row in rows], "count": len(rows)}


@router.get("/valuation/ageing")
async def get_inventory_ageing(
    organization: Reader,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    branch_id: str | None = None,
    item_id: str | None = None,
    as_of_date: date | None = None,
) -> dict[str, object]:
    """Age remaining FIFO cost layers by receipt date, without mixing currencies."""
    as_of = as_of_date or datetime.now(UTC).date()
    statement = (
        select(
            InventoryCostLayer.branch_id,
            InventoryCostLayer.item_id,
            InventoryItem.sku,
            InventoryItem.name,
            InventoryCostLayer.unit_code,
            InventoryCostLayer.currency,
            InventoryCostLayer.batch_id,
            InventoryCostLayer.received_at,
            InventoryCostLayer.remaining_quantity,
            InventoryCostLayer.unit_cost,
        )
        .join(InventoryItem, InventoryItem.id == InventoryCostLayer.item_id)
        .where(
            InventoryCostLayer.organization_id == organization.id,
            InventoryCostLayer.remaining_quantity > 0,
        )
    )
    if branch_id is not None:
        await require_branch_assignment(session, user, organization, branch_id)
        statement = statement.where(InventoryCostLayer.branch_id == branch_id)
    if item_id is not None:
        statement = statement.where(InventoryCostLayer.item_id == item_id)
    rows = (await session.execute(statement.order_by(InventoryCostLayer.received_at))).all()
    buckets: dict[tuple[str, str, str, str], dict[str, Decimal | int]] = {}
    layer_details = []
    for branch, item, sku, name, unit, currency, batch_id, received_at, raw_qty, raw_cost in rows:
        age_days = max((as_of - received_at.date()).days, 0)
        bucket_name = (
            "0_30_days"
            if age_days <= 30
            else "31_60_days"
            if age_days <= 60
            else "61_90_days"
            if age_days <= 90
            else "91_180_days"
            if age_days <= 180
            else "over_180_days"
        )
        quantity, unit_cost = Decimal(raw_qty), Decimal(raw_cost)
        value = quantity * unit_cost
        key = (branch, item, unit, currency)
        bucket = buckets.setdefault(
            key,
            {
                name: Decimal(0)
                for name in (
                    "0_30_days",
                    "31_60_days",
                    "61_90_days",
                    "91_180_days",
                    "over_180_days",
                    "total_quantity",
                    "total_value",
                )
            },
        )
        bucket[bucket_name] += quantity
        bucket["total_quantity"] += quantity
        bucket["total_value"] += value
        layer_details.append(
            {
                "branch_id": branch,
                "item_id": item,
                "sku": sku,
                "name": name,
                "unit_code": unit,
                "currency": currency,
                "batch_id": batch_id,
                "received_at": received_at,
                "age_days": age_days,
                "age_bucket": bucket_name,
                "quantity": quantity,
                "unit_cost": unit_cost,
                "carrying_value": value,
            }
        )
    summary = [
        {"branch_id": key[0], "item_id": key[1], "unit_code": key[2], "currency": key[3], **values}
        for key, values in sorted(buckets.items())
    ]
    return {
        "as_of_date": as_of,
        "items": summary,
        "layers": layer_details,
        "count": len(summary),
        "costed_stock_only": True,
        "note": (
            "Ageing is based on original FIFO receipt-layer dates. Uncosted stock is excluded "
            "and remains visible in the on-hand valuation report."
        ),
    }


@router.get("/valuation/movement-costs")
async def get_inventory_movement_costs(
    organization: Reader,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    branch_id: str | None = None,
    item_id: str | None = None,
    source_type: str | None = Query(default=None, min_length=1, max_length=40),
    from_date: date | None = None,
    to_date: date | None = None,
    limit: int = Query(default=200, ge=1, le=1000),
) -> dict[str, object]:
    """Audit FIFO cost consumption and subsequent cost restorations without FX netting."""
    if from_date and to_date and from_date > to_date:
        raise HTTPException(status_code=422, detail="from_date must not follow to_date")

    movement_query = (
        select(StockMovement, InventoryItem.name, InventoryItem.sku)
        .join(
            InventoryItem,
            (InventoryItem.id == StockMovement.item_id)
            & (InventoryItem.organization_id == StockMovement.organization_id),
        )
        .where(StockMovement.organization_id == organization.id)
    )
    if branch_id is not None:
        await require_branch_assignment(session, user, organization, branch_id)
        movement_query = movement_query.where(StockMovement.branch_id == branch_id)
    if item_id is not None:
        movement_query = movement_query.where(StockMovement.item_id == item_id)
    if source_type is not None:
        movement_query = movement_query.where(StockMovement.source_type == source_type)
    if from_date is not None:
        movement_query = movement_query.where(
            StockMovement.occurred_at >= datetime.combine(from_date, time.min, tzinfo=UTC)
        )
    if to_date is not None:
        movement_query = movement_query.where(
            StockMovement.occurred_at
            < datetime.combine(to_date + timedelta(days=1), time.min, tzinfo=UTC)
        )
    movement_query = movement_query.order_by(StockMovement.occurred_at.desc()).limit(limit)
    movement_rows = (await session.execute(movement_query)).all()

    movement_ids = [row[0].id for row in movement_rows]
    allocation_rows = []
    restoration_rows = []
    if movement_ids:
        allocation_rows = list(
            (
                await session.scalars(
                    select(InventoryCostAllocation).where(
                        InventoryCostAllocation.organization_id == organization.id,
                        InventoryCostAllocation.stock_movement_id.in_(movement_ids),
                    )
                )
            ).all()
        )
        restoration_rows = list(
            (
                await session.scalars(
                    select(InventoryCostRestoration).where(
                        InventoryCostRestoration.organization_id == organization.id,
                        InventoryCostRestoration.reversal_movement_id.in_(movement_ids),
                    )
                )
            ).all()
        )

    allocations_by_movement: dict[str, list[InventoryCostAllocation]] = {}
    for allocation in allocation_rows:
        allocations_by_movement.setdefault(allocation.stock_movement_id, []).append(allocation)
    restorations_by_movement: dict[str, list[InventoryCostRestoration]] = {}
    for restoration in restoration_rows:
        restorations_by_movement.setdefault(restoration.reversal_movement_id, []).append(
            restoration
        )

    events: list[dict[str, object]] = []
    buckets: dict[tuple[str, str, str, str], dict[str, Decimal]] = {}
    for movement, item_name, sku in movement_rows:
        for allocation in allocations_by_movement.get(movement.id, []):
            events.append(
                {
                    "event_type": "cost_consumption",
                    "movement_id": movement.id,
                    "source_type": movement.source_type,
                    "source_id": movement.source_id,
                    "branch_id": movement.branch_id,
                    "item_id": movement.item_id,
                    "sku": sku,
                    "item_name": item_name,
                    "unit_code": movement.unit_code,
                    "quantity": allocation.quantity,
                    "unit_cost": allocation.unit_cost,
                    "extended_cost": allocation.extended_cost,
                    "currency": allocation.currency,
                    "occurred_at": allocation.allocated_at,
                    "cost_layer_id": allocation.cost_layer_id,
                }
            )
            key = (movement.branch_id, movement.item_id, movement.unit_code, allocation.currency)
            bucket = buckets.setdefault(
                key,
                {
                    "consumed_quantity": Decimal(0),
                    "consumed_cost": Decimal(0),
                    "restored_quantity": Decimal(0),
                    "restored_cost": Decimal(0),
                },
            )
            bucket["consumed_quantity"] += allocation.quantity
            bucket["consumed_cost"] += allocation.extended_cost
        for restoration in restorations_by_movement.get(movement.id, []):
            events.append(
                {
                    "event_type": "cost_restoration",
                    "movement_id": movement.id,
                    "source_type": movement.source_type,
                    "source_id": movement.source_id,
                    "branch_id": movement.branch_id,
                    "item_id": movement.item_id,
                    "sku": sku,
                    "item_name": item_name,
                    "unit_code": movement.unit_code,
                    "quantity": restoration.quantity,
                    "unit_cost": restoration.unit_cost,
                    "extended_cost": restoration.extended_cost,
                    "currency": restoration.currency,
                    "occurred_at": restoration.restored_at,
                    "cost_layer_id": restoration.cost_layer_id,
                    "original_allocation_id": restoration.original_allocation_id,
                }
            )
            key = (movement.branch_id, movement.item_id, movement.unit_code, restoration.currency)
            bucket = buckets.setdefault(
                key,
                {
                    "consumed_quantity": Decimal(0),
                    "consumed_cost": Decimal(0),
                    "restored_quantity": Decimal(0),
                    "restored_cost": Decimal(0),
                },
            )
            bucket["restored_quantity"] += restoration.quantity
            bucket["restored_cost"] += restoration.extended_cost

    events.sort(key=lambda event: str(event["occurred_at"]), reverse=True)
    summaries = [
        {
            "branch_id": key[0],
            "item_id": key[1],
            "unit_code": key[2],
            "currency": key[3],
            **values,
            "net_consumed_quantity": values["consumed_quantity"] - values["restored_quantity"],
            "net_consumed_cost": values["consumed_cost"] - values["restored_cost"],
        }
        for key, values in sorted(buckets.items())
    ]
    return {
        "events": events,
        "count": len(events),
        "summary": summaries,
        "summary_count": len(summaries),
        "currency_aggregation": "separate_currency_buckets_no_conversion",
        "scope_note": (
            "Only movements with FIFO allocations or audited restorations appear; "
            "uncosted quantities remain visible in the on-hand valuation report."
        ),
    }


@router.post("/purchase-orders/{purchase_order_id}/receipts", status_code=201)
async def receive_purchase_order(
    purchase_order_id: str,
    payload: GoodsReceiptInput,
    organization: Manager,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict[str, object]:
    po = await session.scalar(
        select(PurchaseOrder)
        .where(
            PurchaseOrder.id == purchase_order_id, PurchaseOrder.organization_id == organization.id
        )
        .options(selectinload(PurchaseOrder.lines))
        .with_for_update()
    )
    if po is None:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    await require_branch_assignment(session, user, organization, po.branch_id)
    prior = await session.scalar(
        select(GoodsReceipt)
        .where(
            GoodsReceipt.organization_id == organization.id,
            GoodsReceipt.idempotency_key == payload.idempotency_key,
        )
        .options(selectinload(GoodsReceipt.lines))
    )
    if prior:
        old: list[tuple[str, Decimal, str | None, date | None, date | None]] = []
        for line in prior.lines:
            batch = await session.get(InventoryBatch, line.batch_id) if line.batch_id else None
            old.append(
                (
                    line.purchase_order_line_id,
                    line.quantity,
                    batch.lot_code if batch else None,
                    batch.manufactured_date if batch else None,
                    batch.expiry_date if batch else None,
                )
            )
        new = sorted(
            (
                line.purchase_order_line_id,
                line.quantity,
                line.lot_code.strip() if line.lot_code else None,
                line.manufactured_date,
                line.expiry_date,
            )
            for line in payload.lines
        )
        if (
            prior.purchase_order_id != po.id
            or prior.reference != payload.reference.strip()
            or prior.supplier_delivery_reference != payload.supplier_delivery_reference
            or sorted(old) != new
        ):
            raise HTTPException(
                status_code=409, detail="Idempotency key belongs to another goods receipt"
            )
        return {
            "id": prior.id,
            "reference": prior.reference,
            "purchase_order_id": po.id,
            "received_at": prior.received_at,
            "lines": [
                {"id": x.id, "item_id": x.item_id, "quantity": x.quantity, "batch_id": x.batch_id}
                for x in prior.lines
            ],
        }
    if po.status not in {"issued", "partially_received"}:
        raise HTTPException(
            status_code=409, detail="Purchase order must be issued before receiving"
        )
    by_id = {line.id: line for line in po.lines}
    if len({line.purchase_order_line_id for line in payload.lines}) != len(payload.lines):
        raise HTTPException(status_code=422, detail="Duplicate purchase order line in receipt")
    receipt = GoodsReceipt(
        id=str(uuid4()),
        organization_id=organization.id,
        purchase_order_id=po.id,
        reference=payload.reference.strip(),
        supplier_delivery_reference=payload.supplier_delivery_reference,
        idempotency_key=payload.idempotency_key,
        received_by_user_id=user.id,
    )
    for input_line in payload.lines:
        po_line = by_id.get(input_line.purchase_order_line_id)
        if po_line is None:
            raise HTTPException(status_code=404, detail="Purchase order line not found")
        if input_line.quantity > po_line.ordered_quantity - po_line.received_quantity:
            raise HTTPException(
                status_code=409,
                detail="Receipt quantity exceeds outstanding purchase order quantity",
            )
        if (
            input_line.expiry_date
            and input_line.manufactured_date
            and input_line.expiry_date < input_line.manufactured_date
        ):
            raise HTTPException(
                status_code=422, detail="Expiry date cannot precede manufacture date"
            )
        item = await session.get(InventoryItem, po_line.item_id)
        if item is None:
            raise HTTPException(status_code=404, detail="Inventory item not found")
        batch_id = None
        tracked = await session.scalar(
            select(InventoryBatch.id)
            .where(
                InventoryBatch.organization_id == organization.id,
                InventoryBatch.item_id == item.id,
                InventoryBatch.branch_id == po.branch_id,
            )
            .limit(1)
        )
        if tracked and not input_line.lot_code:
            raise HTTPException(
                status_code=422, detail="Lot code is required for batch-tracked items"
            )
        if input_line.lot_code:
            lot = input_line.lot_code.strip()
            if not lot:
                raise HTTPException(status_code=422, detail="Lot code cannot be blank")
            batch = await session.scalar(
                select(InventoryBatch).where(
                    InventoryBatch.organization_id == organization.id,
                    InventoryBatch.item_id == item.id,
                    InventoryBatch.branch_id == po.branch_id,
                    InventoryBatch.lot_code == lot,
                )
            )
            if batch is None:
                batch = InventoryBatch(
                    id=str(uuid4()),
                    organization_id=organization.id,
                    item_id=item.id,
                    branch_id=po.branch_id,
                    lot_code=lot,
                    manufactured_date=input_line.manufactured_date,
                    expiry_date=input_line.expiry_date,
                    supplier_reference=payload.supplier_delivery_reference,
                    status=(
                        "quarantined"
                        if input_line.expiry_date and input_line.expiry_date < date.today()
                        else "active"
                    ),
                )
                session.add(batch)
            elif (
                batch.status != "active"
                or batch.expiry_date != input_line.expiry_date
                or batch.manufactured_date != input_line.manufactured_date
            ):
                raise HTTPException(
                    status_code=409, detail="Existing lot is inactive or has conflicting dates"
                )
            batch_id = batch.id
            batch_balance = await session.scalar(
                select(BatchStockBalance)
                .where(
                    BatchStockBalance.organization_id == organization.id,
                    BatchStockBalance.branch_id == po.branch_id,
                    BatchStockBalance.item_id == item.id,
                    BatchStockBalance.batch_id == batch_id,
                )
                .with_for_update()
            )
            if batch_balance is None:
                session.add(
                    BatchStockBalance(
                        organization_id=organization.id,
                        branch_id=po.branch_id,
                        item_id=item.id,
                        batch_id=batch_id,
                        quantity_on_hand=input_line.quantity,
                    )
                )
            else:
                batch_balance.quantity_on_hand += input_line.quantity
        balance = await session.scalar(
            select(StockBalance)
            .where(
                StockBalance.organization_id == organization.id,
                StockBalance.branch_id == po.branch_id,
                StockBalance.item_id == item.id,
            )
            .with_for_update()
        )
        if balance is None:
            session.add(
                StockBalance(
                    organization_id=organization.id,
                    branch_id=po.branch_id,
                    item_id=item.id,
                    quantity_on_hand=input_line.quantity,
                )
            )
        else:
            balance.quantity_on_hand += input_line.quantity
            balance.version += 1
        movement_key = f"grn:{payload.idempotency_key}:{po_line.id}"
        session.add(
            StockMovement(
                organization_id=organization.id,
                branch_id=po.branch_id,
                item_id=item.id,
                batch_id=batch_id,
                quantity_delta=input_line.quantity,
                unit_code=po_line.unit_code,
                source_type="purchase_receipt",
                source_id=receipt.id,
                reason=f"Goods receipt {payload.reference}",
                idempotency_key=movement_key,
                actor_user_id=user.id,
            )
        )
        po_line.received_quantity += input_line.quantity
        receipt_line = GoodsReceiptLine(
            id=str(uuid4()),
            organization_id=organization.id,
            purchase_order_line_id=po_line.id,
            item_id=item.id,
            quantity=input_line.quantity,
            batch_id=batch_id,
        )
        receipt.lines.append(receipt_line)
        session.add(
            InventoryCostLayer(
                organization_id=organization.id,
                branch_id=po.branch_id,
                item_id=item.id,
                batch_id=batch_id,
                goods_receipt_line_id=receipt_line.id,
                purchase_order_line_id=po_line.id,
                received_quantity=input_line.quantity,
                remaining_quantity=input_line.quantity,
                unit_code=po_line.unit_code,
                unit_cost=po_line.unit_cost,
                currency=po.currency,
                received_at=datetime.now(UTC),
            )
        )
    po.status = (
        "received"
        if all(x.received_quantity == x.ordered_quantity for x in po.lines)
        else "partially_received"
    )
    if po.status == "received" and po.completed_at is None:
        po.completed_at = datetime.now(UTC)
    session.add(receipt)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=409, detail="Receipt reference, lot or idempotency conflict"
        ) from exc
    await session.refresh(receipt, attribute_names=["lines"])
    return {
        "id": receipt.id,
        "reference": receipt.reference,
        "purchase_order_id": po.id,
        "received_at": receipt.received_at,
        "lines": [
            {"id": x.id, "item_id": x.item_id, "quantity": x.quantity, "batch_id": x.batch_id}
            for x in receipt.lines
        ],
    }
