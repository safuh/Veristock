"""Controlled inter-branch stock transfers with dispatch and receipt confirmation."""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
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
)
from veristock.inventory.procurement import InventoryCostAllocation, InventoryCostLayer
from veristock.inventory.transfers import StockTransfer, StockTransferLine
from veristock.organizations.models import Branch

router = APIRouter(prefix="/inventory/transfers", tags=["inventory-transfers"])
TransferManager = Annotated[Organization, Depends(require_permission("inventory.manage"))]
TransferReader = Annotated[Organization, Depends(require_permission("inventory.read"))]


class TransferLineCreate(BaseModel):
    item_id: str
    quantity: Decimal = Field(gt=0, max_digits=18, decimal_places=4)
    batch_id: str | None = None


class TransferCreate(BaseModel):
    reference: str = Field(min_length=2, max_length=80)
    source_branch_id: str
    destination_branch_id: str
    idempotency_key: str = Field(min_length=8, max_length=128)
    note: str | None = Field(default=None, max_length=500)
    lines: list[TransferLineCreate] = Field(min_length=1, max_length=200)


class TransferLineRead(BaseModel):
    id: str
    item_id: str
    batch_id: str | None
    destination_batch_id: str | None
    quantity: Decimal
    unit_code: str


class TransferRead(BaseModel):
    id: str
    reference: str
    source_branch_id: str
    destination_branch_id: str
    status: str
    note: str | None
    created_at: datetime
    dispatched_at: datetime | None
    received_at: datetime | None
    lines: list[TransferLineRead]


def _read(transfer: StockTransfer) -> TransferRead:
    return TransferRead(
        id=transfer.id,
        reference=transfer.reference,
        source_branch_id=transfer.source_branch_id,
        destination_branch_id=transfer.destination_branch_id,
        status=transfer.status,
        note=transfer.note,
        created_at=transfer.created_at,
        dispatched_at=transfer.dispatched_at,
        received_at=transfer.received_at,
        lines=[
            TransferLineRead(
                id=line.id,
                item_id=line.item_id,
                batch_id=line.batch_id,
                destination_batch_id=line.destination_batch_id,
                quantity=line.quantity,
                unit_code=line.unit_code,
            )
            for line in transfer.lines
        ],
    )


