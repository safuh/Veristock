# ruff: noqa: E501
"""Add sale-recording permission to client operational roles.

Revision ID: 0010_sales_recording_permission
Revises: 0009_organization_enrollments
"""

from collections.abc import Sequence
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision: str = "0010_sales_recording_permission"
down_revision: str | None = "0009_organization_enrollments"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    permission_id = str(uuid4())
    bind.execute(
        sa.text(
            "INSERT INTO permissions (id, code, description) "
            "VALUES (:id, :code, :description)"
        ),
        {
            "id": permission_id,
            "code": "sales.record",
            "description": "Record and view client sales",
        },
    )
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
    permission_id = bind.execute(
        sa.text("SELECT id FROM permissions WHERE code = 'sales.record'")
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
