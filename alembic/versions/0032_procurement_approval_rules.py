"""Add currency-aware value-based procurement approval rules."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0032_procurement_approval_rules"
down_revision: str | None = "0031_requisition_purchase_order_link"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("purchase_requisitions") as batch_op:
        batch_op.add_column(
            sa.Column("currency", sa.String(3), nullable=False, server_default="KES")
        )
        batch_op.add_column(
            sa.Column("required_approvals", sa.Integer(), nullable=False, server_default="1")
        )
        batch_op.create_check_constraint(
            "ck_purchase_requisitions_required_approvals",
            "required_approvals BETWEEN 1 AND 5",
        )
    op.create_table(
        "procurement_approval_rules",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(36),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("minimum_total", sa.Numeric(18, 4), nullable=False),
        sa.Column("required_approvals", sa.Integer(), nullable=False),
        sa.Column(
            "created_by_user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint(
            "organization_id", "currency", "minimum_total", name="uq_procurement_approval_rule_band"
        ),
        sa.CheckConstraint("minimum_total >= 0", name="ck_procurement_approval_rule_nonnegative"),
        sa.CheckConstraint(
            "required_approvals BETWEEN 1 AND 5", name="ck_procurement_approval_rule_approvers"
        ),
    )
    op.create_index(
        "ix_procurement_approval_rules_org_currency",
        "procurement_approval_rules",
        ["organization_id", "currency"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_procurement_approval_rules_org_currency", table_name="procurement_approval_rules"
    )
    op.drop_table("procurement_approval_rules")
    with op.batch_alter_table("purchase_requisitions") as batch_op:
        batch_op.drop_constraint("ck_purchase_requisitions_required_approvals", type_="check")
        batch_op.drop_column("required_approvals")
        batch_op.drop_column("currency")
