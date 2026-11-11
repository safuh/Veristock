"""Add business enrollment requests for client tenant provisioning.

Revision ID: 0009_organization_enrollments
Revises: 0008_inventory_sales_ledger
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_organization_enrollments"
down_revision: str | None = "0008_inventory_sales_ledger"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create enrollment workflow records without granting access before approval."""
    op.create_table(
        "organization_enrollments",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("requester_user_id", sa.String(36), nullable=False),
        sa.Column("legal_name", sa.String(240), nullable=False),
        sa.Column("trading_name", sa.String(240)),
        sa.Column("business_registration_number", sa.String(100)),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("contact_name", sa.String(180), nullable=False),
        sa.Column("contact_email", sa.String(320), nullable=False),
        sa.Column("contact_phone", sa.String(40)),
        sa.Column("business_description", sa.String(1000)),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("review_note", sa.String(1000)),
        sa.Column("organization_id", sa.String(36)),
        sa.Column("reviewed_by_user_id", sa.String(36)),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected')",
            name="ck_organization_enrollments_status",
        ),
        sa.ForeignKeyConstraint(
            ["requester_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_org_enrollments_status_created",
        "organization_enrollments",
        ["status", "created_at"],
    )
    op.create_index(
        "ix_org_enrollments_requester_status",
        "organization_enrollments",
        ["requester_user_id", "status"],
    )


def downgrade() -> None:
    """Remove business enrollment requests."""
    op.drop_index(
        "ix_org_enrollments_requester_status",
        table_name="organization_enrollments",
    )
    op.drop_index(
        "ix_org_enrollments_status_created",
        table_name="organization_enrollments",
    )
    op.drop_table("organization_enrollments")
