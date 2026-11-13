"""Persist metadata for private stocktake image evidence.

Revision ID: 0019_stocktake_evidence
Revises: 0018_stocktake_rejection
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019_stocktake_evidence"
down_revision: str | None = "0018_stocktake_rejection"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "stocktake_evidence",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("stocktake_id", sa.String(length=36), nullable=False),
        sa.Column("round_id", sa.String(length=36), nullable=False),
        sa.Column("observation_id", sa.String(length=36), nullable=False),
        sa.Column("storage_key", sa.String(length=80), nullable=False),
        sa.Column("media_type", sa.String(length=32), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("sha256_digest", sa.String(length=64), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=True),
        sa.Column("uploaded_by_user_id", sa.String(length=36), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("byte_size > 0", name="ck_stocktake_evidence_size_positive"),
        sa.CheckConstraint(
            "media_type IN ('image/jpeg', 'image/png', 'image/webp')",
            name="ck_stocktake_evidence_media_type",
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
            ["observation_id"], ["stocktake_observations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("storage_key", name="uq_stocktake_evidence_storage_key"),
    )
    op.create_index(
        "ix_stocktake_evidence_org_stocktake",
        "stocktake_evidence",
        ["organization_id", "stocktake_id", "created_at"],
    )
    op.create_index(
        "ix_stocktake_evidence_observation",
        "stocktake_evidence",
        ["observation_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_stocktake_evidence_observation", table_name="stocktake_evidence")
    op.drop_index("ix_stocktake_evidence_org_stocktake", table_name="stocktake_evidence")
    op.drop_table("stocktake_evidence")
