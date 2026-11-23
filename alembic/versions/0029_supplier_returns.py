"""Add auditable supplier return workflow."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0029_supplier_returns"
down_revision: str | None = "0028_purchase_orders_goods_receipts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "supplier_returns",
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
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column(
            "created_by_user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "dispatched_by_user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT")
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("dispatched_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("organization_id", "reference", name="uq_supplier_returns_reference"),
        sa.UniqueConstraint(
            "organization_id", "idempotency_key", name="uq_supplier_returns_idempotency"
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'dispatched', 'cancelled')", name="ck_supplier_returns_status"
        ),
    )
    op.create_index(
        "ix_supplier_returns_org_status", "supplier_returns", ["organization_id", "status"]
    )
    op.create_table(
        "supplier_return_lines",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(36),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "supplier_return_id",
            sa.String(36),
            sa.ForeignKey("supplier_returns.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "item_id",
            sa.String(36),
            sa.ForeignKey("inventory_items.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "batch_id", sa.String(36), sa.ForeignKey("inventory_batches.id", ondelete="RESTRICT")
        ),
        sa.Column("quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("unit_code", sa.String(24), nullable=False),
        sa.UniqueConstraint(
            "supplier_return_id", "item_id", "batch_id", name="uq_supplier_return_line_scope"
        ),
        sa.CheckConstraint("quantity > 0", name="ck_supplier_return_lines_positive_quantity"),
    )
    with op.batch_alter_table("stock_movements") as batch_op:
        batch_op.drop_constraint("ck_stock_movements_source_type", type_="check")
        batch_op.create_check_constraint(
            "ck_stock_movements_source_type",
            "source_type IN ('opening_balance', 'sale', 'stocktake_adjustment', 'reversal', "
            "'manual_adjustment', 'batch_receipt', 'batch_issue', 'stock_transfer', "
            "'purchase_receipt', 'supplier_return')",
        )


def downgrade() -> None:
    with op.batch_alter_table("stock_movements") as batch_op:
        batch_op.drop_constraint("ck_stock_movements_source_type", type_="check")
        batch_op.create_check_constraint(
            "ck_stock_movements_source_type",
            "source_type IN ('opening_balance', 'sale', 'stocktake_adjustment', 'reversal', "
            "'manual_adjustment', 'batch_receipt', 'batch_issue', "
            "'stock_transfer', 'purchase_receipt')",
        )
    op.drop_table("supplier_return_lines")
    op.drop_index("ix_supplier_returns_org_status", table_name="supplier_returns")
    op.drop_table("supplier_returns")
