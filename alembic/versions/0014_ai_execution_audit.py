"""Persist tenant-scoped AI execution metadata.

Revision ID: 0014_ai_execution_audit
Revises: 0013_client_stocktake_submit
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_ai_execution_audit"
down_revision: str | None = "0013_client_stocktake_submit"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ai_execution_records",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("operation", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("provider", sa.String(length=80), nullable=True),
        sa.Column("model", sa.String(length=160), nullable=True),
        sa.Column("model_version", sa.String(length=120), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("request_id", sa.String(length=128), nullable=True),
        sa.Column("source_references", sa.JSON(), nullable=False),
        sa.Column("failure_code", sa.String(length=80), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('succeeded', 'failed', 'unavailable')",
            name="ck_ai_execution_records_status",
        ),
        sa.CheckConstraint(
            "operation IN ('report_narrative')",
            name="ck_ai_execution_records_operation",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ai_execution_records_org_created",
        "ai_execution_records",
        ["organization_id", "created_at"],
    )
    op.create_index(
        "ix_ai_execution_records_user_created",
        "ai_execution_records",
        ["user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_ai_execution_records_user_created",
        table_name="ai_execution_records",
    )
    op.drop_index(
        "ix_ai_execution_records_org_created",
        table_name="ai_execution_records",
    )
    op.drop_table("ai_execution_records")