@router.post("", response_model=TransferRead, status_code=201)
async def create_transfer(
    payload: TransferCreate,
    organization: TransferManager,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> TransferRead:
    if payload.source_branch_id == payload.destination_branch_id:
        raise HTTPException(status_code=422, detail="Source and destination branches must differ")
    prior = await session.scalar(
        select(StockTransfer)
        .where(
            StockTransfer.organization_id == organization.id,
            StockTransfer.idempotency_key == payload.idempotency_key,
        )
        .options(selectinload(StockTransfer.lines))
    )
    if prior is not None:
        await require_branch_assignment(session, user, organization, prior.source_branch_id)
        await require_branch_assignment(session, user, organization, prior.destination_branch_id)
        prior_lines = sorted(
            (line.item_id, line.batch_id or "", line.quantity) for line in prior.lines
        )
        requested_lines = sorted(
            (line.item_id, line.batch_id or "", line.quantity) for line in payload.lines
        )
        if (
            prior.reference != payload.reference.strip()
            or prior.source_branch_id != payload.source_branch_id
            or prior.destination_branch_id != payload.destination_branch_id
            or prior.note != (payload.note.strip() if payload.note else None)
            or prior_lines != requested_lines
        ):
            raise HTTPException(
                status_code=409, detail="Idempotency key belongs to another transfer"
            )
        return _read(prior)

    for branch_id in (payload.source_branch_id, payload.destination_branch_id):
        branch = await session.scalar(
            select(Branch).where(
                Branch.id == branch_id,
                Branch.organization_id == organization.id,
                Branch.status == "active",
            )
        )
        if branch is None:
            raise HTTPException(status_code=404, detail="Active transfer branch not found")
        await require_branch_assignment(session, user, organization, branch_id)

    transfer = StockTransfer(
        id=str(uuid4()),
        organization_id=organization.id,
        reference=payload.reference.strip(),
        source_branch_id=payload.source_branch_id,
        destination_branch_id=payload.destination_branch_id,
        status="draft",
        note=payload.note.strip() if payload.note else None,
        idempotency_key=payload.idempotency_key,
        created_by_user_id=user.id,
    )
    seen: set[tuple[str, str | None]] = set()
    for line_payload in payload.lines:
        key = (line_payload.item_id, line_payload.batch_id)
        if key in seen:
            raise HTTPException(status_code=422, detail="Duplicate item/batch transfer line")
        seen.add(key)
        item = await session.scalar(
            select(InventoryItem).where(
                InventoryItem.id == line_payload.item_id,
                InventoryItem.organization_id == organization.id,
                InventoryItem.status == "active",
            )
        )
        if item is None:
            raise HTTPException(status_code=404, detail="Active inventory item not found")
        if line_payload.batch_id:
            batch = await session.scalar(
                select(InventoryBatch).where(
                    InventoryBatch.id == line_payload.batch_id,
                    InventoryBatch.organization_id == organization.id,
                    InventoryBatch.branch_id == payload.source_branch_id,
                    InventoryBatch.item_id == item.id,
                )
            )
            if batch is None:
                raise HTTPException(status_code=404, detail="Batch not found at source branch")
            if batch.status != "active" or (batch.expiry_date and batch.expiry_date < date.today()):
                raise HTTPException(
                    status_code=409, detail="Only active, unexpired batches can be transferred"
                )
        transfer.lines.append(
            StockTransferLine(
                id=str(uuid4()),
                organization_id=organization.id,
                item_id=item.id,
                batch_id=line_payload.batch_id,
                quantity=line_payload.quantity,
                unit_code=item.base_unit_code,
            )
        )
    session.add(transfer)
    await session.commit()
    await session.refresh(transfer, attribute_names=["lines"])
    return _read(transfer)


@router.get("/{transfer_id}", response_model=TransferRead)
async def get_transfer(
    transfer_id: str,
    organization: TransferReader,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> TransferRead:
    transfer = await session.scalar(
        select(StockTransfer)
        .where(
            StockTransfer.id == transfer_id,
            StockTransfer.organization_id == organization.id,
        )
        .options(selectinload(StockTransfer.lines))
    )
    if transfer is None:
        raise HTTPException(status_code=404, detail="Transfer not found")
    await require_branch_assignment(session, user, organization, transfer.source_branch_id)
    await require_branch_assignment(session, user, organization, transfer.destination_branch_id)
    return _read(transfer)


@router.get("", response_model=list[TransferRead])
async def list_transfers(
    organization: TransferReader,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> list[TransferRead]:
    rows = list(
        (
            await session.scalars(
                select(StockTransfer)
                .where(StockTransfer.organization_id == organization.id)
                .options(selectinload(StockTransfer.lines))
                .order_by(StockTransfer.created_at.desc())
            )
        ).all()
    )
    visible = []
    for row in rows:
        try:
            await require_branch_assignment(session, user, organization, row.source_branch_id)
            await require_branch_assignment(session, user, organization, row.destination_branch_id)
        except HTTPException:
            continue
        visible.append(_read(row))
    return visible


@router.post("/{transfer_id}/dispatch", response_model=TransferRead)
async def dispatch_transfer(
    transfer_id: str,
    organization: TransferManager,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> TransferRead:
    transfer = await session.scalar(
        select(StockTransfer)
        .where(StockTransfer.id == transfer_id, StockTransfer.organization_id == organization.id)
        .options(selectinload(StockTransfer.lines))
        .with_for_update()
    )
    if transfer is None:
        raise HTTPException(status_code=404, detail="Transfer not found")
    await require_branch_assignment(session, user, organization, transfer.source_branch_id)
    if transfer.status == "dispatched" or transfer.status == "received":
        return _read(transfer)
    if transfer.status != "draft":
        raise HTTPException(status_code=409, detail="Only draft transfers can be dispatched")

    for line in transfer.lines:
        balance = await session.scalar(
            select(StockBalance)
            .where(
                StockBalance.organization_id == organization.id,
                StockBalance.branch_id == transfer.source_branch_id,
                StockBalance.item_id == line.item_id,
            )
            .with_for_update()
        )
        if balance is None or balance.quantity_on_hand < line.quantity:
            raise HTTPException(status_code=409, detail="Insufficient source stock")
        batch_total = Decimal(
            await session.scalar(
                select(func.coalesce(func.sum(BatchStockBalance.quantity_on_hand), 0)).where(
                    BatchStockBalance.organization_id == organization.id,
                    BatchStockBalance.branch_id == transfer.source_branch_id,
                    BatchStockBalance.item_id == line.item_id,
                )
            )
            or 0
        )
        if line.batch_id is None:
            if batch_total > 0 or balance.quantity_on_hand - batch_total < line.quantity:
                raise HTTPException(
                    status_code=409, detail="Select a specific batch for batch-tracked stock"
                )
        else:
            batch = await session.scalar(
                select(InventoryBatch)
                .where(
                    InventoryBatch.id == line.batch_id,
                    InventoryBatch.organization_id == organization.id,
                    InventoryBatch.branch_id == transfer.source_branch_id,
                    InventoryBatch.item_id == line.item_id,
                )
                .with_for_update()
            )
            if (
                batch is None
                or batch.status != "active"
                or (batch.expiry_date is not None and batch.expiry_date < date.today())
            ):
                raise HTTPException(
                    status_code=409, detail="Batch is no longer eligible for transfer"
                )
            batch_balance = await session.scalar(
                select(BatchStockBalance)
                .where(
                    BatchStockBalance.organization_id == organization.id,
                    BatchStockBalance.branch_id == transfer.source_branch_id,
                    BatchStockBalance.item_id == line.item_id,
                    BatchStockBalance.batch_id == line.batch_id,
                )
                .with_for_update()
            )
            if batch_balance is None or batch_balance.quantity_on_hand < line.quantity:
                raise HTTPException(status_code=409, detail="Insufficient batch stock")
            batch_balance.quantity_on_hand -= line.quantity
        balance.quantity_on_hand -= line.quantity
        balance.version += 1
        movement = StockMovement(
            id=str(uuid4()),
            organization_id=organization.id,
            branch_id=transfer.source_branch_id,
            item_id=line.item_id,
            batch_id=line.batch_id,
            quantity_delta=-line.quantity,
            unit_code=line.unit_code,
            source_type="stock_transfer",
            source_id=transfer.id,
            reason=f"Transfer {transfer.reference} dispatched",
            idempotency_key=f"transfer:{transfer.id}:dispatch:{line.id}",
            actor_user_id=user.id,
        )
        session.add(movement)
        await session.flush()
        await allocate_fifo_cost(session, movement)
    transfer.status = "dispatched"
    transfer.dispatched_by_user_id = user.id
    transfer.dispatched_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(transfer, attribute_names=["lines"])
    return _read(transfer)


@router.post("/{transfer_id}/receive", response_model=TransferRead)
async def receive_transfer(
    transfer_id: str,
    organization: TransferManager,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> TransferRead:
    transfer = await session.scalar(
        select(StockTransfer)
        .where(StockTransfer.id == transfer_id, StockTransfer.organization_id == organization.id)
        .options(selectinload(StockTransfer.lines))
        .with_for_update()
    )
    if transfer is None:
        raise HTTPException(status_code=404, detail="Transfer not found")
    await require_branch_assignment(session, user, organization, transfer.destination_branch_id)
    if transfer.status == "received":
        return _read(transfer)
    if transfer.status != "dispatched":
        raise HTTPException(status_code=409, detail="Only dispatched transfers can be received")

    for line in transfer.lines:
        destination_balance = await session.scalar(
            select(StockBalance)
            .where(
                StockBalance.organization_id == organization.id,
                StockBalance.branch_id == transfer.destination_branch_id,
                StockBalance.item_id == line.item_id,
            )
            .with_for_update()
        )
        if destination_balance is None:
            destination_balance = StockBalance(
                id=str(uuid4()),
                organization_id=organization.id,
                branch_id=transfer.destination_branch_id,
                item_id=line.item_id,
                quantity_on_hand=Decimal("0"),
                version=1,
            )
            session.add(destination_balance)
        destination_balance.quantity_on_hand += line.quantity
        destination_balance.version += 1
        destination_batch_id = None
        if line.batch_id:
            source_batch = await session.scalar(
                select(InventoryBatch).where(
                    InventoryBatch.id == line.batch_id,
                    InventoryBatch.organization_id == organization.id,
                )
            )
            if source_batch is None:
                raise HTTPException(status_code=409, detail="Source batch no longer exists")
            destination_batch = await session.scalar(
                select(InventoryBatch).where(
                    InventoryBatch.organization_id == organization.id,
                    InventoryBatch.branch_id == transfer.destination_branch_id,
                    InventoryBatch.item_id == line.item_id,
                    InventoryBatch.lot_code == source_batch.lot_code,
                )
            )
            if destination_batch is not None and destination_batch.status != "active":
                raise HTTPException(
                    status_code=409,
                    detail="A non-active batch with this lot code already exists at destination",
                )
            if destination_batch is None:
                destination_batch = InventoryBatch(
                    id=str(uuid4()),
                    organization_id=organization.id,
                    item_id=line.item_id,
                    branch_id=transfer.destination_branch_id,
                    lot_code=source_batch.lot_code,
                    manufactured_date=source_batch.manufactured_date,
                    expiry_date=source_batch.expiry_date,
                    supplier_reference=source_batch.supplier_reference,
                    status=source_batch.status,
                )
                session.add(destination_batch)
                await session.flush()
            destination_batch_id = destination_batch.id
            line.destination_batch_id = destination_batch_id
            destination_batch_balance = await session.scalar(
                select(BatchStockBalance)
                .where(
                    BatchStockBalance.organization_id == organization.id,
                    BatchStockBalance.branch_id == transfer.destination_branch_id,
                    BatchStockBalance.item_id == line.item_id,
                    BatchStockBalance.batch_id == destination_batch_id,
                )
                .with_for_update()
            )
            if destination_batch_balance is None:
                destination_batch_balance = BatchStockBalance(
                    id=str(uuid4()),
                    organization_id=organization.id,
                    branch_id=transfer.destination_branch_id,
                    item_id=line.item_id,
                    batch_id=destination_batch_id,
                    quantity_on_hand=Decimal("0"),
                )
                session.add(destination_batch_balance)
            destination_batch_balance.quantity_on_hand += line.quantity
        source_movement = await session.scalar(
            select(StockMovement).where(
                StockMovement.organization_id == organization.id,
                StockMovement.source_type == "stock_transfer",
                StockMovement.source_id == transfer.id,
                StockMovement.idempotency_key == f"transfer:{transfer.id}:dispatch:{line.id}",
            )
        )
        if source_movement is None:
            raise HTTPException(status_code=409, detail="Transfer dispatch ledger entry is missing")
        source_allocations = list(
            (
                await session.scalars(
                    select(InventoryCostAllocation)
                    .where(InventoryCostAllocation.stock_movement_id == source_movement.id)
                    .order_by(InventoryCostAllocation.id)
                )
            ).all()
        )
        for allocation in source_allocations:
            source_layer = await session.get(InventoryCostLayer, allocation.cost_layer_id)
            if source_layer is None:
                raise HTTPException(status_code=409, detail="Transfer source cost layer is missing")
            session.add(
                InventoryCostLayer(
                    organization_id=organization.id,
                    branch_id=transfer.destination_branch_id,
                    item_id=line.item_id,
                    batch_id=destination_batch_id,
                    goods_receipt_line_id=None,
                    purchase_order_line_id=None,
                    source_transfer_line_id=line.id,
                    source_cost_layer_id=source_layer.id,
                    received_quantity=allocation.quantity,
                    remaining_quantity=allocation.quantity,
                    unit_code=source_layer.unit_code,
                    unit_cost=allocation.unit_cost,
                    currency=allocation.currency,
                )
            )
        session.add(
            StockMovement(
                id=str(uuid4()),
                organization_id=organization.id,
                branch_id=transfer.destination_branch_id,
                item_id=line.item_id,
                batch_id=destination_batch_id,
                quantity_delta=line.quantity,
                unit_code=line.unit_code,
                source_type="stock_transfer",
                source_id=transfer.id,
                reason=f"Transfer {transfer.reference} received",
                idempotency_key=f"transfer:{transfer.id}:receive:{line.id}",
                actor_user_id=user.id,
            )
        )
    transfer.status = "received"
    transfer.received_by_user_id = user.id
    transfer.received_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(transfer, attribute_names=["lines"])
    return _read(transfer)
