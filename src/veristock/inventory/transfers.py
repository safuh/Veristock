"""Branch-to-branch inventory transfer persistence."""

from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from veristock.core.database import Base


class StockTransfer(Base):
    __tablename__ = "stock_transfers"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'dispatched', 'received', 'cancelled')",
            name="ck_stock_transfers_status",
        ),
        CheckConstraint(
            "source_branch_id != destination_branch_id", name="ck_stock_transfers_distinct_branches"
        ),
        UniqueConstraint("organization_id", "reference", name="uq_stock_transfers_reference"),
        UniqueConstraint(
            "organization_id", "idempotency_key", name="uq_stock_transfers_idempotency"
        ),
        Index("ix_stock_transfers_org_status", "organization_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    reference: Mapped[str] = mapped_column(String(80), nullable=False)
    source_branch_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False
    )
    destination_branch_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    note: Mapped[str | None] = mapped_column(String(500))
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    created_by_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    dispatched_by_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT")
    )
    received_by_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lines: Mapped[list["StockTransferLine"]] = relationship(
        cascade="all, delete-orphan", lazy="selectin"
    )


class StockTransferLine(Base):
    __tablename__ = "stock_transfer_lines"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_stock_transfer_lines_positive_quantity"),
        UniqueConstraint(
            "transfer_id", "item_id", "batch_id", name="uq_stock_transfer_line_item_batch"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    transfer_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("stock_transfers.id", ondelete="CASCADE"), nullable=False
    )
    item_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("inventory_items.id", ondelete="RESTRICT"), nullable=False
    )
    batch_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("inventory_batches.id", ondelete="RESTRICT")
    )
    destination_batch_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("inventory_batches.id", ondelete="RESTRICT")
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    unit_code: Mapped[str] = mapped_column(String(24), nullable=False)
