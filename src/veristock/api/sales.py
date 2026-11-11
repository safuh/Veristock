# ruff: noqa: E501
"""Tenant-scoped sale posting and stock ledger operations."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from veristock.identity.authorization import Organization
from veristock.identity.authorization_dependencies import (
    get_current_user,
    get_db_session,
    require_permission,
)
from veristock.identity.models import User
from veristock.inventory.models import (
    InventoryItem,
    Sale,
    SaleLine,
    StockBalance,
    StockMovement,
)
from veristock.organizations.models import Branch

router = APIRouter(tags=["sales"])
SalesRecorder = Annotated[Organization, Depends(require_permission("sales.record"))]
InventoryManager = Annotated[Organization, Depends(require_permission("inventory.manage"))]


class SaleLineCreate(BaseModel):
    item_id: str
    quantity: Decimal = Field(gt=0, max_digits=18, decimal_places=4)
    unit_code: str = Field(min_length=1, max_length=24)
    unit_price: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=4)
    currency: str | None = Field(default=None, min_length=3, max_length=3)

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str | None) -> str | None:
        return value.upper() if value else None


class SaleCreate(BaseModel):
    branch_id: str
    idempotency_key: str = Field(min_length=8, max_length=128)
    reference: str | None = Field(default=None, max_length=80)
    lines: list[SaleLineCreate] = Field(min_length=1, max_length=250)


class SaleLineRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    item_id: str
    quantity: Decimal
    unit_code: str
    unit_price: Decimal | None
    currency: str | None


class SaleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    branch_id: str
    reference: str | None
    status: str
    posted_at: datetime
    lines: list[SaleLineRead]


class InventoryItemCreate(BaseModel):
    sku: str | None = Field(default=None, max_length=80)
    barcode: str | None = Field(default=None, max_length=128)
    name: str = Field(min_length=2, max_length=240)
    description: str | None = Field(default=None, max_length=1000)
    base_unit_code: str = Field(min_length=1, max_length=24)

    @field_validator("sku", "barcode", "base_unit_code")
    @classmethod
    def normalize_codes(cls, value: str | None) -> str | None:
        return value.strip().upper() if value is not None else None


class InventoryItemCreateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    sku: str | None
    barcode: str | None
    name: str
    description: str | None
    base_unit_code: str
    status: str


class OpeningBalanceCreate(BaseModel):
    branch_id: str
    item_id: str
    quantity: Decimal = Field(gt=0, max_digits=18, decimal_places=4)
    idempotency_key: str = Field(min_length=8, max_length=128)


class OpeningBalanceRead(BaseModel):
    branch_id: str
    item_id: str
    quantity_on_hand: Decimal
    unit_code: str


@router.post("/inventory/items", response_model=InventoryItemCreateRead, status_code=201)
async def create_inventory_item(
    payload: InventoryItemCreate,
    organization: InventoryManager,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> InventoryItem:
    item = InventoryItem(
        id=str(uuid4()),
        organization_id=organization.id,
        name=payload.name.strip(),
        **payload.model_dump(exclude={"name"}),
    )
    session.add(item)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="SKU or barcode already exists") from exc
    await session.refresh(item)
    return item


@router.post("/inventory/opening-balances", response_model=OpeningBalanceRead, status_code=201)
async def record_opening_balance(
    payload: OpeningBalanceCreate,
    organization: InventoryManager,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> OpeningBalanceRead:
    existing = await session.scalar(
        select(StockMovement).where(
            StockMovement.organization_id == organization.id,
            StockMovement.idempotency_key == payload.idempotency_key,
        )
    )
    if existing is not None:
        if (
            existing.source_type != "opening_balance"
            or existing.branch_id != payload.branch_id
            or existing.item_id != payload.item_id
            or existing.quantity_delta != payload.quantity
        ):
            raise HTTPException(status_code=409, detail="Idempotency key was used for another operation")
        balance = await session.scalar(
            select(StockBalance).where(
                StockBalance.organization_id == organization.id,
                StockBalance.branch_id == payload.branch_id,
                StockBalance.item_id == payload.item_id,
            )
        )
        item = await session.get(InventoryItem, payload.item_id)
        if balance is None or item is None:
            raise HTTPException(status_code=409, detail="Original balance is no longer available")
        return OpeningBalanceRead(
            branch_id=balance.branch_id,
            item_id=balance.item_id,
            quantity_on_hand=balance.quantity_on_hand,
            unit_code=item.base_unit_code,
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
        raise HTTPException(status_code=404, detail="Active branch or inventory item not found")

    balance = await session.scalar(
        select(StockBalance).where(
            StockBalance.organization_id == organization.id,
            StockBalance.branch_id == branch.id,
            StockBalance.item_id == item.id,
        ).with_for_update()
    )
    if balance is not None and balance.quantity_on_hand != 0:
        raise HTTPException(status_code=409, detail="Opening balance already exists; use an adjustment workflow")
    if balance is None:
        balance = StockBalance(
            id=str(uuid4()),
            organization_id=organization.id,
            branch_id=branch.id,
            item_id=item.id,
            quantity_on_hand=payload.quantity,
        )
        session.add(balance)
    else:
        balance.quantity_on_hand = payload.quantity
    session.add(
        StockMovement(
            id=str(uuid4()),
            organization_id=organization.id,
            branch_id=branch.id,
            item_id=item.id,
            quantity_delta=payload.quantity,
            unit_code=item.base_unit_code,
            source_type="opening_balance",
            idempotency_key=payload.idempotency_key,
            actor_user_id=user.id,
        )
    )
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Opening balance conflicts with another request") from exc
    return OpeningBalanceRead(
        branch_id=branch.id,
        item_id=item.id,
        quantity_on_hand=balance.quantity_on_hand,
        unit_code=item.base_unit_code,
    )


@router.post("/sales", response_model=SaleRead, status_code=201)
async def post_sale(
    payload: SaleCreate,
    organization: SalesRecorder,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> Sale:
    prior = await session.scalar(
        select(Sale)
        .options(selectinload(Sale.lines))
        .where(
            Sale.organization_id == organization.id,
            Sale.idempotency_key == payload.idempotency_key,
        )
    )
    if prior is not None:
        prior_lines = prior.lines
        requested = sorted(
            (line.item_id, line.quantity, line.unit_code, line.unit_price, line.currency)
            for line in payload.lines
        )
        recorded = sorted(
            (line.item_id, line.quantity, line.unit_code, line.unit_price, line.currency)
            for line in prior_lines
        )
        if prior.branch_id != payload.branch_id or prior.reference != payload.reference or requested != recorded:
            raise HTTPException(status_code=409, detail="Idempotency key was used for a different sale")
        return prior

    branch = await session.scalar(
        select(Branch).where(
            Branch.id == payload.branch_id,
            Branch.organization_id == organization.id,
            Branch.status == "active",
        )
    )
    if branch is None:
        raise HTTPException(status_code=404, detail="Active branch not found")

    sale_id = str(uuid4())
    prepared: list[tuple[SaleLineCreate, InventoryItem, StockBalance]] = []
    seen: set[str] = set()
    for line in payload.lines:
        if line.item_id in seen:
            raise HTTPException(status_code=422, detail="Each item may appear only once per sale")
        seen.add(line.item_id)
        item = await session.scalar(
            select(InventoryItem).where(
                InventoryItem.id == line.item_id,
                InventoryItem.organization_id == organization.id,
                InventoryItem.status == "active",
            )
        )
        if item is None:
            raise HTTPException(status_code=404, detail=f"Active item {line.item_id} not found")
        if line.unit_code.strip().upper() != item.base_unit_code.upper():
            raise HTTPException(status_code=422, detail=f"Unit mismatch for item {item.name}")
        if (line.unit_price is None) != (line.currency is None):
            raise HTTPException(status_code=422, detail="Unit price and currency must be supplied together")
        balance = await session.scalar(
            select(StockBalance).where(
                StockBalance.organization_id == organization.id,
                StockBalance.branch_id == branch.id,
                StockBalance.item_id == item.id,
            ).with_for_update()
        )
        if balance is None or balance.quantity_on_hand < line.quantity:
            raise HTTPException(status_code=409, detail=f"Insufficient stock for item {item.name}")
        prepared.append((line, item, balance))

    sale = Sale(
        id=sale_id,
        organization_id=organization.id,
        branch_id=branch.id,
        idempotency_key=payload.idempotency_key,
        reference=payload.reference,
        status="posted",
        recorded_by_user_id=user.id,
    )
    session.add(sale)
    for index, (line, item, balance) in enumerate(prepared):
        balance.quantity_on_hand -= line.quantity
        sale.lines.append(
            SaleLine(
                id=str(uuid4()),
                organization_id=organization.id,
                sale_id=sale_id,
                item_id=item.id,
                quantity=line.quantity,
                unit_code=item.base_unit_code,
                unit_price=line.unit_price,
                currency=line.currency,
            )
        )
        session.add(
            StockMovement(
                id=str(uuid4()),
                organization_id=organization.id,
                branch_id=branch.id,
                item_id=item.id,
                quantity_delta=-line.quantity,
                unit_code=item.base_unit_code,
                source_type="sale",
                source_id=sale_id,
                idempotency_key=f"sale:{sale_id}:{index}",
                actor_user_id=user.id,
            )
        )
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Sale conflicts with another request") from exc
    await session.refresh(sale)
    return sale


@router.get("/sales", response_model=list[SaleRead])
async def list_sales(
    organization: SalesRecorder,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    branch_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[Sale]:
    statement = select(Sale).where(Sale.organization_id == organization.id)
    if branch_id is not None:
        statement = statement.where(Sale.branch_id == branch_id)
    sales = list(
        (
            await session.scalars(
                statement.options(selectinload(Sale.lines))
                .order_by(Sale.posted_at.desc())
                .limit(limit)
                .offset(offset)
            )
        ).all()
    )
    return sales
