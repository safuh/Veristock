"""Persist tenant-scoped branch/item replenishment assumptions.

Revision ID: 0015_replenishment_policies
Revises: 0014_ai_execution_audit
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015_replenishment_policies"
down_revision: str | None = "0014_ai_execution_audit"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "replenishment_policies",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("branch_id", sa.String(length=36), nullable=False),
        sa.Column("item_id", sa.String(length=36), nullable=False),
        sa.Column("lead_time_days", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("safety_stock_days", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_by_user_id", sa.String(length=36), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "lead_time_days BETWEEN 0 AND 180",
            name="ck_replenishment_policy_lead_time",
        ),
        sa.CheckConstraint(
            "safety_stock_days BETWEEN 0 AND 180",
            name="ck_replenishment_policy_safety_stock",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["item_id"], ["inventory_items.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "branch_id",
            "item_id",
            name="uq_replenishment_policy_scope_item",
        ),
    )
    op.create_index(
        "ix_replenishment_policies_org_branch",
        "replenishment_policies",
        ["organization_id", "branch_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_replenishment_policies_org_branch",
        table_name="replenishment_policies",
    )
    op.drop_table("replenishment_policies")
