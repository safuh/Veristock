"""Persist FIFO cost allocations against outbound stock movements."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0035_inventory_cost_allocations"
down_revision: str | None = "0034_inventory_cost_layers"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "inventory_cost_allocations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(36),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "stock_movement_id",
            sa.String(36),
            sa.ForeignKey("stock_movements.id", ondelete="RESTRICT"),
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
            "allocated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("quantity > 0", name="ck_cost_allocations_quantity_positive"),
        sa.CheckConstraint("unit_cost >= 0", name="ck_cost_allocations_unit_cost_nonnegative"),
        sa.CheckConstraint("extended_cost >= 0", name="ck_cost_allocations_extended_nonnegative"),
        sa.UniqueConstraint(
            "stock_movement_id", "cost_layer_id", name="uq_cost_allocation_movement_layer"
        ),
    )
    op.create_index(
        "ix_cost_allocations_movement", "inventory_cost_allocations", ["stock_movement_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_cost_allocations_movement", table_name="inventory_cost_allocations")
    op.drop_table("inventory_cost_allocations")
