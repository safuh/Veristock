"""Persist human-readable reasons for manual stock adjustments.

Revision ID: 0022_stock_movement_reason
Revises: 0021_client_admin_member_invite
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022_stock_movement_reason"
down_revision: str | None = "0021_client_admin_member_invite"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add optional reason metadata to stock movement events."""
    op.add_column("stock_movements", sa.Column("reason", sa.String(length=500), nullable=True))


def downgrade() -> None:
    """Remove manual-adjustment reason metadata."""
    op.drop_column("stock_movements", "reason")
