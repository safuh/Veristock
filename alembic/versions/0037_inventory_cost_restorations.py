"""Audit FIFO cost restored by manual stock adjustment reversals."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0037_inventory_cost_restorations"
down_revision: str | None = "0036_transfer_cost_carry_forward"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "inventory_cost_restorations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(36),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "reversal_movement_id",
            sa.String(36),
            sa.ForeignKey("stock_movements.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "original_allocation_id",
            sa.String(36),
            sa.ForeignKey("inventory_cost_allocations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "cost_layer_id",
            sa.String(36),
            sa.ForeignKey("inventory_cost_layers.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("unit_cost", sa.Numeric(18, 4), nullable=False),
        sa.Column("extended_cost", sa.Numeric(18, 4), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column(
            "restored_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("quantity > 0", name="ck_cost_restorations_quantity_positive"),
        sa.CheckConstraint("unit_cost >= 0", name="ck_cost_restorations_unit_cost_nonnegative"),
        sa.CheckConstraint("extended_cost >= 0", name="ck_cost_restorations_extended_nonnegative"),
        sa.UniqueConstraint(
            "reversal_movement_id",
            "original_allocation_id",
            name="uq_cost_restoration_reversal_allocation",
        ),
    )
    op.create_index(
        "ix_cost_restorations_org_layer",
        "inventory_cost_restorations",
        ["organization_id", "cost_layer_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_cost_restorations_org_layer", table_name="inventory_cost_restorations")
    op.drop_table("inventory_cost_restorations")
