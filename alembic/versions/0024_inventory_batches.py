"""Add lot-level inventory and batch movement references.

Revision ID: 0024_inventory_batches
Revises: 0023_stock_movement_reversal
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0024_inventory_batches"
down_revision: str | None = "0023_stock_movement_reversal"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "inventory_batches",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(36),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "item_id",
            sa.String(36),
            sa.ForeignKey("inventory_items.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "branch_id",
            sa.String(36),
            sa.ForeignKey("branches.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("lot_code", sa.String(100), nullable=False),
        sa.Column("manufactured_date", sa.Date(), nullable=True),
        sa.Column("expiry_date", sa.Date(), nullable=True),
        sa.Column("supplier_reference", sa.String(120), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column(
            "received_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint(
            "organization_id",
            "item_id",
            "branch_id",
            "lot_code",
            name="uq_inventory_batches_scope_lot",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'quarantined', 'recalled', 'closed')",
            name="ck_inventory_batches_status",
        ),
        sa.CheckConstraint(
            "expiry_date IS NULL OR manufactured_date IS NULL OR expiry_date >= manufactured_date",
            name="ck_inventory_batches_dates",
        ),
    )
    op.create_index(
        "ix_inventory_batches_expiry",
        "inventory_batches",
        ["organization_id", "branch_id", "expiry_date"],
    )
    op.create_table(
        "batch_stock_balances",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(36),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "branch_id",
            sa.String(36),
            sa.ForeignKey("branches.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "item_id",
            sa.String(36),
            sa.ForeignKey("inventory_items.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "batch_id",
            sa.String(36),
            sa.ForeignKey("inventory_batches.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("quantity_on_hand", sa.Numeric(18, 4), nullable=False),
        sa.UniqueConstraint(
            "organization_id", "branch_id", "item_id", "batch_id", name="uq_batch_balance_scope"
        ),
        sa.CheckConstraint("quantity_on_hand >= 0", name="ck_batch_balance_nonnegative"),
    )
    op.create_index(
        "ix_batch_balance_item", "batch_stock_balances", ["organization_id", "branch_id", "item_id"]
    )
    with op.batch_alter_table("stock_movements") as batch:
        batch.drop_constraint("ck_stock_movements_source_type", type_="check")
        batch.create_check_constraint(
            "ck_stock_movements_source_type",
            "source_type IN ('opening_balance', 'sale', 'stocktake_adjustment', "
            "'reversal', 'manual_adjustment', 'batch_receipt', 'batch_issue')",
        )
        batch.add_column(sa.Column("batch_id", sa.String(36), nullable=True))
        batch.create_foreign_key(
            "fk_stock_movements_batch_id_inventory_batches",
            "inventory_batches",
            ["batch_id"],
            ["id"],
            ondelete="RESTRICT",
        )


def downgrade() -> None:
    with op.batch_alter_table("stock_movements") as batch:
        batch.drop_constraint("fk_stock_movements_batch_id_inventory_batches", type_="foreignkey")
        batch.drop_constraint("ck_stock_movements_source_type", type_="check")
        batch.create_check_constraint(
            "ck_stock_movements_source_type",
            "source_type IN ('opening_balance', 'sale', 'stocktake_adjustment', "
            "'reversal', 'manual_adjustment')",
        )
        batch.drop_column("batch_id")
    op.drop_index("ix_batch_balance_item", table_name="batch_stock_balances")
    op.drop_table("batch_stock_balances")
    op.drop_index("ix_inventory_batches_expiry", table_name="inventory_batches")
    op.drop_table("inventory_batches")
