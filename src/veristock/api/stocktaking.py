# ruff: noqa: E501
"""Tenant-scoped physical stocktake planning and blind count capture."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from veristock.identity.authorization import Organization
from veristock.identity.authorization_dependencies import (
    get_current_user,
    get_db_session,
    require_permission,
)
from veristock.identity.models import User
from veristock.inventory.models import InventoryItem, StockBalance
from veristock.organizations.models import Branch
from veristock.stocktaking.models import (
    Stocktake,
    StocktakeObservation,
    StocktakeRound,
    StocktakeScopeItem,
)

router = APIRouter(prefix="/stocktakes", tags=["stocktaking"])
StocktakeManager = Annotated[Organization, Depends(require_permission("stocktake.manage"))]
StocktakeReader = Annotated[Organization, Depends(require_permission("stocktake.read"))]
StocktakeCounter = Annotated[Organization, Depends(require_permission("stocktake.count"))]


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
    organization: StocktakeManager,
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


@router.post("/{stocktake_id}/recount", response_model=RoundRead, status_code=201)
async def open_recount_round(
    stocktake_id: str,
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
    new_round = StocktakeRound(
        id=str(uuid4()),
        organization_id=organization.id,
        stocktake_id=stocktake.id,
        round_number=latest.round_number + 1,
        status="open",
        opened_by_user_id=user.id,
    )
    stocktake.status = "open"
    session.add(new_round)
    await session.commit()
    await session.refresh(new_round)
    return new_round
