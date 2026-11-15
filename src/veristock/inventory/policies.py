"""Tenant-scoped branch/item replenishment planning policies."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from veristock.core.database import Base


class ReplenishmentPolicy(Base):
    """Human-maintained planning assumptions for one item at one branch."""

    __tablename__ = "replenishment_policies"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "branch_id",
            "item_id",
            name="uq_replenishment_policy_scope_item",
        ),
        CheckConstraint(
            "lead_time_days BETWEEN 0 AND 180",
            name="ck_replenishment_policy_lead_time",
        ),
        CheckConstraint(
            "safety_stock_days BETWEEN 0 AND 180",
            name="ck_replenishment_policy_safety_stock",
        ),
        Index(
            "ix_replenishment_policies_org_branch",
            "organization_id",
            "branch_id",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    branch_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("branches.id", ondelete="CASCADE"), nullable=False
    )
    item_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("inventory_items.id", ondelete="CASCADE"), nullable=False
    )
    lead_time_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    safety_stock_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_by_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
