"""Record immutable cost basis for each goods receipt line."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0034_inventory_cost_layers"
down_revision: str | None = "0033_purchase_order_delivery_tracking"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "inventory_cost_layers",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(length=36),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "branch_id",
            sa.String(length=36),
            sa.ForeignKey("branches.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "item_id",
            sa.String(length=36),
            sa.ForeignKey("inventory_items.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "batch_id",
            sa.String(length=36),
            sa.ForeignKey("inventory_batches.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "goods_receipt_line_id",
            sa.String(length=36),
            sa.ForeignKey("goods_receipt_lines.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "purchase_order_line_id",
            sa.String(length=36),
            sa.ForeignKey("purchase_order_lines.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("received_quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("remaining_quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("unit_code", sa.String(length=24), nullable=False),
        sa.Column("unit_cost", sa.Numeric(18, 4), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column(
            "received_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("received_quantity > 0", name="ck_cost_layers_received_positive"),
        sa.CheckConstraint(
            "remaining_quantity >= 0 AND remaining_quantity <= received_quantity",
            name="ck_cost_layers_remaining_range",
        ),
        sa.CheckConstraint("unit_cost >= 0", name="ck_cost_layers_unit_cost_nonnegative"),
        sa.UniqueConstraint("goods_receipt_line_id", name="uq_cost_layers_receipt_line"),
    )
    op.create_index(
        "ix_cost_layers_scope",
        "inventory_cost_layers",
        ["organization_id", "branch_id", "item_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_cost_layers_scope", table_name="inventory_cost_layers")
    op.drop_table("inventory_cost_layers")
