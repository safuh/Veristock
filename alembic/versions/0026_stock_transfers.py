"""Add controlled branch stock transfers.

Revision ID: 0026_stock_transfers
Revises: 0025_stocktake_batch_observations
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0026_stock_transfers"
down_revision: str | None = "0025_stocktake_batch_observations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "stock_transfers",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(36),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("reference", sa.String(80), nullable=False),
        sa.Column(
            "source_branch_id",
            sa.String(36),
            sa.ForeignKey("branches.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "destination_branch_id",
            sa.String(36),
            sa.ForeignKey("branches.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("note", sa.String(500), nullable=True),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column(
            "created_by_user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "dispatched_by_user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "received_by_user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("organization_id", "reference", name="uq_stock_transfers_reference"),
        sa.UniqueConstraint(
            "organization_id", "idempotency_key", name="uq_stock_transfers_idempotency"
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'dispatched', 'received', 'cancelled')",
            name="ck_stock_transfers_status",
        ),
        sa.CheckConstraint(
            "source_branch_id != destination_branch_id", name="ck_stock_transfers_distinct_branches"
        ),
    )
    op.create_index(
        "ix_stock_transfers_org_status", "stock_transfers", ["organization_id", "status"]
    )
    op.create_table(
        "stock_transfer_lines",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(36),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "transfer_id",
            sa.String(36),
            sa.ForeignKey("stock_transfers.id", ondelete="CASCADE"),
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
            nullable=True,
        ),
        sa.Column(
            "destination_batch_id",
            sa.String(36),
            sa.ForeignKey("inventory_batches.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("unit_code", sa.String(24), nullable=False),
        sa.UniqueConstraint(
            "transfer_id", "item_id", "batch_id", name="uq_stock_transfer_line_item_batch"
        ),
        sa.CheckConstraint("quantity > 0", name="ck_stock_transfer_lines_positive_quantity"),
    )
    with op.batch_alter_table("stock_movements") as batch:
        batch.drop_constraint("ck_stock_movements_source_type", type_="check")
        batch.create_check_constraint(
            "ck_stock_movements_source_type",
            "source_type IN ('opening_balance', 'sale', 'stocktake_adjustment', 'reversal', "
            "'manual_adjustment', 'batch_receipt', 'batch_issue', 'stock_transfer')",
        )


def downgrade() -> None:
    with op.batch_alter_table("stock_movements") as batch:
        batch.drop_constraint("ck_stock_movements_source_type", type_="check")
        batch.create_check_constraint(
            "ck_stock_movements_source_type",
            "source_type IN ('opening_balance', 'sale', 'stocktake_adjustment', 'reversal', "
            "'manual_adjustment', 'batch_receipt', 'batch_issue')",
        )
    op.drop_table("stock_transfer_lines")
    op.drop_index("ix_stock_transfers_org_status", table_name="stock_transfers")
    op.drop_table("stock_transfers")
