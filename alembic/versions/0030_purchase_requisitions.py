"""Add purchase requisitions and immutable approval decisions."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0030_purchase_requisitions"
down_revision: str | None = "0029_supplier_returns"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "purchase_requisitions",
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
        sa.Column("reference", sa.String(80), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("justification", sa.String(1000), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column(
            "requested_by_user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("submitted_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint(
            "organization_id", "reference", name="uq_purchase_requisitions_reference"
        ),
        sa.UniqueConstraint(
            "organization_id", "idempotency_key", name="uq_purchase_requisitions_idempotency"
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'submitted', 'approved', 'rejected', 'converted', 'cancelled')",
            name="ck_purchase_requisitions_status",
        ),
    )
    op.create_index(
        "ix_purchase_requisitions_org_status",
        "purchase_requisitions",
        ["organization_id", "status"],
    )
    op.create_table(
        "purchase_requisition_lines",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(36),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "requisition_id",
            sa.String(36),
            sa.ForeignKey("purchase_requisitions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "item_id",
            sa.String(36),
            sa.ForeignKey("inventory_items.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("unit_code", sa.String(24), nullable=False),
        sa.Column("estimated_unit_cost", sa.Numeric(18, 4)),
        sa.UniqueConstraint("requisition_id", "item_id", name="uq_purchase_requisition_line_item"),
        sa.CheckConstraint("quantity > 0", name="ck_purchase_requisition_lines_positive_quantity"),
    )
    op.create_table(
        "purchase_requisition_decisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(36),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "requisition_id",
            sa.String(36),
            sa.ForeignKey("purchase_requisitions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column(
            "actor_user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("reason", sa.String(1000)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "decision IN ('submitted', 'approved', 'rejected')",
            name="ck_purchase_requisition_decisions_decision",
        ),
    )
    op.create_index(
        "ix_purchase_requisition_decisions_org_req",
        "purchase_requisition_decisions",
        ["organization_id", "requisition_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_purchase_requisition_decisions_org_req", table_name="purchase_requisition_decisions"
    )
    op.drop_table("purchase_requisition_decisions")
    op.drop_table("purchase_requisition_lines")
    op.drop_index("ix_purchase_requisitions_org_status", table_name="purchase_requisitions")
    op.drop_table("purchase_requisitions")
