"""Deterministic, tenant-scoped stocktake reconciliation and approval."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from veristock.identity.authorization import Organization
from veristock.identity.authorization_dependencies import (
    get_current_user,
    get_db_session,
    require_permission,
)
from veristock.identity.models import User
from veristock.inventory.models import InventoryItem, StockBalance, StockMovement
from veristock.stocktaking.models import (
    ReconciliationApproval,
    ReconciliationLine,
    ReconciliationRun,
    Stocktake,
    StocktakeDecision,
    StocktakeObservation,
    StocktakeRound,
    StocktakeScopeItem,
)

router = APIRouter(prefix="/reconciliations", tags=["reconciliation"])
CanRun = Annotated[Organization, Depends(require_permission("reconciliation.run"))]
CanApprove = Annotated[Organization, Depends(require_permission("reconciliation.approve"))]
CanReview = Annotated[Organization, Depends(require_permission("reconciliation.review"))]


class ReconciliationLineRead(BaseModel):
    item_id: str
    item_name: str
    unit_code: str
    expected_quantity: Decimal
    physical_quantity: Decimal
    variance_quantity: Decimal
    classification: str


class ReconciliationRead(BaseModel):
    id: str
    stocktake_id: str
    round_id: str
    version: int
    status: str
    calculated_at: datetime
    total_lines: int
    shortage_lines: int
    surplus_lines: int
    matched_lines: int


class ReconciliationDetailRead(ReconciliationRead):
    lines: list[ReconciliationLineRead]


class DecisionPayload(BaseModel):
    note: str | None = Field(default=None, max_length=1000)


def _summary(run: ReconciliationRun, lines: list[ReconciliationLine]) -> ReconciliationRead:
    return ReconciliationRead(
        id=run.id,
        stocktake_id=run.stocktake_id,
        round_id=run.round_id,
        version=run.version,
        status=run.status,
        calculated_at=run.calculated_at,
        total_lines=len(lines),
        shortage_lines=sum(line.classification == "shortage" for line in lines),
        surplus_lines=sum(line.classification == "surplus" for line in lines),
        matched_lines=sum(line.classification == "matched" for line in lines),
    )


async def _detail(
    session: AsyncSession, run: ReconciliationRun, organization_id: str
) -> ReconciliationDetailRead:
    rows = (
        await session.execute(
            select(ReconciliationLine, InventoryItem)
            .join(
                InventoryItem,
                (InventoryItem.id == ReconciliationLine.item_id)
                & (InventoryItem.organization_id == organization_id),
            )
            .where(
                ReconciliationLine.run_id == run.id,
                ReconciliationLine.organization_id == organization_id,
            )
            .order_by(InventoryItem.name)
        )
    ).all()
    lines = [
        ReconciliationLineRead(
            item_id=line.item_id,
            item_name=item.name,
            unit_code=line.unit_code,
            expected_quantity=line.expected_quantity,
            physical_quantity=line.physical_quantity,
            variance_quantity=line.variance_quantity,
            classification=line.classification,
        )
        for line, item in rows
    ]
    summary = _summary(run, [line for line, _ in rows])
    return ReconciliationDetailRead(**summary.model_dump(), lines=lines)


@router.post(
    "/stocktakes/{stocktake_id}/calculate", response_model=ReconciliationDetailRead, status_code=201
)
async def calculate_reconciliation(
    stocktake_id: str,
    organization: CanRun,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ReconciliationDetailRead:
    stocktake = await session.scalar(
        select(Stocktake)
        .where(
            Stocktake.id == stocktake_id,
            Stocktake.organization_id == organization.id,
            Stocktake.status == "submitted",
        )
        .with_for_update()
    )
    if stocktake is None:
        raise HTTPException(status_code=404, detail="Submitted stocktake not found")

    round_record = await session.scalar(
        select(StocktakeRound)
        .where(
            StocktakeRound.stocktake_id == stocktake.id,
            StocktakeRound.organization_id == organization.id,
            StocktakeRound.status == "submitted",
        )
        .order_by(StocktakeRound.round_number.desc())
    )
    if round_record is None:
        raise HTTPException(status_code=409, detail="No submitted count round")

    existing_run = await session.scalar(
        select(ReconciliationRun).where(
            ReconciliationRun.stocktake_id == stocktake.id,
            ReconciliationRun.round_id == round_record.id,
            ReconciliationRun.organization_id == organization.id,
        )
    )
    if existing_run is not None:
        return await _detail(session, existing_run, organization.id)

    prior = await session.scalar(
        select(func.max(ReconciliationRun.version)).where(
            ReconciliationRun.stocktake_id == stocktake.id,
            ReconciliationRun.organization_id == organization.id,
        )
    )
    version = int(prior or 0) + 1

    rows = (
        await session.execute(
            select(StocktakeScopeItem, StocktakeObservation, InventoryItem)
            .join(
                StocktakeObservation,
                (StocktakeObservation.stocktake_id == StocktakeScopeItem.stocktake_id)
                & (StocktakeObservation.item_id == StocktakeScopeItem.item_id)
                & (StocktakeObservation.round_id == round_record.id),
            )
            .join(
                InventoryItem,
                (InventoryItem.id == StocktakeScopeItem.item_id)
                & (InventoryItem.organization_id == organization.id),
            )
            .where(
                StocktakeScopeItem.stocktake_id == stocktake.id,
                StocktakeScopeItem.organization_id == organization.id,
            )
            .order_by(InventoryItem.name)
        )
    ).all()
    expected_count = await session.scalar(
        select(func.count(StocktakeScopeItem.id)).where(
            StocktakeScopeItem.stocktake_id == stocktake.id,
            StocktakeScopeItem.organization_id == organization.id,
        )
    )
    if len(rows) != int(expected_count or 0):
        raise HTTPException(
            status_code=409, detail="Submitted round does not cover the frozen scope"
        )

    run = ReconciliationRun(
        id=str(uuid4()),
        organization_id=organization.id,
        stocktake_id=stocktake.id,
        round_id=round_record.id,
        version=version,
        status="calculated",
        calculated_by_user_id=user.id,
    )
    session.add(run)
    response_lines: list[ReconciliationLineRead] = []
    persisted_lines: list[ReconciliationLine] = []
    for scope, observation, item in rows:
        variance = observation.counted_quantity - scope.expected_quantity
        classification = "shortage" if variance < 0 else "surplus" if variance > 0 else "matched"
        line = ReconciliationLine(
            id=str(uuid4()),
            organization_id=organization.id,
            run_id=run.id,
            item_id=item.id,
            expected_quantity=scope.expected_quantity,
            physical_quantity=observation.counted_quantity,
            variance_quantity=variance,
            unit_code=scope.unit_code,
            classification=classification,
        )
        session.add(line)
        persisted_lines.append(line)
        response_lines.append(
            ReconciliationLineRead(
                item_id=item.id,
                item_name=item.name,
                unit_code=scope.unit_code,
                expected_quantity=scope.expected_quantity,
                physical_quantity=observation.counted_quantity,
                variance_quantity=variance,
                classification=classification,
            )
        )
    await session.commit()
    await session.refresh(run)
    summary = _summary(run, persisted_lines)
    return ReconciliationDetailRead(**summary.model_dump(), lines=response_lines)


@router.get("/{run_id}", response_model=ReconciliationDetailRead)
async def get_reconciliation(
    run_id: str,
    organization: CanReview,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ReconciliationDetailRead:
    run = await session.scalar(
        select(ReconciliationRun).where(
            ReconciliationRun.id == run_id,
            ReconciliationRun.organization_id == organization.id,
        )
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Reconciliation run not found")
    return await _detail(session, run, organization.id)


@router.post("/{run_id}/approve", response_model=ReconciliationRead)
async def approve_reconciliation(
    run_id: str,
    payload: DecisionPayload,
    organization: CanApprove,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ReconciliationRead:
    run = await session.scalar(
        select(ReconciliationRun)
        .where(
            ReconciliationRun.id == run_id,
            ReconciliationRun.organization_id == organization.id,
        )
        .with_for_update()
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Reconciliation run not found")
    if run.status == "approved":
        prior_lines = list(
            (
                await session.scalars(
                    select(ReconciliationLine).where(
                        ReconciliationLine.run_id == run.id,
                        ReconciliationLine.organization_id == organization.id,
                    )
                )
            ).all()
        )
        return _summary(run, prior_lines)
    if run.status != "calculated":
        raise HTTPException(status_code=409, detail="Only calculated runs can be approved")

    counter_ids = set(
        (
            await session.scalars(
                select(StocktakeObservation.counted_by_user_id).where(
                    StocktakeObservation.round_id == run.round_id,
                    StocktakeObservation.organization_id == organization.id,
                )
            )
        ).all()
    )
    if user.id in counter_ids:
        raise HTTPException(status_code=403, detail="A counter cannot approve their own count")

    lines = list(
        (
            await session.scalars(
                select(ReconciliationLine).where(
                    ReconciliationLine.run_id == run.id,
                    ReconciliationLine.organization_id == organization.id,
                )
            )
        ).all()
    )
    stocktake = await session.scalar(
        select(Stocktake).where(
            Stocktake.id == run.stocktake_id,
            Stocktake.organization_id == organization.id,
        )
    )
    if stocktake is None:
        raise HTTPException(status_code=409, detail="Stocktake no longer exists")
    if stocktake.status != "submitted":
        raise HTTPException(status_code=409, detail="Stocktake has already been approved or closed")

    scope_versions = {
        scope.item_id: scope.expected_balance_version
        for scope in (
            await session.scalars(
                select(StocktakeScopeItem).where(
                    StocktakeScopeItem.stocktake_id == stocktake.id,
                    StocktakeScopeItem.organization_id == organization.id,
                )
            )
        ).all()
    }

    for line in lines:
        balance = await session.scalar(
            select(StockBalance)
            .where(
                StockBalance.organization_id == organization.id,
                StockBalance.branch_id == stocktake.branch_id,
                StockBalance.item_id == line.item_id,
            )
            .with_for_update()
        )
        current = balance.quantity_on_hand if balance is not None else Decimal("0")
        current_version = balance.version if balance is not None else 0
        if current != line.expected_quantity or current_version != scope_versions.get(
            line.item_id, -1
        ):
            raise HTTPException(
                status_code=409,
                detail=(
                    "Stock changed after the frozen snapshot; create a new stocktake "
                    "before approval"
                ),
            )

    for line in lines:
        delta = line.variance_quantity
        if delta == 0:
            continue
        balance = await session.scalar(
            select(StockBalance)
            .where(
                StockBalance.organization_id == organization.id,
                StockBalance.branch_id == stocktake.branch_id,
                StockBalance.item_id == line.item_id,
            )
            .with_for_update()
        )
        if balance is None:
            balance = StockBalance(
                id=str(uuid4()),
                organization_id=organization.id,
                branch_id=stocktake.branch_id,
                item_id=line.item_id,
                quantity_on_hand=delta,
            )
            session.add(balance)
        else:
            balance.quantity_on_hand += delta
            balance.version += 1
        session.add(
            StockMovement(
                id=str(uuid4()),
                organization_id=organization.id,
                branch_id=stocktake.branch_id,
                item_id=line.item_id,
                quantity_delta=delta,
                unit_code=line.unit_code,
                source_type="stocktake_adjustment",
                source_id=run.id,
                idempotency_key=f"reconciliation:{run.id}:{line.item_id}",
                actor_user_id=user.id,
            )
        )

    run.status = "approved"
    run.decided_by_user_id = user.id
    run.decided_at = datetime.now(UTC)
    run.decision_note = payload.note.strip() if payload.note else None
    session.add(
        ReconciliationApproval(
            id=str(uuid4()),
            organization_id=organization.id,
            run_id=run.id,
            decision="approved",
            decided_by_user_id=user.id,
            note=run.decision_note,
        )
    )
    completed_at = datetime.now(UTC)
    stocktake.status = "completed"
    stocktake.completed_at = completed_at
    stocktake.approved_by_user_id = user.id
    session.add(
        StocktakeDecision(
            id=str(uuid4()),
            organization_id=organization.id,
            stocktake_id=stocktake.id,
            round_id=run.round_id,
            action="approved",
            actor_user_id=user.id,
            created_at=completed_at,
        )
    )
    await session.commit()
    await session.refresh(run)
    return _summary(run, lines)


@router.post("/{run_id}/reject", response_model=ReconciliationRead)
async def reject_reconciliation(
    run_id: str,
    payload: DecisionPayload,
    organization: CanApprove,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ReconciliationRead:
    run = await session.scalar(
        select(ReconciliationRun)
        .where(
            ReconciliationRun.id == run_id,
            ReconciliationRun.organization_id == organization.id,
        )
        .with_for_update()
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Reconciliation run not found")
    if run.status == "rejected":
        prior_lines = list(
            (
                await session.scalars(
                    select(ReconciliationLine).where(
                        ReconciliationLine.run_id == run.id,
                        ReconciliationLine.organization_id == organization.id,
                    )
                )
            ).all()
        )
        return _summary(run, prior_lines)
    if run.status != "calculated":
        raise HTTPException(status_code=409, detail="Only calculated runs can be rejected")

    counter_ids = set(
        (
            await session.scalars(
                select(StocktakeObservation.counted_by_user_id).where(
                    StocktakeObservation.round_id == run.round_id,
                    StocktakeObservation.organization_id == organization.id,
                )
            )
        ).all()
    )
    if user.id in counter_ids:
        raise HTTPException(status_code=403, detail="A counter cannot decide their own count")

    note = payload.note.strip() if payload.note else ""
    if len(note) < 3:
        raise HTTPException(status_code=422, detail="A reason is required to reject reconciliation")
    lines = list(
        (
            await session.scalars(
                select(ReconciliationLine).where(ReconciliationLine.run_id == run.id)
            )
        ).all()
    )
    run.status = "rejected"
    run.decided_by_user_id = user.id
    run.decided_at = datetime.now(UTC)
    run.decision_note = note
    session.add(
        ReconciliationApproval(
            id=str(uuid4()),
            organization_id=organization.id,
            run_id=run.id,
            decision="rejected",
            decided_by_user_id=user.id,
            note=note,
        )
    )
    await session.commit()
    await session.refresh(run)
    return _summary(run, lines)
