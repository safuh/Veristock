"""Grant client administrators organization member invitation access.

Revision ID: 0021_client_admin_member_invite
Revises: 0020_branch_memberships
"""

from collections.abc import Sequence
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision: str = "0021_client_admin_member_invite"
down_revision: str | None = "0020_branch_memberships"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Allow client administrators to manage tenant membership invitations."""
    bind = op.get_bind()
    permission_id = bind.execute(
        sa.text("SELECT id FROM permissions WHERE code = 'employee.invite'")
    ).scalar_one_or_none()
    role_id = bind.execute(
        sa.text("SELECT id FROM roles WHERE code = 'client_admin' AND scope = 'client'")
    ).scalar_one_or_none()
    if permission_id is None or role_id is None:
        raise RuntimeError("Required employee.invite permission or client_admin role is missing")
    existing = bind.execute(
        sa.text(
            "SELECT id FROM role_permissions "
            "WHERE role_id = :role_id AND permission_id = :permission_id"
        ),
        {"role_id": role_id, "permission_id": permission_id},
    ).scalar_one_or_none()
    if existing is None:
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
    """Revoke the client-admin invitation grant introduced by this revision."""
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "DELETE FROM role_permissions WHERE role_id = "
            "(SELECT id FROM roles WHERE code = 'client_admin' AND scope = 'client') "
            "AND permission_id = "
            "(SELECT id FROM permissions WHERE code = 'employee.invite')"
        )
    )
