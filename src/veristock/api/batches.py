"""Tenant- and branch-scoped batch receiving, FEFO issue and expiry visibility."""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from veristock.api.branch_access import accessible_branch_ids, require_branch_assignment
from veristock.identity.authorization import Organization
from veristock.identity.authorization_dependencies import (
    get_current_user,
    get_db_session,
    require_permission,
)
from veristock.identity.models import User
from veristock.inventory.batches import allocate_fefo
from veristock.inventory.models import (
    BatchStockBalance,
    InventoryBatch,
    InventoryItem,
    StockBalance,
    StockMovement,
)
from veristock.organizations.models import Branch

router = APIRouter(prefix="/inventory/batches", tags=["inventory-batches"])
BatchManager = Annotated[Organization, Depends(require_permission("inventory.manage"))]
BatchReader = Annotated[Organization, Depends(require_permission("inventory.read"))]


class BatchReceive(BaseModel):
    branch_id: str
    item_id: str
    lot_code: str = Field(min_length=1, max_length=100)
    quantity: Decimal = Field(gt=0, max_digits=18, decimal_places=4)
    manufactured_date: date | None = None
    expiry_date: date | None = None
    supplier_reference: str | None = Field(default=None, max_length=120)
    idempotency_key: str = Field(min_length=8, max_length=128)

    @field_validator("lot_code")
    @classmethod
    def normalize_lot(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Lot code cannot be blank")
        return value


class BatchStatusUpdate(BaseModel):
    status: Literal["active", "quarantined", "recalled", "closed"]


class BatchIssue(BaseModel):
    branch_id: str
    item_id: str
    quantity: Decimal = Field(gt=0, max_digits=18, decimal_places=4)
    idempotency_key: str = Field(min_length=8, max_length=128)
    reason: str = Field(default="FEFO stock issue", min_length=3, max_length=300)


class BatchRead(BaseModel):
    id: str
    item_id: str
    branch_id: str
    lot_code: str
    manufactured_date: date | None
    expiry_date: date | None
    supplier_reference: str | None
    status: str
    quantity_on_hand: Decimal
    received_at: datetime


class BatchIssueRead(BaseModel):
    movement_ids: list[str]
    allocations: list[dict[str, str]]
    remaining_item_quantity: Decimal


@router.post("/receive", response_model=BatchRead, status_code=201)
async def receive_batch(
    payload: BatchReceive,
    organization: BatchManager,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> BatchRead:
    await require_branch_assignment(session, user, organization, payload.branch_id)
    if (
        payload.expiry_date
        and payload.manufactured_date
        and payload.expiry_date < payload.manufactured_date
    ):
        raise HTTPException(status_code=422, detail="Expiry date cannot precede manufacture date")
    prior = await session.scalar(
        select(StockMovement).where(
            StockMovement.organization_id == organization.id,
            StockMovement.idempotency_key == payload.idempotency_key,
        )
    )
    if prior is not None:
        batch = await session.scalar(
            select(InventoryBatch).where(
                InventoryBatch.id == prior.source_id,
                InventoryBatch.organization_id == organization.id,
            )
        )
        if (
            prior.source_type != "batch_receipt"
            or batch is None
            or prior.branch_id != payload.branch_id
            or prior.item_id != payload.item_id
            or prior.quantity_delta != payload.quantity
            or batch.lot_code != payload.lot_code
            or batch.manufactured_date != payload.manufactured_date
            or batch.expiry_date != payload.expiry_date
            or batch.supplier_reference != payload.supplier_reference
        ):
            raise HTTPException(
                status_code=409, detail="Idempotency key belongs to another operation"
            )
        bal = await session.scalar(
            select(BatchStockBalance).where(
                BatchStockBalance.batch_id == batch.id,
                BatchStockBalance.branch_id == payload.branch_id,
            )
        )
        return BatchRead(
            **{
                **{
                    k: getattr(batch, k)
                    for k in (
                        "id",
                        "item_id",
                        "branch_id",
                        "lot_code",
                        "manufactured_date",
                        "expiry_date",
                        "supplier_reference",
                        "status",
                        "received_at",
                    )
                },
                "quantity_on_hand": bal.quantity_on_hand if bal else Decimal("0"),
            }
        )
    branch = await session.scalar(
        select(Branch).where(
            Branch.id == payload.branch_id,
            Branch.organization_id == organization.id,
            Branch.status == "active",
        )
    )
    item = await session.scalar(
        select(InventoryItem).where(
            InventoryItem.id == payload.item_id,
            InventoryItem.organization_id == organization.id,
            InventoryItem.status == "active",
        )
    )
    if branch is None or item is None:
        raise HTTPException(status_code=404, detail="Active branch or item not found")
    batch = InventoryBatch(
        id=str(uuid4()),
        organization_id=organization.id,
        item_id=item.id,
        branch_id=branch.id,
        lot_code=payload.lot_code,
        manufactured_date=payload.manufactured_date,
        expiry_date=payload.expiry_date,
        supplier_reference=payload.supplier_reference,
        status="active",
    )
    session.add(batch)
    balance = await session.scalar(
        select(StockBalance)
        .where(
            StockBalance.organization_id == organization.id,
            StockBalance.branch_id == branch.id,
            StockBalance.item_id == item.id,
        )
        .with_for_update()
    )
    if balance is None:
        balance = StockBalance(
            organization_id=organization.id,
            branch_id=branch.id,
            item_id=item.id,
            quantity_on_hand=payload.quantity,
        )
        session.add(balance)
    else:
        balance.quantity_on_hand += payload.quantity
        balance.version += 1
    batch_balance = BatchStockBalance(
        organization_id=organization.id,
        branch_id=branch.id,
        item_id=item.id,
        batch_id=batch.id,
        quantity_on_hand=payload.quantity,
    )
    session.add(batch_balance)
    session.add(
        StockMovement(
            organization_id=organization.id,
            branch_id=branch.id,
            item_id=item.id,
            batch_id=batch.id,
            quantity_delta=payload.quantity,
            unit_code=item.base_unit_code,
            source_type="batch_receipt",
            source_id=batch.id,
            idempotency_key=payload.idempotency_key,
            actor_user_id=user.id,
        )
    )
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=409, detail="Lot code already exists or receipt conflicts"
        ) from exc
    await session.refresh(batch)
    return BatchRead(
        id=batch.id,
        item_id=item.id,
        branch_id=batch.branch_id,
        lot_code=batch.lot_code,
        manufactured_date=batch.manufactured_date,
        expiry_date=batch.expiry_date,
        supplier_reference=batch.supplier_reference,
        status=batch.status,
        quantity_on_hand=payload.quantity,
        received_at=batch.received_at,
    )


@router.post("/issue-fefo", response_model=BatchIssueRead, status_code=201)
async def issue_fefo(
    payload: BatchIssue,
    organization: BatchManager,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> BatchIssueRead:
    await require_branch_assignment(session, user, organization, payload.branch_id)
    existing = await session.scalar(
        select(StockMovement).where(
            StockMovement.organization_id == organization.id,
            StockMovement.idempotency_key == payload.idempotency_key,
        )
    )
    if existing is not None:
        movements = list(
            (
                await session.scalars(
                    select(StockMovement)
                    .where(
                        StockMovement.organization_id == organization.id,
                        StockMovement.source_type == "batch_issue",
                        StockMovement.source_id == payload.idempotency_key,
                    )
                    .order_by(StockMovement.idempotency_key)
                )
            ).all()
        )
        if (
            existing.source_type != "batch_issue"
            or existing.branch_id != payload.branch_id
            or existing.item_id != payload.item_id
            or any(m.reason != payload.reason for m in movements)
            or sum((-m.quantity_delta for m in movements), Decimal("0")) != payload.quantity
        ):
            raise HTTPException(
                status_code=409, detail="Idempotency key belongs to another operation"
            )
        current = await session.scalar(
            select(StockBalance).where(
                StockBalance.organization_id == organization.id,
                StockBalance.branch_id == payload.branch_id,
                StockBalance.item_id == payload.item_id,
            )
        )
        return BatchIssueRead(
            movement_ids=[m.id for m in movements],
            allocations=[
                {"batch_id": m.batch_id or "", "quantity": str(-m.quantity_delta)}
                for m in movements
            ],
            remaining_item_quantity=current.quantity_on_hand if current else Decimal("0"),
        )
    item = await session.scalar(
        select(InventoryItem).where(
            InventoryItem.id == payload.item_id,
            InventoryItem.organization_id == organization.id,
            InventoryItem.status == "active",
        )
    )
    branch = await session.scalar(
        select(Branch).where(
            Branch.id == payload.branch_id,
            Branch.organization_id == organization.id,
            Branch.status == "active",
        )
    )
    if item is None or branch is None:
        raise HTTPException(status_code=404, detail="Active branch or item not found")
    total = await session.scalar(
        select(StockBalance)
        .where(
            StockBalance.organization_id == organization.id,
            StockBalance.branch_id == branch.id,
            StockBalance.item_id == item.id,
        )
        .with_for_update()
    )
    if total is None or total.quantity_on_hand < payload.quantity:
        raise HTTPException(status_code=409, detail="Insufficient total stock")
    try:
        allocations = await allocate_fefo(
            session,
            organization_id=organization.id,
            branch_id=branch.id,
            item_id=item.id,
            quantity=payload.quantity,
            on_date=date.today(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    movement_ids: list[str] = []
    allocation_rows: list[dict[str, str]] = []
    for index, (lot_balance, qty) in enumerate(allocations):
        lot_balance.quantity_on_hand -= qty
        movement_id = str(uuid4())
        movement_ids.append(movement_id)
        allocation_rows.append({"batch_id": lot_balance.batch_id, "quantity": str(qty)})
        session.add(
            StockMovement(
                id=movement_id,
                organization_id=organization.id,
                branch_id=branch.id,
                item_id=item.id,
                batch_id=lot_balance.batch_id,
                quantity_delta=-qty,
                unit_code=item.base_unit_code,
                source_type="batch_issue",
                source_id=payload.idempotency_key,
                reason=payload.reason,
                idempotency_key=(
                    payload.idempotency_key if index == 0 else f"{payload.idempotency_key}:{index}"
                ),
                actor_user_id=user.id,
            )
        )
    total.quantity_on_hand -= payload.quantity
    total.version += 1
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Issue conflicts with another request") from exc
    return BatchIssueRead(
        movement_ids=movement_ids,
        allocations=allocation_rows,
        remaining_item_quantity=total.quantity_on_hand,
    )


@router.get("", response_model=list[BatchRead])
async def list_batches(
    organization: BatchReader,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    branch_id: str | None = None,
    item_id: str | None = None,
    expiring_within_days: int | None = Query(default=None, ge=0, le=3650),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[BatchRead]:
    from datetime import timedelta

    allowed = await accessible_branch_ids(session, user, organization)
    if branch_id and allowed is not None and branch_id not in allowed:
        raise HTTPException(status_code=404, detail="Branch not found")
    stmt = (
        select(InventoryBatch, BatchStockBalance)
        .join(BatchStockBalance, BatchStockBalance.batch_id == InventoryBatch.id)
        .where(
            InventoryBatch.organization_id == organization.id,
            BatchStockBalance.organization_id == organization.id,
        )
    )
    if branch_id:
        stmt = stmt.where(InventoryBatch.branch_id == branch_id)
    elif allowed is not None:
        stmt = stmt.where(InventoryBatch.branch_id.in_(allowed))
    if item_id:
        stmt = stmt.where(InventoryBatch.item_id == item_id)
    if expiring_within_days is not None:
        stmt = stmt.where(
            InventoryBatch.expiry_date.is_not(None),
            InventoryBatch.expiry_date <= date.today() + timedelta(days=expiring_within_days),
            InventoryBatch.expiry_date >= date.today(),
        )
    rows = (
        await session.execute(
            stmt.order_by(
                InventoryBatch.expiry_date.is_(None),
                InventoryBatch.expiry_date,
                InventoryBatch.received_at,
            ).limit(limit)
        )
    ).all()
    return [
        BatchRead(
            id=b.id,
            item_id=b.item_id,
            branch_id=b.branch_id,
            lot_code=b.lot_code,
            manufactured_date=b.manufactured_date,
            expiry_date=b.expiry_date,
            supplier_reference=b.supplier_reference,
            status=b.status,
            quantity_on_hand=bal.quantity_on_hand,
            received_at=b.received_at,
        )
        for b, bal in rows
    ]


@router.patch("/{batch_id}/status", response_model=BatchRead)
async def update_batch_status(
    batch_id: str,
    payload: BatchStatusUpdate,
    organization: BatchManager,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> BatchRead:
    batch = await session.scalar(
        select(InventoryBatch).where(
            InventoryBatch.id == batch_id,
            InventoryBatch.organization_id == organization.id,
        )
    )
    if batch is None:
        raise HTTPException(status_code=404, detail="Batch not found")
    await require_branch_assignment(session, user, organization, batch.branch_id)
    balance = await session.scalar(
        select(BatchStockBalance).where(
            BatchStockBalance.organization_id == organization.id,
            BatchStockBalance.batch_id == batch.id,
        )
    )
    batch.status = payload.status
    await session.commit()
    return BatchRead(
        id=batch.id,
        item_id=batch.item_id,
        branch_id=batch.branch_id,
        lot_code=batch.lot_code,
        manufactured_date=batch.manufactured_date,
        expiry_date=batch.expiry_date,
        supplier_reference=batch.supplier_reference,
        status=batch.status,
        quantity_on_hand=balance.quantity_on_hand if balance else Decimal("0"),
        received_at=batch.received_at,
    )
