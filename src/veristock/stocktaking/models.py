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
            "status IN ('open', 'submitted', 'cancelled', 'completed')",
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
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT")
    )


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
        UniqueConstraint("organization_id", "idempotency_key", name="uq_stocktake_observation_idempotency"),
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


class StocktakeDecision(Base):
    """Append-only record of supervisor actions on a physical stocktake."""

    __tablename__ = "stocktake_decisions"
    __table_args__ = (
        CheckConstraint(
            "action IN ('recount_requested', 'rejected', 'approved')",
            name="ck_stocktake_decisions_action",
        ),
        CheckConstraint(
            "(action = 'recount_requested' AND reason_code IS NOT NULL AND reason IS NOT NULL) "
            "OR (action = 'rejected' AND reason_code IS NOT NULL AND reason IS NOT NULL) "
            "OR (action = 'approved' AND reason_code IS NULL AND reason IS NULL)",
            name="ck_stocktake_decisions_reason",
        ),
        Index(
            "ix_stocktake_decisions_org_stocktake_created",
            "organization_id",
            "stocktake_id",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    stocktake_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("stocktakes.id", ondelete="CASCADE"), nullable=False
    )
    round_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("stocktake_rounds.id", ondelete="RESTRICT"), nullable=False
    )
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(40))
    reason: Mapped[str | None] = mapped_column(String(500))
    actor_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
