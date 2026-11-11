"""Add tenant-scoped inventory catalogue, sales and stock movement ledger.

Revision ID: 0008_inventory_sales_ledger
Revises: 0007_organization_invitations
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_inventory_sales_ledger"
down_revision: str | None = "0007_organization_invitations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create inventory catalogue, balance projection and immutable movement records."""
    op.create_table(
        "inventory_items",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("sku", sa.String(80)),
        sa.Column("barcode", sa.String(128)),
        sa.Column("name", sa.String(240), nullable=False),
        sa.Column("description", sa.String(1000)),
        sa.Column("base_unit_code", sa.String(24), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('active', 'inactive')", name="ck_inventory_items_status"
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id", "sku", name="uq_inventory_items_org_sku"
        ),
        sa.UniqueConstraint(
            "organization_id", "barcode", name="uq_inventory_items_org_barcode"
        ),
    )
    op.create_index(
        "ix_inventory_items_org_name", "inventory_items", ["organization_id", "name"]
    )

    op.create_table(
        "stock_balances",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("branch_id", sa.String(36), nullable=False),
        sa.Column("item_id", sa.String(36), nullable=False),
        sa.Column("quantity_on_hand", sa.Numeric(18, 4), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "quantity_on_hand >= 0", name="ck_stock_balances_nonnegative"
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["branch_id"], ["branches.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["item_id"], ["inventory_items.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "branch_id",
            "item_id",
            name="uq_stock_balances_scope_item",
        ),
    )
    op.create_index(
        "ix_stock_balances_org_branch",
        "stock_balances",
        ["organization_id", "branch_id"],
    )

    op.create_table(
        "stock_movements",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("branch_id", sa.String(36), nullable=False),
        sa.Column("item_id", sa.String(36), nullable=False),
        sa.Column("quantity_delta", sa.Numeric(18, 4), nullable=False),
        sa.Column("unit_code", sa.String(24), nullable=False),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("source_id", sa.String(36)),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("actor_user_id", sa.String(36), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "quantity_delta != 0", name="ck_stock_movements_nonzero"
        ),
        sa.CheckConstraint(
            "source_type IN ('opening_balance', 'sale', 'stocktake_adjustment', "
            "'reversal', 'manual_adjustment')",
            name="ck_stock_movements_source_type",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["branch_id"], ["branches.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["item_id"], ["inventory_items.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "idempotency_key",
            name="uq_stock_movements_idempotency",
        ),
    )
    op.create_index(
        "ix_stock_movements_org_branch_time",
        "stock_movements",
        ["organization_id", "branch_id", "occurred_at"],
    )
    op.create_index(
        "ix_stock_movements_org_item_time",
        "stock_movements",
        ["organization_id", "item_id", "occurred_at"],
    )

    op.create_table(
        "sales",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("branch_id", sa.String(36), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("reference", sa.String(80)),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("recorded_by_user_id", sa.String(36), nullable=False),
        sa.Column(
            "posted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('posted', 'reversed')", name="ck_sales_status"
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["branch_id"], ["branches.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["recorded_by_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id", "idempotency_key", name="uq_sales_idempotency"
        ),
    )
    op.create_index(
        "ix_sales_org_branch_posted", "sales", ["organization_id", "branch_id", "posted_at"]
    )

    op.create_table(
        "sale_lines",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("sale_id", sa.String(36), nullable=False),
        sa.Column("item_id", sa.String(36), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("unit_code", sa.String(24), nullable=False),
        sa.Column("unit_price", sa.Numeric(18, 4)),
        sa.Column("currency", sa.String(3)),
        sa.CheckConstraint(
            "quantity > 0", name="ck_sale_lines_positive_quantity"
        ),
        sa.CheckConstraint(
            "(unit_price IS NULL AND currency IS NULL) OR "
            "(unit_price >= 0 AND currency IS NOT NULL)",
            name="ck_sale_lines_price_currency_pair",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["sale_id"], ["sales.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["item_id"], ["inventory_items.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sale_lines_sale", "sale_lines", ["sale_id"])
    op.create_index(
        "ix_sale_lines_org_item", "sale_lines", ["organization_id", "item_id"]
    )


def downgrade() -> None:
    """Remove the inventory ledger in dependency order."""
    op.drop_index("ix_sale_lines_org_item", table_name="sale_lines")
    op.drop_index("ix_sale_lines_sale", table_name="sale_lines")
    op.drop_table("sale_lines")
    op.drop_index("ix_sales_org_branch_posted", table_name="sales")
    op.drop_table("sales")
    op.drop_index("ix_stock_movements_org_item_time", table_name="stock_movements")
    op.drop_index("ix_stock_movements_org_branch_time", table_name="stock_movements")
    op.drop_table("stock_movements")
    op.drop_index("ix_stock_balances_org_branch", table_name="stock_balances")
    op.drop_table("stock_balances")
    op.drop_index("ix_inventory_items_org_name", table_name="inventory_items")
    op.drop_table("inventory_items")
