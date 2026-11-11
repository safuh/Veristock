"""Grant count-round submission to client administrators and managers.

Revision ID: 0013_client_stocktake_submit
Revises: 0012_client_stocktake_count
"""

from collections.abc import Sequence
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision: str = "0013_client_stocktake_submit"
down_revision: str | None = "0012_client_stocktake_count"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    permission_id = bind.execute(
        sa.text("SELECT id FROM permissions WHERE code = 'stocktake.submit'")
    ).scalar_one()
    bind.execute(
        sa.text(
            "INSERT INTO role_permissions (id, role_id, permission_id) "
            "SELECT :id, r.id, :permission_id FROM roles r "
            "WHERE r.code IN ('client_admin', 'client_manager') "
            "AND NOT EXISTS (SELECT 1 FROM role_permissions rp "
            "WHERE rp.role_id = r.id AND rp.permission_id = :permission_id)"
        ),
        {"id": str(uuid4()), "permission_id": permission_id},
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "DELETE FROM role_permissions WHERE permission_id = "
            "(SELECT id FROM permissions WHERE code = 'stocktake.submit') "
            "AND role_id IN (SELECT id FROM roles WHERE code IN ('client_admin', 'client_manager'))"
        )
    )
