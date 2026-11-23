"""Inventory catalogue, stock ledger and client sales persistence."""

from datetime import date, datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from veristock.core.database import Base


class InventoryItem(Base):
    """A tenant-owned catalogue item measured in one explicit base unit."""

    __tablename__ = "inventory_items"
    __table_args__ = (
        UniqueConstraint("organization_id", "sku", name="uq_inventory_items_org_sku"),
        UniqueConstraint("organization_id", "barcode", name="uq_inventory_items_org_barcode"),
        CheckConstraint("status IN ('active', 'inactive')", name="ck_inventory_items_status"),
        Index("ix_inventory_items_org_name", "organization_id", "name"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    sku: Mapped[str | None] = mapped_column(String(80))
    barcode: Mapped[str | None] = mapped_column(String(128))
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    description: Mapped[str | None] = mapped_column(String(1000))
    base_unit_code: Mapped[str] = mapped_column(String(24), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class StockBalance(Base):
    """Current branch/item quantity projection maintained with the movement ledger."""

    __tablename__ = "stock_balances"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "branch_id", "item_id", name="uq_stock_balances_scope_item"
        ),
        CheckConstraint("quantity_on_hand >= 0", name="ck_stock_balances_nonnegative"),
        Index("ix_stock_balances_org_branch", "organization_id", "branch_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    branch_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False
    )
    item_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("inventory_items.id", ondelete="RESTRICT"), nullable=False
    )
    quantity_on_hand: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), nullable=False, default=Decimal("0")
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class StockMovement(Base):
    """Append-only signed stock change with an auditable source and idempotency key."""

    __tablename__ = "stock_movements"
    __table_args__ = (
        CheckConstraint("quantity_delta != 0", name="ck_stock_movements_nonzero"),
        CheckConstraint(
            "source_type IN ('opening_balance', 'sale', 'stocktake_adjustment', "
            "'reversal', 'manual_adjustment', 'batch_receipt', 'batch_issue', "
            "'stock_transfer', 'purchase_receipt')",
            name="ck_stock_movements_source_type",
        ),
        UniqueConstraint(
            "organization_id", "idempotency_key", name="uq_stock_movements_idempotency"
        ),
        UniqueConstraint(
            "organization_id",
            "reversal_of_movement_id",
            name="uq_stock_movements_single_reversal",
        ),
        Index("ix_stock_movements_org_branch_time", "organization_id", "branch_id", "occurred_at"),
        Index("ix_stock_movements_org_item_time", "organization_id", "item_id", "occurred_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    branch_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False
    )
    item_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("inventory_items.id", ondelete="RESTRICT"), nullable=False
    )
    batch_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("inventory_batches.id", ondelete="RESTRICT")
    )
    quantity_delta: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    unit_code: Mapped[str] = mapped_column(String(24), nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_id: Mapped[str | None] = mapped_column(String(36))
    reason: Mapped[str | None] = mapped_column(String(500))
    reversal_of_movement_id: Mapped[str | None] = mapped_column(String(36))
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    actor_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Sale(Base):
    """A client-entered sale; posting is immutable and creates stock movements."""

    __tablename__ = "sales"
    __table_args__ = (
        UniqueConstraint("organization_id", "idempotency_key", name="uq_sales_idempotency"),
        CheckConstraint("status IN ('posted', 'reversed')", name="ck_sales_status"),
        Index("ix_sales_org_branch_posted", "organization_id", "branch_id", "posted_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    branch_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    reference: Mapped[str | None] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="posted")
    recorded_by_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    posted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    lines: Mapped[list["SaleLine"]] = relationship(
        back_populates="sale",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class SaleLine(Base):
    """Quantity and optional verified selling price for one item in a posted sale."""

    __tablename__ = "sale_lines"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_sale_lines_positive_quantity"),
        CheckConstraint(
            "(unit_price IS NULL AND currency IS NULL) OR "
            "(unit_price >= 0 AND currency IS NOT NULL)",
            name="ck_sale_lines_price_currency_pair",
        ),
        Index("ix_sale_lines_sale", "sale_id"),
        Index("ix_sale_lines_org_item", "organization_id", "item_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    sale_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("sales.id", ondelete="CASCADE"), nullable=False
    )
    item_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("inventory_items.id", ondelete="RESTRICT"), nullable=False
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    unit_code: Mapped[str] = mapped_column(String(24), nullable=False)
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    currency: Mapped[str | None] = mapped_column(String(3))
    sale: Mapped["Sale"] = relationship(back_populates="lines")


class InventoryBatch(Base):
    """A traceable lot of an item received at a specific branch."""

    __tablename__ = "inventory_batches"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "item_id",
            "branch_id",
            "lot_code",
            name="uq_inventory_batches_scope_lot",
        ),
        CheckConstraint(
            "status IN ('active', 'quarantined', 'recalled', 'closed')",
            name="ck_inventory_batches_status",
        ),
        CheckConstraint(
            "expiry_date IS NULL OR manufactured_date IS NULL OR expiry_date >= manufactured_date",
            name="ck_inventory_batches_dates",
        ),
        Index("ix_inventory_batches_expiry", "organization_id", "branch_id", "expiry_date"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    item_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("inventory_items.id", ondelete="RESTRICT"), nullable=False
    )
    branch_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False
    )
    lot_code: Mapped[str] = mapped_column(String(100), nullable=False)
    manufactured_date: Mapped[date | None] = mapped_column(Date)
    expiry_date: Mapped[date | None] = mapped_column(Date)
    supplier_reference: Mapped[str | None] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active", server_default="active"
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class BatchStockBalance(Base):
    """Quantity projection for one item lot at one branch."""

    __tablename__ = "batch_stock_balances"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "branch_id", "item_id", "batch_id", name="uq_batch_balance_scope"
        ),
        CheckConstraint("quantity_on_hand >= 0", name="ck_batch_balance_nonnegative"),
        Index("ix_batch_balance_item", "organization_id", "branch_id", "item_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    branch_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False
    )
    item_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("inventory_items.id", ondelete="RESTRICT"), nullable=False
    )
    batch_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("inventory_batches.id", ondelete="RESTRICT"), nullable=False
    )
    quantity_on_hand: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)


