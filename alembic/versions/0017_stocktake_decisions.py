"""Persist stocktake recount and approval decisions.

Revision ID: 0017_stocktake_decisions
Revises: 0016_stocktake_approval
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017_stocktake_decisions"
down_revision: str | None = "0016_stocktake_approval"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "stocktake_decisions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("stocktake_id", sa.String(length=36), nullable=False),
        sa.Column("round_id", sa.String(length=36), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("reason_code", sa.String(length=40), nullable=True),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column("actor_user_id", sa.String(length=36), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "action IN ('recount_requested', 'approved')",
            name="ck_stocktake_decisions_action",
        ),
        sa.CheckConstraint(
            "(action = 'recount_requested' AND reason_code IS NOT NULL AND reason IS NOT NULL) "
            "OR (action = 'approved' AND reason_code IS NULL AND reason IS NULL)",
            name="ck_stocktake_decisions_reason",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["stocktake_id"], ["stocktakes.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["round_id"], ["stocktake_rounds.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_stocktake_decisions_org_stocktake_created",
        "stocktake_decisions",
        ["organization_id", "stocktake_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_stocktake_decisions_org_stocktake_created",
        table_name="stocktake_decisions",
    )
    op.drop_table("stocktake_decisions")
