"""Add explicit tenant-scoped staff-to-branch assignments.

Revision ID: 0020_branch_memberships
Revises: 0019_stocktake_evidence
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020_branch_memberships"
down_revision: str | None = "0019_stocktake_evidence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create branch assignments and grant client administrators management access."""
    op.create_table(
        "branch_memberships",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("branch_id", sa.String(36), nullable=False),
        sa.Column("membership_id", sa.String(36), nullable=False),
        sa.Column("assigned_by_user_id", sa.String(36), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["membership_id"], ["organization_memberships.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["assigned_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("branch_id", "membership_id", name="uq_branch_membership"),
    )
    op.create_index(
        "ix_branch_memberships_org_membership",
        "branch_memberships",
        ["organization_id", "membership_id"],
    )
    op.create_index(
        "ix_branch_memberships_org_branch",
        "branch_memberships",
        ["organization_id", "branch_id"],
    )
    bind = op.get_bind()
    permission_id = bind.execute(
        sa.text("SELECT id FROM permissions WHERE code = 'assignment.manage'")
    ).scalar_one_or_none()
    role_id = bind.execute(
        sa.text("SELECT id FROM roles WHERE code = 'client_admin'")
    ).scalar_one_or_none()
    if permission_id is not None and role_id is not None:
        exists = bind.execute(
            sa.text(
                "SELECT id FROM role_permissions "
                "WHERE role_id = :role_id AND permission_id = :permission_id"
            ),
            {"role_id": role_id, "permission_id": permission_id},
        ).scalar_one_or_none()
        if exists is None:
            bind.execute(
                sa.text(
                    "INSERT INTO role_permissions (id, role_id, permission_id) "
                    "VALUES (lower(hex(randomblob(16))), :role_id, :permission_id)"
                ),
                {"role_id": role_id, "permission_id": permission_id},
            )


def downgrade() -> None:
    """Remove branch assignment capability."""
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "DELETE FROM role_permissions WHERE permission_id = "
            "(SELECT id FROM permissions WHERE code = 'assignment.manage') "
            "AND role_id = (SELECT id FROM roles WHERE code = 'client_admin')"
        )
    )
    op.drop_index("ix_branch_memberships_org_branch", table_name="branch_memberships")
    op.drop_index("ix_branch_memberships_org_membership", table_name="branch_memberships")
    op.drop_table("branch_memberships")
