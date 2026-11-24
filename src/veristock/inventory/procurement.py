"""Purchase orders and immutable goods-received-note persistence."""

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


class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'issued', 'partially_received', 'received', 'cancelled')",
            name="ck_purchase_orders_status",
        ),
        UniqueConstraint("organization_id", "reference", name="uq_purchase_orders_reference"),
        UniqueConstraint(
            "organization_id", "idempotency_key", name="uq_purchase_orders_idempotency"
        ),
        Index("ix_purchase_orders_org_status", "organization_id", "status"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    supplier_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("suppliers.id", ondelete="RESTRICT"), nullable=False
    )
    branch_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False
    )
    reference: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="draft")
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    notes: Mapped[str | None] = mapped_column(String(1000))
    expected_delivery_date: Mapped[date | None] = mapped_column(Date)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    created_by_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    issued_by_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT")
    )
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    lines: Mapped[list["PurchaseOrderLine"]] = relationship(
        cascade="all, delete-orphan", lazy="selectin"
    )


class PurchaseOrderLine(Base):
    __tablename__ = "purchase_order_lines"
    __table_args__ = (
        CheckConstraint("ordered_quantity > 0", name="ck_po_lines_positive_ordered"),
        CheckConstraint(
            "received_quantity >= 0 AND received_quantity <= ordered_quantity",
            name="ck_po_lines_received_range",
        ),
        CheckConstraint("unit_cost >= 0", name="ck_po_lines_nonnegative_cost"),
        UniqueConstraint("purchase_order_id", "item_id", name="uq_po_line_item"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    purchase_order_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("purchase_orders.id", ondelete="CASCADE"), nullable=False
    )
    item_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("inventory_items.id", ondelete="RESTRICT"), nullable=False
    )
    ordered_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    received_quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), nullable=False, default=Decimal("0"), server_default="0"
    )
    unit_code: Mapped[str] = mapped_column(String(24), nullable=False)
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)


class GoodsReceipt(Base):
    __tablename__ = "goods_receipts"
    __table_args__ = (
        UniqueConstraint("organization_id", "reference", name="uq_goods_receipts_reference"),
        UniqueConstraint(
            "organization_id", "idempotency_key", name="uq_goods_receipts_idempotency"
        ),
        Index("ix_goods_receipts_org_po", "organization_id", "purchase_order_id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    purchase_order_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("purchase_orders.id", ondelete="RESTRICT"), nullable=False
    )
    reference: Mapped[str] = mapped_column(String(80), nullable=False)
    supplier_delivery_reference: Mapped[str | None] = mapped_column(String(120))
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    received_by_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    lines: Mapped[list["GoodsReceiptLine"]] = relationship(
        cascade="all, delete-orphan", lazy="selectin"
    )


class GoodsReceiptLine(Base):
    __tablename__ = "goods_receipt_lines"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_grn_lines_positive_quantity"),
        UniqueConstraint("goods_receipt_id", "purchase_order_line_id", name="uq_grn_line_po_line"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    goods_receipt_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("goods_receipts.id", ondelete="CASCADE"), nullable=False
    )
    purchase_order_line_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("purchase_order_lines.id", ondelete="RESTRICT"), nullable=False
    )
    item_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("inventory_items.id", ondelete="RESTRICT"), nullable=False
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    batch_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("inventory_batches.id", ondelete="RESTRICT")
    )


class InventoryCostLayer(Base):
    """Immutable receipt cost basis with a separately maintained unconsumed quantity."""

    __tablename__ = "inventory_cost_layers"
    __table_args__ = (
        CheckConstraint("received_quantity > 0", name="ck_cost_layers_received_positive"),
        CheckConstraint(
            "remaining_quantity >= 0 AND remaining_quantity <= received_quantity",
            name="ck_cost_layers_remaining_range",
        ),
        CheckConstraint("unit_cost >= 0", name="ck_cost_layers_unit_cost_nonnegative"),
        CheckConstraint(
            "(goods_receipt_line_id IS NOT NULL AND purchase_order_line_id IS NOT NULL "
            "AND source_transfer_line_id IS NULL AND source_cost_layer_id IS NULL) "
            "OR (goods_receipt_line_id IS NULL AND purchase_order_line_id IS NULL "
            "AND source_transfer_line_id IS NOT NULL AND source_cost_layer_id IS NOT NULL)",
            name="ck_cost_layers_single_origin",
        ),
        UniqueConstraint("goods_receipt_line_id", name="uq_cost_layers_receipt_line"),
        UniqueConstraint(
            "source_transfer_line_id",
            "source_cost_layer_id",
            name="uq_cost_layers_transfer_source",
        ),
        Index("ix_cost_layers_scope", "organization_id", "branch_id", "item_id"),
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
    goods_receipt_line_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("goods_receipt_lines.id", ondelete="RESTRICT")
    )
    purchase_order_line_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("purchase_order_lines.id", ondelete="RESTRICT")
    )
    source_transfer_line_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("stock_transfer_lines.id", ondelete="RESTRICT")
    )
    source_cost_layer_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("inventory_cost_layers.id", ondelete="RESTRICT")
    )
    received_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    remaining_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    unit_code: Mapped[str] = mapped_column(String(24), nullable=False)
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class InventoryCostAllocation(Base):
    """Immutable FIFO cost assigned to a single outbound stock movement."""

    __tablename__ = "inventory_cost_allocations"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_cost_allocations_quantity_positive"),
        CheckConstraint("unit_cost >= 0", name="ck_cost_allocations_unit_cost_nonnegative"),
        CheckConstraint("extended_cost >= 0", name="ck_cost_allocations_extended_nonnegative"),
        Index("ix_cost_allocations_movement", "stock_movement_id"),
        UniqueConstraint(
            "stock_movement_id", "cost_layer_id", name="uq_cost_allocation_movement_layer"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    stock_movement_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("stock_movements.id", ondelete="RESTRICT"), nullable=False
    )
    cost_layer_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("inventory_cost_layers.id", ondelete="RESTRICT"), nullable=False
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    extended_cost: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    allocated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SupplierReturn(Base):
    __tablename__ = "supplier_returns"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'dispatched', 'cancelled')", name="ck_supplier_returns_status"
        ),
        UniqueConstraint("organization_id", "reference", name="uq_supplier_returns_reference"),
        UniqueConstraint(
            "organization_id", "idempotency_key", name="uq_supplier_returns_idempotency"
        ),
        Index("ix_supplier_returns_org_status", "organization_id", "status"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    supplier_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("suppliers.id", ondelete="RESTRICT"), nullable=False
    )
    branch_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False
    )
    reference: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    created_by_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    dispatched_by_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lines: Mapped[list["SupplierReturnLine"]] = relationship(
        cascade="all, delete-orphan", lazy="selectin"
    )


