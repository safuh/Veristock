# ruff: noqa: E501
"""Tenant-scoped physical stocktake planning and blind count capture."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import case, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from veristock.identity.authorization import Organization
from veristock.identity.authorization_dependencies import (
    get_current_user,
    get_db_session,
    require_permission,
)
from veristock.identity.models import User
from veristock.inventory.models import InventoryItem, StockBalance, StockMovement
from veristock.organizations.models import Branch
from veristock.stocktaking.models import (
    Stocktake,
    StocktakeObservation,
    StocktakeRound,
    StocktakeScopeItem,
    StocktakeDecision,
)

router = APIRouter(prefix="/stocktakes", tags=["stocktaking"])
StocktakeManager = Annotated[Organization, Depends(require_permission("stocktake.manage"))]
StocktakeReader = Annotated[Organization, Depends(require_permission("stocktake.read"))]
StocktakeCounter = Annotated[Organization, Depends(require_permission("stocktake.count"))]
StocktakeSubmitter = Annotated[Organization, Depends(require_permission("stocktake.submit"))]
StocktakeApprover = Annotated[Organization, Depends(require_permission("stocktake.approve"))]


class StocktakeCreate(BaseModel):
    branch_id: str
    reference: str = Field(min_length=2, max_length=80)
    blind_count: bool = True


class StocktakeRead(BaseModel):
    id: str
    branch_id: str
    reference: str
    blind_count: bool
    status: str
    created_at: datetime
    item_count: int


class CountObservationCreate(BaseModel):
    item_id: str
    counted_quantity: Decimal = Field(ge=0, max_digits=18, decimal_places=4)
    unit_code: str = Field(min_length=1, max_length=24)
    idempotency_key: str = Field(min_length=8, max_length=128)


class CountObservationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    stocktake_id: str
    round_id: str
    item_id: str
    counted_quantity: Decimal
    unit_code: str
    counted_at: datetime


class RoundRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    stocktake_id: str
    round_number: int
    status: str
    submitted_at: datetime | None


@router.post("", response_model=StocktakeRead, status_code=201)
async def create_stocktake(
    payload: StocktakeCreate,
    organization: StocktakeManager,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> StocktakeRead:
    branch = await session.scalar(
        select(Branch).where(
            Branch.id == payload.branch_id,
            Branch.organization_id == organization.id,
            Branch.status == "active",
        )
    )
    if branch is None:
        raise HTTPException(status_code=404, detail="Active branch not found")

    stocktake_id = str(uuid4())
    stocktake = Stocktake(
        id=stocktake_id,
        organization_id=organization.id,
        branch_id=branch.id,
        reference=payload.reference.strip(),
        blind_count=payload.blind_count,
        status="open",
        created_by_user_id=user.id,
    )
    session.add(stocktake)
    items = list(
        (
            await session.scalars(
                select(InventoryItem).where(
                    InventoryItem.organization_id == organization.id,
                    InventoryItem.status == "active",
                )
            )
        ).all()
    )
    balances = {
        balance.item_id: balance.quantity_on_hand
        for balance in (
            await session.scalars(
                select(StockBalance).where(
                    StockBalance.organization_id == organization.id,
                    StockBalance.branch_id == branch.id,
                ).with_for_update()
            )
        ).all()
    }
    for item in items:
        session.add(
            StocktakeScopeItem(
                id=str(uuid4()),
                organization_id=organization.id,
                stocktake_id=stocktake_id,
                item_id=item.id,
                expected_quantity=balances.get(item.id, Decimal("0")),
                unit_code=item.base_unit_code,
            )
        )
    round_record = StocktakeRound(
        id=str(uuid4()),
        organization_id=organization.id,
        stocktake_id=stocktake_id,
        round_number=1,
        status="open",
        opened_by_user_id=user.id,
    )
    session.add(round_record)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Stocktake reference or scope conflict") from exc
    await session.refresh(stocktake)
    return StocktakeRead(
        id=stocktake.id,
        branch_id=stocktake.branch_id,
        reference=stocktake.reference,
        blind_count=stocktake.blind_count,
        status=stocktake.status,
        created_at=stocktake.created_at,
        item_count=len(items),
    )


@router.get("", response_model=list[StocktakeRead])
async def list_stocktakes(
    organization: StocktakeReader,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    branch_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[StocktakeRead]:
    statement = select(Stocktake).where(Stocktake.organization_id == organization.id)
    if branch_id is not None:
        statement = statement.where(Stocktake.branch_id == branch_id)
    records = list(
        (
            await session.scalars(
                statement.order_by(Stocktake.created_at.desc()).limit(limit).offset(offset)
            )
        ).all()
    )
    results = []
    for record in records:
        count = await session.scalar(
            select(func.count(StocktakeScopeItem.id)).where(
                StocktakeScopeItem.stocktake_id == record.id
            )
        )
        results.append(
            StocktakeRead(
                id=record.id,
                branch_id=record.branch_id,
                reference=record.reference,
                blind_count=record.blind_count,
                status=record.status,
                created_at=record.created_at,
                item_count=int(count or 0),
            )
        )
    return results


@router.get("/{stocktake_id}/scope", response_model=list[dict[str, str]])
async def list_stocktake_scope(
    stocktake_id: str,
    organization: StocktakeReader,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> list[dict[str, str]]:
    stocktake = await session.scalar(
        select(Stocktake).where(
            Stocktake.id == stocktake_id,
            Stocktake.organization_id == organization.id,
        )
    )
    if stocktake is None:
        raise HTTPException(status_code=404, detail="Stocktake not found")
    rows = (
        await session.execute(
            select(StocktakeScopeItem, InventoryItem)
            .join(InventoryItem, InventoryItem.id == StocktakeScopeItem.item_id)
            .where(StocktakeScopeItem.stocktake_id == stocktake.id)
            .order_by(InventoryItem.name)
        )
    ).all()
    # Blind-count callers never receive expected quantities through this endpoint.
    return [
        {
            "item_id": item.id,
            "sku": item.sku or "",
            "barcode": item.barcode or "",
            "name": item.name,
            "unit_code": scope.unit_code,
            **(
                {"expected_quantity": str(scope.expected_quantity)}
                if not stocktake.blind_count
                else {}
            ),
        }
        for scope, item in rows
    ]


@router.post("/{stocktake_id}/observations", response_model=CountObservationRead, status_code=201)
async def record_count_observation(
    stocktake_id: str,
    payload: CountObservationCreate,
    organization: StocktakeCounter,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> StocktakeObservation:
    duplicate = await session.scalar(
        select(StocktakeObservation).where(
            StocktakeObservation.organization_id == organization.id,
            StocktakeObservation.idempotency_key == payload.idempotency_key,
        )
    )
    if duplicate is not None:
        if (
            duplicate.stocktake_id != stocktake_id
            or duplicate.item_id != payload.item_id
            or duplicate.counted_quantity != payload.counted_quantity
            or duplicate.unit_code != payload.unit_code
        ):
            raise HTTPException(status_code=409, detail="Idempotency key was used for another count")
        return duplicate

    stocktake = await session.scalar(
        select(Stocktake).where(
            Stocktake.id == stocktake_id,
            Stocktake.organization_id == organization.id,
            Stocktake.status == "open",
        )
    )
    if stocktake is None:
        raise HTTPException(status_code=404, detail="Open stocktake not found")
    round_record = await session.scalar(
        select(StocktakeRound).where(
            StocktakeRound.stocktake_id == stocktake.id,
            StocktakeRound.organization_id == organization.id,
            StocktakeRound.status == "open",
        ).order_by(StocktakeRound.round_number.desc())
    )
    if round_record is None:
        raise HTTPException(status_code=409, detail="No open count round")
    scope = await session.scalar(
        select(StocktakeScopeItem).where(
            StocktakeScopeItem.stocktake_id == stocktake.id,
            StocktakeScopeItem.item_id == payload.item_id,
            StocktakeScopeItem.organization_id == organization.id,
        )
    )
    if scope is None:
        raise HTTPException(status_code=404, detail="Item is outside this stocktake scope")
    if payload.unit_code.strip().upper() != scope.unit_code.upper():
        raise HTTPException(status_code=422, detail="Count unit does not match the frozen item unit")
    observation = StocktakeObservation(
        id=str(uuid4()),
        organization_id=organization.id,
        stocktake_id=stocktake.id,
        round_id=round_record.id,
        item_id=payload.item_id,
        counted_quantity=payload.counted_quantity,
        unit_code=scope.unit_code,
        idempotency_key=payload.idempotency_key,
        counted_by_user_id=user.id,
    )
    session.add(observation)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="This item already has a count in the active round") from exc
    await session.refresh(observation)
    return observation


@router.post("/{stocktake_id}/submit", response_model=RoundRead)
async def submit_count_round(
    stocktake_id: str,
    organization: StocktakeSubmitter,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> StocktakeRound:
    stocktake = await session.scalar(
        select(Stocktake).where(
            Stocktake.id == stocktake_id,
            Stocktake.organization_id == organization.id,
            Stocktake.status == "open",
        )
    )
    if stocktake is None:
        raise HTTPException(status_code=404, detail="Open stocktake not found")
    round_record = await session.scalar(
        select(StocktakeRound).where(
            StocktakeRound.stocktake_id == stocktake.id,
            StocktakeRound.status == "open",
        ).order_by(StocktakeRound.round_number.desc())
    )
    if round_record is None:
        raise HTTPException(status_code=409, detail="No open count round")
    expected_count = await session.scalar(
        select(func.count(StocktakeScopeItem.id)).where(
            StocktakeScopeItem.stocktake_id == stocktake.id
        )
    )
    observed_count = await session.scalar(
        select(func.count(StocktakeObservation.id)).where(
            StocktakeObservation.round_id == round_record.id
        )
    )
    if observed_count != expected_count:
        raise HTTPException(
            status_code=409,
            detail=f"Count incomplete: {observed_count or 0} of {expected_count or 0} items recorded",
        )
    round_record.status = "submitted"
    round_record.submitted_at = datetime.now(UTC)
    stocktake.status = "submitted"
    stocktake.submitted_at = round_record.submitted_at
    await session.commit()
    await session.refresh(round_record)
    return round_record


StocktakeRecountReasonCode = Literal[
    "count_discrepancy",
    "damaged_stock",
    "unit_mismatch",
    "suspected_loss",
    "counting_error",
    "other",
]


class StocktakeRecountRequest(BaseModel):
    reason_code: StocktakeRecountReasonCode
    reason: str = Field(min_length=10, max_length=500)


class StocktakeDecisionRead(BaseModel):
    id: str
    stocktake_id: str
    round_id: str
    action: str
    reason_code: str | None
    reason: str | None
    actor_user_id: str
    created_at: datetime


@router.post("/{stocktake_id}/recount", response_model=RoundRead, status_code=201)
async def open_recount_round(
    stocktake_id: str,
    payload: StocktakeRecountRequest,
    organization: StocktakeManager,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> StocktakeRound:
    stocktake = await session.scalar(
        select(Stocktake).where(
            Stocktake.id == stocktake_id,
            Stocktake.organization_id == organization.id,
            Stocktake.status == "submitted",
        )
    )
    if stocktake is None:
        raise HTTPException(status_code=404, detail="Submitted stocktake not found")
    latest = await session.scalar(
        select(StocktakeRound).where(
            StocktakeRound.stocktake_id == stocktake.id
        ).order_by(StocktakeRound.round_number.desc())
    )
    if latest is None or latest.status != "submitted":
        raise HTTPException(status_code=409, detail="Previous count round must be submitted")
    decision = StocktakeDecision(
        id=str(uuid4()),
        organization_id=organization.id,
        stocktake_id=stocktake.id,
        round_id=latest.id,
        action="recount_requested",
        reason_code=payload.reason_code,
        reason=payload.reason.strip(),
        actor_user_id=user.id,
    )
    new_round = StocktakeRound(
        id=str(uuid4()),
        organization_id=organization.id,
        stocktake_id=stocktake.id,
        round_number=latest.round_number + 1,
        status="open",
        opened_by_user_id=user.id,
    )
    stocktake.status = "open"
    session.add_all([decision, new_round])
    await session.commit()
    await session.refresh(new_round)
    return new_round


class StocktakeReviewQueueItem(BaseModel):
    """Submitted stocktake awaiting an independent supervisor decision."""

    stocktake_id: str
    reference: str
    branch_id: str
    branch_name: str
    submitted_at: datetime | None
    round_number: int
    item_count: int
    variance_count: int
    shortage_count: int
    surplus_count: int


@router.get(
    "/{stocktake_id}/decisions",
    response_model=list[StocktakeDecisionRead],
)
async def list_stocktake_decisions(
    stocktake_id: str,
    organization: StocktakeReader,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> list[StocktakeDecisionRead]:
    """Return the tenant-scoped, chronological stocktake decision history."""
    stocktake = await session.scalar(
        select(Stocktake.id).where(
            Stocktake.id == stocktake_id,
            Stocktake.organization_id == organization.id,
        )
    )
    if stocktake is None:
        raise HTTPException(status_code=404, detail="Stocktake not found")
    records = (
        await session.scalars(
            select(StocktakeDecision)
            .where(
                StocktakeDecision.organization_id == organization.id,
                StocktakeDecision.stocktake_id == stocktake_id,
            )
            .order_by(StocktakeDecision.created_at, StocktakeDecision.id)
        )
    ).all()
    return [
        StocktakeDecisionRead(
            id=record.id,
            stocktake_id=record.stocktake_id,
            round_id=record.round_id,
            action=record.action,
            reason_code=record.reason_code,
            reason=record.reason,
            actor_user_id=record.actor_user_id,
            created_at=record.created_at,
        )
        for record in records
    ]


@router.get("/review-queue", response_model=list[StocktakeReviewQueueItem])
async def list_stocktake_review_queue(
    organization: StocktakeApprover,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    branch_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[StocktakeReviewQueueItem]:
    """List this tenant's submitted stocktakes for independent approval."""
    statement = (
        select(Stocktake, Branch)
        .join(
            Branch,
            (Branch.id == Stocktake.branch_id)
            & (Branch.organization_id == organization.id),
        )
        .where(
            Stocktake.organization_id == organization.id,
            Stocktake.status == "submitted",
        )
    )
    if branch_id is not None:
        statement = statement.where(Stocktake.branch_id == branch_id)
    records = (
        await session.execute(
            statement.order_by(Stocktake.submitted_at.asc(), Stocktake.created_at.asc())
            .limit(limit)
            .offset(offset)
        )
    ).all()

    queue = []
    for stocktake, branch in records:
        round_record = await session.scalar(
            select(StocktakeRound)
            .where(
                StocktakeRound.organization_id == organization.id,
                StocktakeRound.stocktake_id == stocktake.id,
                StocktakeRound.status == "submitted",
            )
            .order_by(StocktakeRound.round_number.desc())
        )
        if round_record is None:
            continue
        counts = (
            await session.execute(
                select(
                    func.count(StocktakeObservation.id),
                    func.coalesce(
                        func.sum(
                            case(
                                (
                                    StocktakeObservation.counted_quantity
                                    < StocktakeScopeItem.expected_quantity,
                                    1,
                                ),
                                else_=0,
                            )
                        ),
                        0,
                    ),
                    func.coalesce(
                        func.sum(
                            case(
                                (
                                    StocktakeObservation.counted_quantity
                                    > StocktakeScopeItem.expected_quantity,
                                    1,
                                ),
                                else_=0,
                            )
                        ),
                        0,
                    ),
                )
                .join(
                    StocktakeScopeItem,
                    (StocktakeScopeItem.stocktake_id == StocktakeObservation.stocktake_id)
                    & (StocktakeScopeItem.item_id == StocktakeObservation.item_id)
                    & (StocktakeScopeItem.organization_id == organization.id),
                )
                .where(
                    StocktakeObservation.organization_id == organization.id,
                    StocktakeObservation.stocktake_id == stocktake.id,
                    StocktakeObservation.round_id == round_record.id,
                )
            )
        ).one()
        item_count, shortage_count, surplus_count = (int(value or 0) for value in counts)
        queue.append(
            StocktakeReviewQueueItem(
                stocktake_id=stocktake.id,
                reference=stocktake.reference,
                branch_id=branch.id,
                branch_name=branch.name,
                submitted_at=round_record.submitted_at,
                round_number=round_record.round_number,
                item_count=item_count,
                variance_count=shortage_count + surplus_count,
                shortage_count=shortage_count,
                surplus_count=surplus_count,
            )
        )
    return queue


