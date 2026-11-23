"""Add tenant-scoped supplier directory and supplier item catalogue."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0027_supplier_directory"
down_revision: str | None = "0026_stock_transfers"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "suppliers",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(36),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("code", sa.String(40), nullable=False),
        sa.Column("name", sa.String(240), nullable=False),
        sa.Column("contact_name", sa.String(160)),
        sa.Column("email", sa.String(254)),
        sa.Column("phone", sa.String(40)),
        sa.Column("website", sa.String(300)),
        sa.Column("address", sa.String(1000)),
        sa.Column("tax_reference", sa.String(100)),
        sa.Column("payment_terms", sa.String(240)),
        sa.Column("default_currency", sa.String(3), nullable=False, server_default="KES"),
        sa.Column("notes", sa.String(1000)),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("organization_id", "code", name="uq_suppliers_org_code"),
        sa.CheckConstraint(
            "status IN ('active', 'inactive', 'blocked')", name="ck_suppliers_status"
        ),
    )
    op.create_index("ix_suppliers_org_name", "suppliers", ["organization_id", "name"])
    op.create_table(
        "supplier_items",
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
            sa.ForeignKey("suppliers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "item_id",
            sa.String(36),
            sa.ForeignKey("inventory_items.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("supplier_sku", sa.String(100)),
        sa.Column("unit_cost", sa.Numeric(18, 4), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="KES"),
        sa.Column("minimum_order_quantity", sa.Numeric(18, 4), nullable=False, server_default="1"),
        sa.Column("lead_time_days", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_preferred", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint(
            "organization_id", "supplier_id", "item_id", name="uq_supplier_items_scope"
        ),
        sa.CheckConstraint("unit_cost >= 0", name="ck_supplier_items_nonnegative_cost"),
        sa.CheckConstraint("minimum_order_quantity > 0", name="ck_supplier_items_positive_moq"),
        sa.CheckConstraint("lead_time_days >= 0", name="ck_supplier_items_nonnegative_lead_time"),
    )
    op.create_index("ix_supplier_items_org_item", "supplier_items", ["organization_id", "item_id"])


def downgrade() -> None:
    op.drop_index("ix_supplier_items_org_item", table_name="supplier_items")
    op.drop_table("supplier_items")
    op.drop_index("ix_suppliers_org_name", table_name="suppliers")
    op.drop_table("suppliers")
