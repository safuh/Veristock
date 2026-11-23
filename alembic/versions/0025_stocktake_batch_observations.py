"""Add batch-level stocktake observations.

Revision ID: 0025_stocktake_batch_observations
Revises: 0024_inventory_batches
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0025_stocktake_batch_observations"
down_revision: str | None = "0024_inventory_batches"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "stocktake_batch_observations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(36),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "stocktake_id",
            sa.String(36),
            sa.ForeignKey("stocktakes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "round_id",
            sa.String(36),
            sa.ForeignKey("stocktake_rounds.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "batch_id",
            sa.String(36),
            sa.ForeignKey("inventory_batches.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("counted_quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("observed_expiry_date", sa.Date(), nullable=True),
        sa.Column("observed_condition", sa.String(16), nullable=False, server_default="good"),
        sa.Column("note", sa.String(500), nullable=True),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column(
            "counted_by_user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "counted_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("round_id", "batch_id", name="uq_stocktake_batch_observation_round"),
        sa.UniqueConstraint(
            "organization_id", "idempotency_key", name="uq_stocktake_batch_observation_idempotency"
        ),
        sa.CheckConstraint("counted_quantity >= 0", name="ck_stocktake_batch_count_nonnegative"),
        sa.CheckConstraint(
            "observed_condition IN ('good', 'damaged', 'quarantined')",
            name="ck_stocktake_batch_condition",
        ),
    )
    op.create_index(
        "ix_stocktake_batch_observations_org_batch",
        "stocktake_batch_observations",
        ["organization_id", "batch_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_stocktake_batch_observations_org_batch", table_name="stocktake_batch_observations"
    )
    op.drop_table("stocktake_batch_observations")
