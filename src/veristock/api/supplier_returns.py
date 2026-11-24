"""Auditable supplier returns with atomic stock-ledger posting."""

from datetime import UTC, datetime
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
from veristock.inventory.costing import allocate_fifo_cost
from veristock.inventory.models import (
    BatchStockBalance,
    InventoryBatch,
    InventoryItem,
    StockBalance,
    StockMovement,
    Supplier,
)
from veristock.inventory.procurement import SupplierReturn, SupplierReturnLine
from veristock.organizations.models import Branch

router = APIRouter(prefix="/procurement/supplier-returns", tags=["supplier-returns"])
Manager = Annotated[Organization, Depends(require_permission("inventory.manage"))]
Reader = Annotated[Organization, Depends(require_permission("inventory.read"))]


class SupplierReturnLineInput(BaseModel):
    item_id: str
    batch_id: str | None = None
    quantity: Decimal = Field(gt=0, max_digits=18, decimal_places=4)


class SupplierReturnInput(BaseModel):
    reference: str = Field(min_length=2, max_length=80)
    supplier_id: str
    branch_id: str
    idempotency_key: str = Field(min_length=8, max_length=128)
    reason: str = Field(min_length=3, max_length=500)
    lines: list[SupplierReturnLineInput] = Field(min_length=1, max_length=200)


def _read(record: SupplierReturn) -> dict[str, object]:
    return {
        "id": record.id,
        "reference": record.reference,
        "supplier_id": record.supplier_id,
        "branch_id": record.branch_id,
        "status": record.status,
        "reason": record.reason,
        "created_at": record.created_at,
        "dispatched_at": record.dispatched_at,
        "lines": [
            {
                "id": line.id,
                "item_id": line.item_id,
                "batch_id": line.batch_id,
                "quantity": line.quantity,
                "unit_code": line.unit_code,
            }
            for line in record.lines
        ],
    }


@router.post("", status_code=201)
async def create_supplier_return(
    payload: SupplierReturnInput,
    organization: Manager,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict[str, object]:
    await require_branch_assignment(session, user, organization, payload.branch_id)
    prior = await session.scalar(
        select(SupplierReturn)
        .where(
            SupplierReturn.organization_id == organization.id,
            SupplierReturn.idempotency_key == payload.idempotency_key,
        )
        .options(selectinload(SupplierReturn.lines))
    )
    normalized = sorted((x.item_id, x.batch_id or "", x.quantity) for x in payload.lines)
    if prior:
        existing = sorted((x.item_id, x.batch_id or "", x.quantity) for x in prior.lines)
        if (
            prior.reference != payload.reference.strip()
            or prior.supplier_id != payload.supplier_id
            or prior.branch_id != payload.branch_id
            or prior.reason != payload.reason.strip()
            or existing != normalized
        ):
            raise HTTPException(
                status_code=409, detail="Idempotency key belongs to another supplier return"
            )
        return _read(prior)
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
    record = SupplierReturn(
        id=str(uuid4()),
        organization_id=organization.id,
        supplier_id=supplier.id,
        branch_id=branch.id,
        reference=payload.reference.strip(),
        status="draft",
        reason=payload.reason.strip(),
        idempotency_key=payload.idempotency_key,
        created_by_user_id=user.id,
    )
    seen: set[tuple[str, str | None]] = set()
    for line in payload.lines:
        key = (line.item_id, line.batch_id)
        if key in seen:
            raise HTTPException(status_code=422, detail="Duplicate item/batch supplier return line")
        seen.add(key)
        item = await session.scalar(
            select(InventoryItem).where(
                InventoryItem.id == line.item_id,
                InventoryItem.organization_id == organization.id,
                InventoryItem.status == "active",
            )
        )
        if item is None:
            raise HTTPException(status_code=404, detail="Active inventory item not found")
        tracked = await session.scalar(
            select(InventoryBatch.id)
            .where(
                InventoryBatch.organization_id == organization.id,
                InventoryBatch.item_id == item.id,
                InventoryBatch.branch_id == branch.id,
            )
            .limit(1)
        )
        if tracked and not line.batch_id:
            raise HTTPException(
                status_code=422, detail="Batch selection is required for batch-tracked items"
            )
        if line.batch_id:
            batch = await session.scalar(
                select(InventoryBatch).where(
                    InventoryBatch.id == line.batch_id,
                    InventoryBatch.organization_id == organization.id,
                    InventoryBatch.item_id == item.id,
                    InventoryBatch.branch_id == branch.id,
                )
            )
            if batch is None:
                raise HTTPException(status_code=404, detail="Batch not found at selected branch")
        record.lines.append(
            SupplierReturnLine(
                id=str(uuid4()),
                organization_id=organization.id,
                item_id=item.id,
                batch_id=line.batch_id,
                quantity=line.quantity,
                unit_code=item.base_unit_code,
            )
        )
    session.add(record)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=409, detail="Supplier return reference or idempotency conflict"
        ) from exc
    await session.refresh(record, attribute_names=["lines"])
    return _read(record)


