"""Add account status to identity users.

Revision ID: 0005_user_status
Revises: 0004_tenancy_rbac
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_user_status"
down_revision: str | None = "0004_tenancy_rbac"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add a persisted account state; existing users remain active."""
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(
            sa.Column(
                "status",
                sa.String(length=16),
                nullable=False,
                server_default="active",
            )
        )
        batch_op.create_check_constraint(
            "ck_users_status",
            "status IN ('active', 'suspended', 'disabled')",
        )


def downgrade() -> None:
    """Remove account status from users."""
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_constraint("ck_users_status", type_="check")
        batch_op.drop_column("status")
