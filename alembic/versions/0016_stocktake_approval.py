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
    with op.batch_alter_table("stocktakes") as batch_op:
        batch_op.drop_constraint("ck_stocktakes_status", type_="check")
        batch_op.create_check_constraint(
            "ck_stocktakes_status",
            "status IN ('open', 'submitted', 'cancelled', 'completed')",
        )
        batch_op.add_column(sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("approved_by_user_id", sa.String(length=36), nullable=True))
        batch_op.create_foreign_key(
            "fk_stocktakes_approved_by_user_id_users",
            "users",
            ["approved_by_user_id"],
            ["id"],
            ondelete="RESTRICT",
        )

    bind = op.get_bind()
    permission_id = str(uuid4())
    bind.execute(
        sa.text(
            "INSERT INTO permissions (id, code, description) VALUES (:id, :code, :description)"
        ),
        {
            "id": permission_id,
            "code": "stocktake.approve",
            "description": "Approve submitted stocktakes and reconcile stock balances",
        },
    )
    role_ids = bind.execute(
        sa.text("SELECT id FROM roles WHERE code IN ('client_admin', 'client_reviewer')")
    ).scalars()
    for role_id in role_ids:
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
    with op.batch_alter_table("stocktakes") as batch_op:
        batch_op.drop_constraint("fk_stocktakes_approved_by_user_id_users", type_="foreignkey")
        batch_op.drop_column("approved_by_user_id")
        batch_op.drop_column("completed_at")
        batch_op.drop_constraint("ck_stocktakes_status", type_="check")
        batch_op.create_check_constraint(
            "ck_stocktakes_status",
            "status IN ('open', 'submitted', 'cancelled')",
        )
