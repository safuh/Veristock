"""Tenant-scoped supplier directory and supplier item catalogue."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from veristock.identity.authorization import Organization
from veristock.identity.authorization_dependencies import get_db_session, require_permission
from veristock.inventory.models import InventoryItem, Supplier, SupplierItem

router = APIRouter(prefix="/suppliers", tags=["suppliers"])
SupplierManager = Annotated[Organization, Depends(require_permission("inventory.manage"))]
SupplierReader = Annotated[Organization, Depends(require_permission("inventory.read"))]


class SupplierWrite(BaseModel):
    code: str = Field(min_length=2, max_length=40, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    name: str = Field(min_length=2, max_length=240)
    contact_name: str | None = Field(default=None, max_length=160)
    email: str | None = Field(default=None, max_length=254)
    phone: str | None = Field(default=None, max_length=40)
    website: str | None = Field(default=None, max_length=300)
    address: str | None = Field(default=None, max_length=1000)
    tax_reference: str | None = Field(default=None, max_length=100)
    payment_terms: str | None = Field(default=None, max_length=240)
    default_currency: str = Field(default="KES", min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")
    notes: str | None = Field(default=None, max_length=1000)
    status: str = Field(default="active", pattern=r"^(active|inactive|blocked)$")


class SupplierRead(SupplierWrite):
    model_config = ConfigDict(from_attributes=True)
    id: str
    created_at: datetime
    updated_at: datetime


class SupplierItemWrite(BaseModel):
    supplier_sku: str | None = Field(default=None, max_length=100)
    unit_cost: Decimal = Field(ge=0, max_digits=18, decimal_places=4)
    currency: str = Field(default="KES", min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")
    minimum_order_quantity: Decimal = Field(
        default=Decimal("1"), gt=0, max_digits=18, decimal_places=4
    )
    lead_time_days: int = Field(default=0, ge=0, le=3650)
    is_preferred: bool = False
    is_active: bool = True


class SupplierItemRead(SupplierItemWrite):
    model_config = ConfigDict(from_attributes=True)
    id: str
    supplier_id: str
    item_id: str
    updated_at: datetime


@router.post("", response_model=SupplierRead, status_code=201)
async def create_supplier(
    payload: SupplierWrite,
    organization: SupplierManager,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> Supplier:
    code = payload.code.strip().upper()
    prior = await session.scalar(
        select(Supplier.id).where(
            Supplier.organization_id == organization.id, Supplier.code == code
        )
    )
    if prior:
        raise HTTPException(status_code=409, detail="Supplier code already exists")
    values = payload.model_dump()
    values.update(code=code, name=payload.name.strip())
    supplier = Supplier(id=str(uuid4()), organization_id=organization.id, **values)
    session.add(supplier)
    await session.commit()
    await session.refresh(supplier)
    return supplier


@router.get("", response_model=list[SupplierRead])
async def list_suppliers(
    organization: SupplierReader,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    status: str | None = None,
) -> list[Supplier]:
    query = select(Supplier).where(Supplier.organization_id == organization.id)
    if status is not None:
        if status not in {"active", "inactive", "blocked"}:
            raise HTTPException(status_code=422, detail="Invalid supplier status")
        query = query.where(Supplier.status == status)
    return list((await session.scalars(query.order_by(Supplier.name))).all())


@router.get("/{supplier_id}", response_model=SupplierRead)
async def get_supplier(
    supplier_id: str,
    organization: SupplierReader,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> Supplier:
    supplier = await session.scalar(
        select(Supplier).where(
            Supplier.id == supplier_id, Supplier.organization_id == organization.id
        )
    )
    if supplier is None:
        raise HTTPException(status_code=404, detail="Supplier not found")
    return supplier


@router.patch("/{supplier_id}", response_model=SupplierRead)
async def update_supplier(
    supplier_id: str,
    payload: SupplierWrite,
    organization: SupplierManager,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> Supplier:
    supplier = await session.scalar(
        select(Supplier).where(
            Supplier.id == supplier_id, Supplier.organization_id == organization.id
        )
    )
    if supplier is None:
        raise HTTPException(status_code=404, detail="Supplier not found")
    code = payload.code.strip().upper()
    duplicate = await session.scalar(
        select(Supplier.id).where(
            Supplier.organization_id == organization.id,
            Supplier.code == code,
            Supplier.id != supplier.id,
        )
    )
    if duplicate:
        raise HTTPException(status_code=409, detail="Supplier code already exists")
    for key, value in payload.model_dump().items():
        setattr(
            supplier,
            key,
            value.strip() if isinstance(value, str) and key in {"name", "code"} else value,
        )
    supplier.code = code
    await session.commit()
    await session.refresh(supplier)
    return supplier


@router.put("/{supplier_id}/items/{item_id}", response_model=SupplierItemRead)
async def upsert_supplier_item(
    supplier_id: str,
    item_id: str,
    payload: SupplierItemWrite,
    organization: SupplierManager,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> SupplierItem:
    supplier = await session.scalar(
        select(Supplier).where(
            Supplier.id == supplier_id, Supplier.organization_id == organization.id
        )
    )
    item = await session.scalar(
        select(InventoryItem).where(
            InventoryItem.id == item_id, InventoryItem.organization_id == organization.id
        )
    )
    if supplier is None or item is None:
        raise HTTPException(status_code=404, detail="Supplier or inventory item not found")
    if supplier.status != "active" or item.status != "active":
        raise HTTPException(status_code=409, detail="Supplier and item must be active")
    record = await session.scalar(
        select(SupplierItem).where(
            SupplierItem.organization_id == organization.id,
            SupplierItem.supplier_id == supplier.id,
            SupplierItem.item_id == item.id,
        )
    )
    if record is None:
        record = SupplierItem(
            id=str(uuid4()),
            organization_id=organization.id,
            supplier_id=supplier.id,
            item_id=item.id,
            **payload.model_dump(),
        )
        session.add(record)
    else:
        for key, value in payload.model_dump().items():
            setattr(record, key, value)
    await session.commit()
    await session.refresh(record)
    return record


@router.get("/{supplier_id}/items", response_model=list[SupplierItemRead])
async def list_supplier_items(
    supplier_id: str,
    organization: SupplierReader,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> list[SupplierItem]:
    exists = await session.scalar(
        select(Supplier.id).where(
            Supplier.id == supplier_id, Supplier.organization_id == organization.id
        )
    )
    if exists is None:
        raise HTTPException(status_code=404, detail="Supplier not found")
    return list(
        (
            await session.scalars(
                select(SupplierItem)
                .where(
                    SupplierItem.organization_id == organization.id,
                    SupplierItem.supplier_id == supplier_id,
                )
                .order_by(SupplierItem.item_id)
            )
        ).all()
    )
