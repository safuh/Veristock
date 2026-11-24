"""Purchase-order issue and partial goods-receipt workflows."""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
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
    StockBalance,
    StockMovement,
    Supplier,
)
from veristock.inventory.procurement import (
    GoodsReceipt,
    GoodsReceiptLine,
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
            "not_scheduled" if po.expected_delivery_date is None else
            "pending" if po.completed_at is None else
            "on_time" if po.completed_at.date() <= po.expected_delivery_date else "late"
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
        receipt.lines.append(
            GoodsReceiptLine(
                id=str(uuid4()),
                organization_id=organization.id,
                purchase_order_line_id=po_line.id,
                item_id=item.id,
                quantity=input_line.quantity,
                batch_id=batch_id,
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
