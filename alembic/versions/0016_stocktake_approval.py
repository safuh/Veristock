"""Add separately authorized stocktake approval and ledger reconciliation.

Revision ID: 0016_stocktake_approval
Revises: 0015_replenishment_policies
"""

from collections.abc import Sequence
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision: str = "0016_stocktake_approval"
down_revision: str | None = "0015_replenishment_policies"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_stocktakes_status", "stocktakes", type_="check")
    op.create_check_constraint(
        "ck_stocktakes_status",
        "stocktakes",
        "status IN ('open', 'submitted', 'cancelled', 'completed')",
    )
    op.add_column(
        "stocktakes",
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "stocktakes",
        sa.Column("approved_by_user_id", sa.String(length=36), nullable=True),
    )
    op.create_foreign_key(
        "fk_stocktakes_approved_by_user_id_users",
        "stocktakes",
        "users",
        ["approved_by_user_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    bind = op.get_bind()
    permission_id = str(uuid4())
    bind.execute(
        sa.text(
            "INSERT INTO permissions (id, code, description) "
            "VALUES (:id, :code, :description)"
        ),
        {
            "id": permission_id,
            "code": "stocktake.approve",
            "description": "Approve submitted stocktakes and reconcile stock balances",
        },
    )
    role_id = bind.execute(
        sa.text("SELECT id FROM roles WHERE code = 'client_admin'")
    ).scalar_one_or_none()
    if role_id is not None:
        bind.execute(
            sa.text(
                "INSERT INTO role_permissions (id, role_id, permission_id) "
                "VALUES (:id, :role_id, :permission_id)"
            ),
            {
                "id": str(uuid4()),
                "role_id": role_id,
                "permission_id": permission_id,
            },
        )


def downgrade() -> None:
    bind = op.get_bind()
    permission_id = bind.execute(
        sa.text("SELECT id FROM permissions WHERE code = 'stocktake.approve'")
    ).scalar_one_or_none()
    if permission_id is not None:
        bind.execute(
            sa.text("DELETE FROM role_permissions WHERE permission_id = :id"),
            {"id": permission_id},
        )
        bind.execute(
            sa.text("DELETE FROM permissions WHERE id = :id"),
            {"id": permission_id},
        )
    op.drop_constraint(
        "fk_stocktakes_approved_by_user_id_users", "stocktakes", type_="foreignkey"
    )
    op.drop_column("stocktakes", "approved_by_user_id")
    op.drop_column("stocktakes", "completed_at")
    op.drop_constraint("ck_stocktakes_status", "stocktakes", type_="check")
    op.create_check_constraint(
        "ck_stocktakes_status",
        "stocktakes",
        "status IN ('open', 'submitted', 'cancelled')",
    )
