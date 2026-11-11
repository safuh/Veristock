"""Add single-use organization invitations.
# ruff: noqa: E501

Revision ID: 0007_organization_invitations
Revises: 0006_organization_workforce
"""

from collections.abc import Sequence
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision: str = "0007_organization_invitations"
down_revision: str | None = "0006_organization_workforce"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create invitation storage and allow client admins to invite users."""
    op.create_table(
        "organization_invitations",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("role_id", sa.String(36), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("invited_by_user_id", sa.String(36), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["invited_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_org_invitations_token_hash"),
    )
    op.create_index("ix_org_invitations_org_email", "organization_invitations", ["organization_id", "email"])
    op.create_index("ix_org_invitations_expires", "organization_invitations", ["expires_at"])

    bind = op.get_bind()
    client_admin = bind.execute(
        sa.text("SELECT id FROM roles WHERE code = 'client_admin' AND scope = 'client'")
    ).scalar_one()
    invite_permission = bind.execute(
        sa.text("SELECT id FROM permissions WHERE code = 'employee.invite'")
    ).scalar_one()
    existing = bind.execute(
        sa.text(
            "SELECT id FROM role_permissions "
            "WHERE role_id = :role_id AND permission_id = :permission_id"
        ),
        {"role_id": client_admin, "permission_id": invite_permission},
    ).scalar_one_or_none()
    if existing is None:
        bind.execute(
            sa.text(
                "INSERT INTO role_permissions (id, role_id, permission_id) "
                "VALUES (:id, :role_id, :permission_id)"
            ),
            {"id": str(uuid4()), "role_id": client_admin, "permission_id": invite_permission},
        )


def downgrade() -> None:
    """Remove invitation storage and the client-admin invitation grant."""
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "DELETE FROM role_permissions WHERE role_id = "
            "(SELECT id FROM roles WHERE code = 'client_admin' AND scope = 'client') "
            "AND permission_id = (SELECT id FROM permissions WHERE code = 'employee.invite')"
        )
    )
    op.drop_index("ix_org_invitations_expires", table_name="organization_invitations")
    op.drop_index("ix_org_invitations_org_email", table_name="organization_invitations")
    op.drop_table("organization_invitations")
