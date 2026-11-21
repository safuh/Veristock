# ruff: noqa: E501
"""Physical stocktake plans, frozen expected quantities and immutable count rounds."""

from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from veristock.core.database import Base


class Stocktake(Base):
    __tablename__ = "stocktakes"
    __table_args__ = (
        CheckConstraint(
            "status IN ('open', 'submitted', 'cancelled')",
            name="ck_stocktakes_status",
        ),
        Index("ix_stocktakes_org_branch_status", "organization_id", "branch_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    branch_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False
    )
    reference: Mapped[str] = mapped_column(String(80), nullable=False)
    blind_count: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    created_by_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class StocktakeScopeItem(Base):
    __tablename__ = "stocktake_scope_items"
    __table_args__ = (
        UniqueConstraint("stocktake_id", "item_id", name="uq_stocktake_scope_item"),
        CheckConstraint("expected_quantity >= 0", name="ck_stocktake_expected_nonnegative"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    stocktake_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("stocktakes.id", ondelete="CASCADE"), nullable=False
    )
    item_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("inventory_items.id", ondelete="RESTRICT"), nullable=False
    )
    expected_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    expected_balance_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    unit_code: Mapped[str] = mapped_column(String(24), nullable=False)


class StocktakeRound(Base):
    __tablename__ = "stocktake_rounds"
    __table_args__ = (
        UniqueConstraint("stocktake_id", "round_number", name="uq_stocktake_round_number"),
        CheckConstraint("status IN ('open', 'submitted')", name="ck_stocktake_round_status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    stocktake_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("stocktakes.id", ondelete="CASCADE"), nullable=False
    )
    round_number: Mapped[int] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    opened_by_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class StocktakeObservation(Base):
    __tablename__ = "stocktake_observations"
    __table_args__ = (
        UniqueConstraint("round_id", "item_id", name="uq_stocktake_observation_round_item"),
        UniqueConstraint(
            "organization_id", "idempotency_key", name="uq_stocktake_observation_idempotency"
        ),
        CheckConstraint("counted_quantity >= 0", name="ck_stocktake_count_nonnegative"),
        Index("ix_stocktake_observations_org_item", "organization_id", "item_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    stocktake_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("stocktakes.id", ondelete="CASCADE"), nullable=False
    )
    round_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("stocktake_rounds.id", ondelete="CASCADE"), nullable=False
    )
    item_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("inventory_items.id", ondelete="RESTRICT"), nullable=False
    )
    counted_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    unit_code: Mapped[str] = mapped_column(String(24), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    counted_by_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    counted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ReconciliationRun(Base):
    """Immutable calculation of one submitted physical count round."""

    __tablename__ = "reconciliation_runs"
    __table_args__ = (
        UniqueConstraint("stocktake_id", "version", name="uq_reconciliation_stocktake_version"),
        UniqueConstraint("stocktake_id", "round_id", name="uq_reconciliation_stocktake_round"),
        CheckConstraint(
            "status IN ('calculated', 'approved', 'rejected')",
            name="ck_reconciliation_runs_status",
        ),
        CheckConstraint("version >= 1", name="ck_reconciliation_runs_version"),
        Index("ix_reconciliation_runs_org_status", "organization_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    stocktake_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("stocktakes.id", ondelete="RESTRICT"), nullable=False
    )
    round_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("stocktake_rounds.id", ondelete="RESTRICT"), nullable=False
    )
    version: Mapped[int] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="calculated")
    calculated_by_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    calculated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    decided_by_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT")
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_note: Mapped[str | None] = mapped_column(String(1000))


class ReconciliationLine(Base):
    """Frozen expected/observed comparison for one item in a run."""

    __tablename__ = "reconciliation_lines"
    __table_args__ = (
        UniqueConstraint("run_id", "item_id", name="uq_reconciliation_line_run_item"),
        CheckConstraint("expected_quantity >= 0", name="ck_reconciliation_expected_nonnegative"),
        CheckConstraint("physical_quantity >= 0", name="ck_reconciliation_physical_nonnegative"),
        CheckConstraint(
            "variance_quantity = physical_quantity - expected_quantity",
            name="ck_reconciliation_variance_consistent",
        ),
        CheckConstraint(
            "classification IN ('matched', 'shortage', 'surplus')",
            name="ck_reconciliation_line_classification",
        ),
        Index("ix_reconciliation_lines_org_item", "organization_id", "item_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("reconciliation_runs.id", ondelete="CASCADE"), nullable=False
    )
    item_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("inventory_items.id", ondelete="RESTRICT"), nullable=False
    )
    expected_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    physical_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    variance_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    unit_code: Mapped[str] = mapped_column(String(24), nullable=False)
    classification: Mapped[str] = mapped_column(String(16), nullable=False)


class ReconciliationApproval(Base):
    """Append-only approval decision for a reconciliation run."""

    __tablename__ = "reconciliation_approvals"
    __table_args__ = (
        UniqueConstraint("run_id", name="uq_reconciliation_approval_run"),
        CheckConstraint(
            "decision IN ('approved', 'rejected')", name="ck_reconciliation_approval_decision"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("reconciliation_runs.id", ondelete="RESTRICT"), nullable=False
    )
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    decided_by_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    note: Mapped[str | None] = mapped_column(String(1000))
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
