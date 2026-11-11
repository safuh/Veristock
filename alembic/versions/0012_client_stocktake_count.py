"""Allow client administrators and managers to perform physical counts.

Revision ID: 0012_client_stocktake_count
Revises: 0011_physical_stocktaking
"""

from collections.abc import Sequence
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision: str = "0012_client_stocktake_count"
down_revision: str | None = "0011_physical_stocktaking"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    permission_id = bind.execute(
        sa.text("SELECT id FROM permissions WHERE code = 'stocktake.count'")
    ).scalar_one()
    role_ids = bind.execute(
        sa.text(
            "SELECT id FROM roles "
            "WHERE code IN ('client_admin', 'client_manager')"
        )
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
    bind.execute(
        sa.text(
            "DELETE FROM role_permissions WHERE permission_id = "
            "(SELECT id FROM permissions WHERE code = 'stocktake.count') "
            "AND role_id IN (SELECT id FROM roles WHERE code IN ('client_admin', 'client_manager'))"
        )
    )
