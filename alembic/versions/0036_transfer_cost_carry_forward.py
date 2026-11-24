"""Carry FIFO cost layers across inter-branch transfers."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0036_transfer_cost_carry_forward"
down_revision: str | None = "0035_inventory_cost_allocations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("inventory_cost_layers") as batch:
        batch.alter_column("goods_receipt_line_id", existing_type=sa.String(36), nullable=True)
        batch.alter_column("purchase_order_line_id", existing_type=sa.String(36), nullable=True)
        batch.add_column(sa.Column("source_transfer_line_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("source_cost_layer_id", sa.String(36), nullable=True))
        batch.create_foreign_key(
            "fk_cost_layers_transfer_line",
            "stock_transfer_lines",
            ["source_transfer_line_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch.create_foreign_key(
            "fk_cost_layers_source_layer",
            "inventory_cost_layers",
            ["source_cost_layer_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch.create_check_constraint(
            "ck_cost_layers_single_origin",
            "(goods_receipt_line_id IS NOT NULL AND purchase_order_line_id IS NOT NULL "
            "AND source_transfer_line_id IS NULL AND source_cost_layer_id IS NULL) "
            "OR (goods_receipt_line_id IS NULL AND purchase_order_line_id IS NULL "
            "AND source_transfer_line_id IS NOT NULL AND source_cost_layer_id IS NOT NULL)",
        )
        batch.create_unique_constraint(
            "uq_cost_layers_transfer_source", ["source_transfer_line_id", "source_cost_layer_id"]
        )


def downgrade() -> None:
    with op.batch_alter_table("inventory_cost_layers") as batch:
        batch.drop_constraint("uq_cost_layers_transfer_source", type_="unique")
        batch.drop_constraint("ck_cost_layers_single_origin", type_="check")
        batch.drop_constraint("fk_cost_layers_source_layer", type_="foreignkey")
        batch.drop_constraint("fk_cost_layers_transfer_line", type_="foreignkey")
        batch.drop_column("source_cost_layer_id")
        batch.drop_column("source_transfer_line_id")
        batch.alter_column("purchase_order_line_id", existing_type=sa.String(36), nullable=False)
        batch.alter_column("goods_receipt_line_id", existing_type=sa.String(36), nullable=False)
