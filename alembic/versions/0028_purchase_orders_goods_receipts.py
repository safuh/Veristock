"""Add purchase orders, partial goods receipts and stock ledger source."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0028_purchase_orders_goods_receipts"
down_revision: str | None = "0027_supplier_directory"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "purchase_orders",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(36),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "supplier_id",
            sa.String(36),
            sa.ForeignKey("suppliers.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "branch_id",
            sa.String(36),
            sa.ForeignKey("branches.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("reference", sa.String(80), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="draft"),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("notes", sa.String(1000)),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column(
            "created_by_user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "issued_by_user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT")
        ),
        sa.Column("issued_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("organization_id", "reference", name="uq_purchase_orders_reference"),
        sa.UniqueConstraint(
            "organization_id", "idempotency_key", name="uq_purchase_orders_idempotency"
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'issued', 'partially_received', 'received', 'cancelled')",
            name="ck_purchase_orders_status",
        ),
    )
    op.create_index(
        "ix_purchase_orders_org_status", "purchase_orders", ["organization_id", "status"]
    )
    op.create_table(
        "purchase_order_lines",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(36),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "purchase_order_id",
            sa.String(36),
            sa.ForeignKey("purchase_orders.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "item_id",
            sa.String(36),
            sa.ForeignKey("inventory_items.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("ordered_quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("received_quantity", sa.Numeric(18, 4), nullable=False, server_default="0"),
        sa.Column("unit_code", sa.String(24), nullable=False),
        sa.Column("unit_cost", sa.Numeric(18, 4), nullable=False),
        sa.UniqueConstraint("purchase_order_id", "item_id", name="uq_po_line_item"),
        sa.CheckConstraint("ordered_quantity > 0", name="ck_po_lines_positive_ordered"),
        sa.CheckConstraint(
            "received_quantity >= 0 AND received_quantity <= ordered_quantity",
            name="ck_po_lines_received_range",
        ),
        sa.CheckConstraint("unit_cost >= 0", name="ck_po_lines_nonnegative_cost"),
    )
    op.create_table(
        "goods_receipts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(36),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "purchase_order_id",
            sa.String(36),
            sa.ForeignKey("purchase_orders.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("reference", sa.String(80), nullable=False),
        sa.Column("supplier_delivery_reference", sa.String(120)),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column(
            "received_by_user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "received_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("organization_id", "reference", name="uq_goods_receipts_reference"),
        sa.UniqueConstraint(
            "organization_id", "idempotency_key", name="uq_goods_receipts_idempotency"
        ),
    )
    op.create_index(
        "ix_goods_receipts_org_po", "goods_receipts", ["organization_id", "purchase_order_id"]
    )
    op.create_table(
        "goods_receipt_lines",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(36),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "goods_receipt_id",
            sa.String(36),
            sa.ForeignKey("goods_receipts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "purchase_order_line_id",
            sa.String(36),
            sa.ForeignKey("purchase_order_lines.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "item_id",
            sa.String(36),
            sa.ForeignKey("inventory_items.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column(
            "batch_id", sa.String(36), sa.ForeignKey("inventory_batches.id", ondelete="RESTRICT")
        ),
        sa.UniqueConstraint(
            "goods_receipt_id", "purchase_order_line_id", name="uq_grn_line_po_line"
        ),
        sa.CheckConstraint("quantity > 0", name="ck_grn_lines_positive_quantity"),
    )
    with op.batch_alter_table("stock_movements") as batch_op:
        batch_op.drop_constraint("ck_stock_movements_source_type", type_="check")
        batch_op.create_check_constraint(
            "ck_stock_movements_source_type",
            "source_type IN ('opening_balance', 'sale', 'stocktake_adjustment', 'reversal', "
            "'manual_adjustment', 'batch_receipt', 'batch_issue', "
            "'stock_transfer', 'purchase_receipt')",
        )


def downgrade() -> None:
    with op.batch_alter_table("stock_movements") as batch_op:
        batch_op.drop_constraint("ck_stock_movements_source_type", type_="check")
        batch_op.create_check_constraint(
            "ck_stock_movements_source_type",
            "source_type IN ('opening_balance', 'sale', 'stocktake_adjustment', 'reversal', "
            "'manual_adjustment', 'batch_receipt', 'batch_issue', 'stock_transfer')",
        )
    op.drop_table("goods_receipt_lines")
    op.drop_index("ix_goods_receipts_org_po", table_name="goods_receipts")
    op.drop_table("goods_receipts")
    op.drop_table("purchase_order_lines")
    op.drop_index("ix_purchase_orders_org_status", table_name="purchase_orders")
    op.drop_table("purchase_orders")