class Supplier(Base):
    """Tenant-owned supplier master record."""

    __tablename__ = "suppliers"
    __table_args__ = (
        UniqueConstraint("organization_id", "code", name="uq_suppliers_org_code"),
        CheckConstraint("status IN ('active', 'inactive', 'blocked')", name="ck_suppliers_status"),
        Index("ix_suppliers_org_name", "organization_id", "name"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    contact_name: Mapped[str | None] = mapped_column(String(160))
    email: Mapped[str | None] = mapped_column(String(254))
    phone: Mapped[str | None] = mapped_column(String(40))
    website: Mapped[str | None] = mapped_column(String(300))
    address: Mapped[str | None] = mapped_column(String(1000))
    tax_reference: Mapped[str | None] = mapped_column(String(100))
    payment_terms: Mapped[str | None] = mapped_column(String(240))
    default_currency: Mapped[str] = mapped_column(String(3), nullable=False, default="KES")
    notes: Mapped[str | None] = mapped_column(String(1000))
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class SupplierItem(Base):
    """Supplier-specific SKU, purchase price and lead-time for an inventory item."""

    __tablename__ = "supplier_items"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "supplier_id", "item_id", name="uq_supplier_items_scope"
        ),
        CheckConstraint("unit_cost >= 0", name="ck_supplier_items_nonnegative_cost"),
        CheckConstraint("minimum_order_quantity > 0", name="ck_supplier_items_positive_moq"),
        CheckConstraint("lead_time_days >= 0", name="ck_supplier_items_nonnegative_lead_time"),
        Index("ix_supplier_items_org_item", "organization_id", "item_id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    supplier_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("suppliers.id", ondelete="CASCADE"), nullable=False
    )
    item_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("inventory_items.id", ondelete="RESTRICT"), nullable=False
    )
    supplier_sku: Mapped[str | None] = mapped_column(String(100))
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="KES")
    minimum_order_quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), nullable=False, default=Decimal("1")
    )
    lead_time_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_preferred: Mapped[bool] = mapped_column(nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
