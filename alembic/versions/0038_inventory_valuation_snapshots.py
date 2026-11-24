"""Persist immutable point-in-time inventory valuation snapshots."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0038_inventory_valuation_snapshots"
down_revision: str | None = "0037_inventory_cost_restorations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "inventory_valuation_snapshots",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(36),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "captured_by_user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("line_count", sa.Integer(), nullable=False),
        sa.Column("valuation_status", sa.String(32), nullable=False),
        sa.Column("snapshot_data", sa.JSON(), nullable=False),
        sa.UniqueConstraint(
            "organization_id", "idempotency_key", name="uq_valuation_snapshot_idempotency"
        ),
    )
    op.create_index(
        "ix_valuation_snapshots_org_captured",
        "inventory_valuation_snapshots",
        ["organization_id", "captured_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_valuation_snapshots_org_captured", table_name="inventory_valuation_snapshots")
    op.drop_table("inventory_valuation_snapshots")