class StocktakeReconciliationLine(BaseModel):
    """Read-only variance detail for one item in the latest submitted count."""

    item_id: str
    sku: str
    item_name: str
    unit_code: str
    expected_quantity: Decimal
    counted_quantity: Decimal
    variance_quantity: Decimal
    variance_status: str
    post_count_movement_delta: Decimal
    reconciled_quantity: Decimal
    current_quantity: Decimal


class StocktakeReconciliationRead(BaseModel):
    stocktake_id: str
    status: str
    round_number: int
    submitted_at: datetime | None
    lines: list[StocktakeReconciliationLine]


@router.get("/{stocktake_id}/reconciliation", response_model=StocktakeReconciliationRead)
async def get_stocktake_reconciliation(
    stocktake_id: str,
    organization: StocktakeReader,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> StocktakeReconciliationRead:
    """Return frozen-snapshot variance and post-count movement context.

    This endpoint is read-only. It never changes stock balances or ledger rows.
    """
    stocktake = await session.scalar(
        select(Stocktake).where(
            Stocktake.id == stocktake_id,
            Stocktake.organization_id == organization.id,
            Stocktake.status.in_(( "submitted", "completed")),
        )
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
        raise HTTPException(status_code=409, detail="No submitted count round to reconcile")

    rows = (
        await session.execute(
            select(StocktakeObservation, StocktakeScopeItem, InventoryItem)
            .join(
                StocktakeScopeItem,
                (StocktakeScopeItem.stocktake_id == StocktakeObservation.stocktake_id)
                & (StocktakeScopeItem.item_id == StocktakeObservation.item_id)
                & (StocktakeScopeItem.organization_id == organization.id),
            )
            .join(InventoryItem, InventoryItem.id == StocktakeObservation.item_id)
            .where(
                StocktakeObservation.organization_id == organization.id,
                StocktakeObservation.stocktake_id == stocktake.id,
                StocktakeObservation.round_id == round_record.id,
            )
            .order_by(InventoryItem.name)
        )
    ).all()

    lines = []
    for observation, scope, item in rows:
        later_movements = await session.scalar(
            select(func.coalesce(func.sum(StockMovement.quantity_delta), 0)).where(
                StockMovement.organization_id == organization.id,
                StockMovement.branch_id == stocktake.branch_id,
                StockMovement.item_id == observation.item_id,
                StockMovement.occurred_at > observation.counted_at,
            )
        )
        post_count_delta = Decimal(later_movements or 0)
        variance = observation.counted_quantity - scope.expected_quantity
        current_balance = await session.scalar(
            select(StockBalance).where(
                StockBalance.organization_id == organization.id,
                StockBalance.branch_id == stocktake.branch_id,
                StockBalance.item_id == observation.item_id,
            )
        )
        current_quantity = (
            current_balance.quantity_on_hand
            if current_balance is not None
            else Decimal("0")
        )
        lines.append(
            StocktakeReconciliationLine(
                item_id=item.id,
                sku=item.sku or "",
                item_name=item.name,
                unit_code=scope.unit_code,
                expected_quantity=scope.expected_quantity,
                counted_quantity=observation.counted_quantity,
                variance_quantity=variance,
                variance_status=(
                    "shortage" if variance < 0 else "surplus" if variance > 0 else "match"
                ),
                post_count_movement_delta=post_count_delta,
                reconciled_quantity=observation.counted_quantity + post_count_delta,
                current_quantity=current_quantity,
            )
        )

    expected_count = await session.scalar(
        select(func.count(StocktakeScopeItem.id)).where(
            StocktakeScopeItem.organization_id == organization.id,
            StocktakeScopeItem.stocktake_id == stocktake.id,
        )
    )
    if len(lines) != int(expected_count or 0):
        raise HTTPException(status_code=409, detail="Latest count round is incomplete")

    return StocktakeReconciliationRead(
        stocktake_id=stocktake.id,
        status=stocktake.status,
        round_number=round_record.round_number,
        submitted_at=round_record.submitted_at,
        lines=lines,
    )


class StocktakeApprovalRead(BaseModel):
    """Result of applying an approved physical count to the stock ledger."""

    stocktake_id: str
    status: str
    adjustment_count: int
    total_quantity_delta: Decimal
    completed_at: datetime


@router.post("/{stocktake_id}/approve", response_model=StocktakeApprovalRead)
async def approve_stocktake(
    stocktake_id: str,
    organization: StocktakeApprover,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> StocktakeApprovalRead:
    """Approve the latest submitted count and reconcile stock atomically.

    Movements posted after an observation are carried forward so sales and
    adjustments made while counting are not overwritten by the physical count.
    """
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
        raise HTTPException(status_code=409, detail="Submitted stocktake not found or already approved")

    round_record = await session.scalar(
        select(StocktakeRound).where(
            StocktakeRound.stocktake_id == stocktake.id,
            StocktakeRound.organization_id == organization.id,
            StocktakeRound.status == "submitted",
        ).order_by(StocktakeRound.round_number.desc())
    )
    if round_record is None:
        raise HTTPException(status_code=409, detail="No submitted count round to approve")

    counter_user_ids = set(
        (
            await session.scalars(
                select(StocktakeObservation.counted_by_user_id)
                .where(StocktakeObservation.round_id == round_record.id)
                .distinct()
            )
        ).all()
    )
    if user.id in counter_user_ids:
        raise HTTPException(
            status_code=409,
            detail="A user who counted this round cannot approve it",
        )

    rows = (
        await session.execute(
            select(StocktakeObservation, StocktakeScopeItem)
            .join(
                StocktakeScopeItem,
                (StocktakeScopeItem.stocktake_id == StocktakeObservation.stocktake_id)
                & (StocktakeScopeItem.item_id == StocktakeObservation.item_id)
                & (StocktakeScopeItem.organization_id == organization.id),
            )
            .where(
                StocktakeObservation.organization_id == organization.id,
                StocktakeObservation.stocktake_id == stocktake.id,
                StocktakeObservation.round_id == round_record.id,
            )
            .order_by(StocktakeObservation.item_id)
        )
    ).all()
    expected_count = await session.scalar(
        select(func.count(StocktakeScopeItem.id)).where(
            StocktakeScopeItem.organization_id == organization.id,
            StocktakeScopeItem.stocktake_id == stocktake.id,
        )
    )
    if len(rows) != int(expected_count or 0):
        raise HTTPException(status_code=409, detail="Latest count round is incomplete")

    adjustment_count = 0
    total_delta = Decimal("0")
    try:
        for observation, _scope in rows:
            balance = await session.scalar(
                select(StockBalance)
                .where(
                    StockBalance.organization_id == organization.id,
                    StockBalance.branch_id == stocktake.branch_id,
                    StockBalance.item_id == observation.item_id,
                )
                .with_for_update()
            )
            current_quantity = (
                balance.quantity_on_hand if balance is not None else Decimal("0")
            )
            later_movements = await session.scalar(
                select(func.coalesce(func.sum(StockMovement.quantity_delta), 0)).where(
                    StockMovement.organization_id == organization.id,
                    StockMovement.branch_id == stocktake.branch_id,
                    StockMovement.item_id == observation.item_id,
                    StockMovement.occurred_at > observation.counted_at,
                )
            )
            target_quantity = observation.counted_quantity + Decimal(later_movements or 0)
            if target_quantity < 0:
                raise HTTPException(
                    status_code=409,
                    detail="Post-count movements produce a negative reconciled balance",
                )
            quantity_delta = target_quantity - current_quantity
            if quantity_delta == 0:
                continue
            if balance is None:
                balance = StockBalance(
                    id=str(uuid4()),
                    organization_id=organization.id,
                    branch_id=stocktake.branch_id,
                    item_id=observation.item_id,
                    quantity_on_hand=target_quantity,
                )
                session.add(balance)
            else:
                balance.quantity_on_hand = target_quantity
            session.add(
                StockMovement(
                    id=str(uuid4()),
                    organization_id=organization.id,
                    branch_id=stocktake.branch_id,
                    item_id=observation.item_id,
                    quantity_delta=quantity_delta,
                    unit_code=observation.unit_code,
                    source_type="stocktake_adjustment",
                    source_id=stocktake.id,
                    idempotency_key=(
                        f"stocktake:{stocktake.id}:{round_record.id}:{observation.item_id}"
                    ),
                    actor_user_id=user.id,
                )
            )
            adjustment_count += 1
            total_delta += quantity_delta

        completed_at = datetime.now(UTC)
        session.add(
            StocktakeDecision(
                id=str(uuid4()),
                organization_id=organization.id,
                stocktake_id=stocktake.id,
                round_id=round_record.id,
                action="approved",
                actor_user_id=user.id,
            )
        )
        stocktake.status = "completed"
        stocktake.completed_at = completed_at
        stocktake.approved_by_user_id = user.id
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Stocktake reconciliation conflicted with another operation") from exc
    except HTTPException:
        await session.rollback()
        raise

    return StocktakeApprovalRead(
        stocktake_id=stocktake.id,
        status=stocktake.status,
        adjustment_count=adjustment_count,
        total_quantity_delta=total_delta,
        completed_at=completed_at,
    )