class SupplierReturnLine(Base):
    __tablename__ = "supplier_return_lines"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_supplier_return_lines_positive_quantity"),
        UniqueConstraint(
            "supplier_return_id", "item_id", "batch_id", name="uq_supplier_return_line_scope"
        ),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    supplier_return_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("supplier_returns.id", ondelete="CASCADE"), nullable=False
    )
    item_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("inventory_items.id", ondelete="RESTRICT"), nullable=False
    )
    batch_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("inventory_batches.id", ondelete="RESTRICT")
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    unit_code: Mapped[str] = mapped_column(String(24), nullable=False)


class PurchaseRequisition(Base):
    __tablename__ = "purchase_requisitions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'submitted', 'approved', 'rejected', 'converted', 'cancelled')",
            name="ck_purchase_requisitions_status",
        ),
        CheckConstraint(
            "required_approvals BETWEEN 1 AND 5",
            name="ck_purchase_requisitions_required_approvals",
        ),
        UniqueConstraint("organization_id", "reference", name="uq_purchase_requisitions_reference"),
        UniqueConstraint(
            "organization_id", "idempotency_key", name="uq_purchase_requisitions_idempotency"
        ),
        UniqueConstraint(
            "converted_purchase_order_id", name="uq_purchase_requisitions_purchase_order"
        ),
        Index("ix_purchase_requisitions_org_status", "organization_id", "status"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    branch_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False
    )
    reference: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default="KES", server_default="KES"
    )
    required_approvals: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    justification: Mapped[str] = mapped_column(String(1000), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    requested_by_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    converted_purchase_order_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey(
            "purchase_orders.id",
            ondelete="RESTRICT",
            name="fk_purchase_requisitions_converted_purchase_order",
        ),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    lines: Mapped[list["PurchaseRequisitionLine"]] = relationship(
        cascade="all, delete-orphan", lazy="selectin"
    )
    decisions: Mapped[list["PurchaseRequisitionDecision"]] = relationship(
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="PurchaseRequisitionDecision.created_at",
    )


class PurchaseRequisitionLine(Base):
    __tablename__ = "purchase_requisition_lines"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_purchase_requisition_lines_positive_quantity"),
        UniqueConstraint("requisition_id", "item_id", name="uq_purchase_requisition_line_item"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    requisition_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("purchase_requisitions.id", ondelete="CASCADE"), nullable=False
    )
    item_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("inventory_items.id", ondelete="RESTRICT"), nullable=False
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    unit_code: Mapped[str] = mapped_column(String(24), nullable=False)
    estimated_unit_cost: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))


class PurchaseRequisitionDecision(Base):
    __tablename__ = "purchase_requisition_decisions"
    __table_args__ = (
        CheckConstraint(
            "decision IN ('submitted', 'approved', 'rejected')",
            name="ck_purchase_requisition_decisions_decision",
        ),
        Index("ix_purchase_requisition_decisions_org_req", "organization_id", "requisition_id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    requisition_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("purchase_requisitions.id", ondelete="CASCADE"), nullable=False
    )
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    reason: Mapped[str | None] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ProcurementApprovalRule(Base):
    """Value band defining the number of independent requisition approvals."""

    __tablename__ = "procurement_approval_rules"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "currency", "minimum_total", name="uq_procurement_approval_rule_band"
        ),
        CheckConstraint("minimum_total >= 0", name="ck_procurement_approval_rule_nonnegative"),
        CheckConstraint(
            "required_approvals BETWEEN 1 AND 5", name="ck_procurement_approval_rule_approvers"
        ),
        Index("ix_procurement_approval_rules_org_currency", "organization_id", "currency"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    minimum_total: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    required_approvals: Mapped[int] = mapped_column(Integer, nullable=False)
    created_by_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
