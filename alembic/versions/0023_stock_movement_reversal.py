"""Enforce one compensating reversal per stock movement.

Revision ID: 0023_stock_movement_reversal
Revises: 0022_stock_movement_reason
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023_stock_movement_reversal"
down_revision: str | None = "0022_stock_movement_reason"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add a unique reference from a compensating movement to its original."""
    with op.batch_alter_table("stock_movements") as batch_op:
        batch_op.add_column(
            sa.Column("reversal_of_movement_id", sa.String(length=36), nullable=True)
        )
        batch_op.create_unique_constraint(
            "uq_stock_movements_single_reversal",
            ["organization_id", "reversal_of_movement_id"],
        )


def downgrade() -> None:
    """Remove reversal linkage and its uniqueness guarantee."""
    with op.batch_alter_table("stock_movements") as batch_op:
        batch_op.drop_constraint("uq_stock_movements_single_reversal", type_="unique")
        batch_op.drop_column("reversal_of_movement_id")
