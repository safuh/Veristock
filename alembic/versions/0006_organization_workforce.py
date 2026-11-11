# ruff: noqa: E501
"""Add tenant branches, contacts and internal employee profiles.
Revision ID: 0006_organization_workforce
Revises: 0005_user_status
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_organization_workforce"
down_revision: str | None = "0005_user_status"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None



def upgrade() -> None:
    """Create branch, contact and employee profile tables."""
    op.create_table(
        "branches",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("code", sa.String(40), nullable=False),
        sa.Column("name", sa.String(180), nullable=False),
        sa.Column("address_line_1", sa.String(240)),
        sa.Column("address_line_2", sa.String(240)),
        sa.Column("town", sa.String(120)),
        sa.Column("county", sa.String(120)),
        sa.Column("postal_code", sa.String(24)),
        sa.Column("phone", sa.String(40)),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("status IN ('active', 'inactive')", name="ck_branches_status"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "code", name="uq_branches_org_code"),
    )
    op.create_index("ix_branches_org_status", "branches", ["organization_id", "status"])
    op.create_table(
        "organization_contacts",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("full_name", sa.String(180), nullable=False),
        sa.Column("title", sa.String(120)),
        sa.Column("email", sa.String(320)),
        sa.Column("phone", sa.String(40)),
        sa.Column("is_primary", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("status IN ('active', 'inactive')", name="ck_contacts_status"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_contacts_org_status", "organization_contacts", ["organization_id", "status"])
    op.create_table(
        "employee_profiles",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("employee_number", sa.String(40), nullable=False),
        sa.Column("display_name", sa.String(180), nullable=False),
        sa.Column("phone", sa.String(40)),
        sa.Column("job_title", sa.String(120)),
        sa.Column("hire_date", sa.Date()),
        sa.Column("employment_status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("employment_status IN ('active', 'suspended', 'terminated')", name="ck_employee_profiles_status"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_employee_profiles_user"),
        sa.UniqueConstraint("employee_number", name="uq_employee_profiles_number"),
    )
    op.create_index("ix_employee_profiles_org_status", "employee_profiles", ["organization_id", "employment_status"])



def downgrade() -> None:
    """Remove workforce and organization administration tables."""
    op.drop_index("ix_employee_profiles_org_status", table_name="employee_profiles")
    op.drop_table("employee_profiles")
    op.drop_index("ix_contacts_org_status", table_name="organization_contacts")
    op.drop_table("organization_contacts")
    op.drop_index("ix_branches_org_status", table_name="branches")
    op.drop_table("branches")