@router.get("")
async def list_supplier_returns(
    organization: Reader,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    status: str | None = None,
) -> list[dict[str, object]]:
    query = (
        select(SupplierReturn)
        .where(SupplierReturn.organization_id == organization.id)
        .options(selectinload(SupplierReturn.lines))
        .order_by(SupplierReturn.created_at.desc())
    )
    if status:
        if status not in {"draft", "dispatched", "cancelled"}:
            raise HTTPException(status_code=422, detail="Invalid supplier return status")
        query = query.where(SupplierReturn.status == status)
    return [_read(x) for x in (await session.scalars(query)).all()]


@router.post("/{return_id}/dispatch")
async def dispatch_supplier_return(
    return_id: str,
    organization: Manager,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict[str, object]:
    record = await session.scalar(
        select(SupplierReturn)
        .where(SupplierReturn.id == return_id, SupplierReturn.organization_id == organization.id)
        .options(selectinload(SupplierReturn.lines))
        .with_for_update()
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Supplier return not found")
    await require_branch_assignment(session, user, organization, record.branch_id)
    if record.status == "dispatched":
        return _read(record)
    if record.status != "draft":
        raise HTTPException(status_code=409, detail="Only draft supplier returns can be dispatched")
    for line in record.lines:
        balance = await session.scalar(
            select(StockBalance)
            .where(
                StockBalance.organization_id == organization.id,
                StockBalance.branch_id == record.branch_id,
                StockBalance.item_id == line.item_id,
            )
            .with_for_update()
        )
        if balance is None or balance.quantity_on_hand < line.quantity:
            raise HTTPException(
                status_code=409, detail="Insufficient on-hand stock for supplier return"
            )
        if line.batch_id:
            batch_balance = await session.scalar(
                select(BatchStockBalance)
                .where(
                    BatchStockBalance.organization_id == organization.id,
                    BatchStockBalance.branch_id == record.branch_id,
                    BatchStockBalance.item_id == line.item_id,
                    BatchStockBalance.batch_id == line.batch_id,
                )
                .with_for_update()
            )
            if batch_balance is None or batch_balance.quantity_on_hand < line.quantity:
                raise HTTPException(
                    status_code=409, detail="Insufficient batch quantity for supplier return"
                )
            batch_balance.quantity_on_hand -= line.quantity
        balance.quantity_on_hand -= line.quantity
        balance.version += 1
        movement = StockMovement(
            organization_id=organization.id,
            branch_id=record.branch_id,
            item_id=line.item_id,
            batch_id=line.batch_id,
            quantity_delta=-line.quantity,
            unit_code=line.unit_code,
            source_type="supplier_return",
            source_id=record.id,
            reason=record.reason,
            idempotency_key=f"supplier-return:{record.id}:{line.id}",
            actor_user_id=user.id,
        )
        session.add(movement)
        await allocate_fifo_cost(session, movement)
    record.status = "dispatched"
    record.dispatched_by_user_id = user.id
    record.dispatched_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(record, attribute_names=["lines"])
    return _read(record)
