"""Tenant-scoped supplier directory and supplier item catalogue."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from veristock.identity.authorization import Organization
from veristock.identity.authorization_dependencies import get_db_session, require_permission
from veristock.inventory.models import InventoryItem, Supplier, SupplierItem
from veristock.inventory.procurement import PurchaseOrder, SupplierReturn

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


@router.get("/{supplier_id}/performance")
async def supplier_performance(
    supplier_id: str,
    organization: SupplierReader,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict[str, object]:
    """Return tenant-scoped purchasing, fulfilment and supplier-return metrics."""
    supplier = await session.scalar(
        select(Supplier).where(
            Supplier.id == supplier_id,
            Supplier.organization_id == organization.id,
        )
    )
    if supplier is None:
        raise HTTPException(status_code=404, detail="Supplier not found")

    orders = list(
        (
            await session.scalars(
                select(PurchaseOrder)
                .where(
                    PurchaseOrder.organization_id == organization.id,
                    PurchaseOrder.supplier_id == supplier.id,
                )
                .options(selectinload(PurchaseOrder.lines))
            )
        ).all()
    )
    returns = list(
        (
            await session.scalars(
                select(SupplierReturn)
                .where(
                    SupplierReturn.organization_id == organization.id,
                    SupplierReturn.supplier_id == supplier.id,
                )
                .options(selectinload(SupplierReturn.lines))
            )
        ).all()
    )

    from collections import defaultdict

    values: dict[str, dict[str, Decimal]] = defaultdict(
        lambda: {"ordered": Decimal("0"), "received": Decimal("0")}
    )
    quantities: dict[str, dict[str, Decimal]] = defaultdict(
        lambda: {
            "ordered": Decimal("0"),
            "received": Decimal("0"),
            "returned": Decimal("0"),
        }
    )
    for order in orders:
        for line in order.lines:
            values[order.currency]["ordered"] += line.ordered_quantity * line.unit_cost
            values[order.currency]["received"] += line.received_quantity * line.unit_cost
            quantities[line.unit_code]["ordered"] += line.ordered_quantity
            quantities[line.unit_code]["received"] += line.received_quantity

    dispatched_returns = [record for record in returns if record.status == "dispatched"]
    for record in dispatched_returns:
        for return_line in record.lines:
            quantities[return_line.unit_code]["returned"] += return_line.quantity

    unit_metrics: list[dict[str, object]] = []
    for unit_code, totals in sorted(quantities.items()):
        received = totals["received"]
        unit_metrics.append(
            {
                "unit_code": unit_code,
                "ordered_quantity": totals["ordered"],
                "received_quantity": received,
                "returned_quantity": totals["returned"],
                "fulfilment_rate_percent": (
                    (received / totals["ordered"] * Decimal("100")).quantize(Decimal("0.01"))
                    if totals["ordered"]
                    else None
                ),
                "return_rate_percent": (
                    (totals["returned"] / received * Decimal("100")).quantize(Decimal("0.01"))
                    if received
                    else None
                ),
            }
        )

    currency_metrics = [
        {
            "currency": currency,
            "ordered_value": totals["ordered"],
            "received_value": totals["received"],
            "outstanding_value": totals["ordered"] - totals["received"],
        }
        for currency, totals in sorted(values.items())
    ]
    return {
        "supplier": {"id": supplier.id, "code": supplier.code, "name": supplier.name},
        "period": "all_time",
        "purchase_order_count": len(orders),
        "issued_purchase_order_count": sum(
            order.status not in {"draft", "cancelled"} for order in orders
        ),
        "fully_received_purchase_order_count": sum(
            order.status == "received" for order in orders
        ),
        "open_purchase_order_count": sum(
            order.status in {"issued", "partially_received"} for order in orders
        ),
        "supplier_return_count": len(returns),
        "dispatched_supplier_return_count": len(dispatched_returns),
        "scheduled_delivery_order_count": sum(
            order.expected_delivery_date is not None and order.status != "draft"
            for order in orders
        ),
        "completed_on_time_order_count": sum(
            order.completed_at is not None
            and order.expected_delivery_date is not None
            and order.completed_at.date() <= order.expected_delivery_date
            for order in orders
        ),
        "completed_late_order_count": sum(
            order.completed_at is not None
            and order.expected_delivery_date is not None
            and order.completed_at.date() > order.expected_delivery_date
            for order in orders
        ),
        "on_time_delivery_rate_percent": (
            (
                Decimal(
                    sum(
                        order.completed_at is not None
                        and order.expected_delivery_date is not None
                        and order.completed_at.date() <= order.expected_delivery_date
                        for order in orders
                    )
                )
                / Decimal(
                    sum(
                        order.completed_at is not None and order.expected_delivery_date is not None
                        for order in orders
                    )
                )
                * Decimal("100")
            ).quantize(Decimal("0.01"))
            if any(
                order.completed_at is not None and order.expected_delivery_date is not None
                for order in orders
            )
            else None
        ),
        "currency_metrics": currency_metrics,
        "unit_metrics": unit_metrics,
        "limitations": [
            (
                "Return rates are reported by unit of measure; quantities across "
                "different units are not combined."
            ),
        ],
    }
