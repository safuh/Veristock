"""Add organizations, memberships and role-based authorization.

Revision ID: 0004_tenancy_rbac
Revises: 0003_refresh_tokens
"""

from collections.abc import Sequence
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision: str = "0004_tenancy_rbac"
down_revision: str | None = "0003_refresh_tokens"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


PERMISSIONS = {
    "organization.read": "View organization profile",
    "organization.manage": "Manage organization profile and access",
    "branch.read": "View organization branches",
    "branch.manage": "Manage organization branches",
    "employee.read": "View employee profiles",
    "employee.manage": "Manage employee profiles",
    "employee.invite": "Invite organization members",
    "assignment.read": "View assignments",
    "assignment.manage": "Create and manage assignments",
    "assignment.assign": "Assign employees to work",
    "inventory.read": "View inventory records",
    "inventory.import": "Import expected inventory",
    "inventory.manage": "Manage inventory catalogue",
    "stocktake.read": "View stocktakes",
    "stocktake.count": "Record physical counts",
    "stocktake.submit": "Submit count rounds",
    "stocktake.recount": "Request or perform recounts",
    "reconciliation.run": "Run inventory reconciliation",
    "reconciliation.review": "Review reconciliation exceptions",
    "reconciliation.approve": "Approve reconciliation results",
    "asset.read": "View fixed asset records",
    "asset.manage": "Manage fixed asset register",
    "asset.verify": "Perform physical asset verification",
    "report.read": "View approved reports",
    "report.generate": "Generate draft reports",
    "report.approve": "Approve reports",
    "report.publish": "Publish reports to clients",
    "billing.manage": "Manage invoices and payment records",
}

ROLE_PERMISSIONS = {
    "platform_owner": list(PERMISSIONS),
    "operations_manager": [
        "organization.read", "organization.manage", "branch.read", "branch.manage",
        "employee.read", "employee.manage", "employee.invite", "assignment.read",
        "assignment.manage", "assignment.assign", "inventory.read", "inventory.import",
        "inventory.manage", "stocktake.read", "stocktake.recount", "reconciliation.run",
        "reconciliation.review", "asset.read", "asset.manage", "asset.verify",
        "report.read", "report.generate", "report.approve", "report.publish",
    ],
    "stocktaking_supervisor": [
        "organization.read", "branch.read", "employee.read", "assignment.read",
        "assignment.assign", "inventory.read", "stocktake.read", "stocktake.recount",
        "reconciliation.run", "reconciliation.review", "reconciliation.approve",
        "asset.read", "asset.verify", "report.read", "report.generate", "report.approve",
    ],
    "field_employee": [
        "assignment.read", "stocktake.read", "stocktake.count", "stocktake.submit",
        "asset.read", "asset.verify",
    ],
    "finance_officer": [
        "organization.read", "report.read", "billing.manage",
    ],
    "client_admin": [
        "organization.read", "organization.manage", "branch.read", "branch.manage",
        "inventory.read", "inventory.import", "inventory.manage", "assignment.read",
        "stocktake.read", "report.read",
    ],
    "client_manager": [
        "organization.read", "branch.read", "inventory.read", "inventory.import",
        "assignment.read", "stocktake.read", "report.read",
    ],
    "client_reviewer": [
        "organization.read", "branch.read", "assignment.read", "stocktake.read",
        "reconciliation.review", "report.read",
    ],
    "client_readonly": [
        "organization.read", "branch.read", "inventory.read", "assignment.read",
        "stocktake.read", "report.read", "asset.read",
    ],
    "field_counter": [
        "assignment.read", "stocktake.read", "stocktake.count", "stocktake.submit",
        "asset.verify",
    ],
}

ROLES = {
    "platform_owner": ("Platform Owner", "platform"),
    "operations_manager": ("Operations Manager", "platform"),
    "stocktaking_supervisor": ("Stocktaking Supervisor", "platform"),
    "field_employee": ("Field Employee", "platform"),
    "finance_officer": ("Finance Officer", "platform"),
    "client_admin": ("Client Administrator", "client"),
    "client_manager": ("Client Manager", "client"),
    "client_reviewer": ("Client Reviewer", "client"),
    "client_readonly": ("Client Read-only", "client"),
    "field_counter": ("Field Counter", "client"),
}


def upgrade() -> None:
    """Create tenant and RBAC tables and seed stable permission/role codes."""
    op.create_table(
        "organizations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("legal_name", sa.String(length=240), nullable=False),
        sa.Column("trading_name", sa.String(length=240), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("kind IN ('platform', 'client')", name="ck_organizations_kind"),
        sa.CheckConstraint(
            "status IN ('active', 'suspended', 'archived')",
            name="ck_organizations_status",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_organizations_kind_status", "organizations", ["kind", "status"])

    op.create_table(
        "organization_memberships",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('invited', 'active', 'suspended', 'revoked')",
            name="ck_memberships_status",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "user_id", name="uq_membership_org_user"),
    )
    op.create_index(
        "ix_memberships_user_status",
        "organization_memberships",
        ["user_id", "status"],
    )
    op.create_index(
        "ix_memberships_org_status",
        "organization_memberships",
        ["organization_id", "status"],
    )

    op.create_table(
        "roles",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("code", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("scope", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("scope IN ('platform', 'client')", name="ck_roles_scope"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", name="uq_roles_code"),
    )

    op.create_table(
        "permissions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("code", sa.String(length=100), nullable=False),
        sa.Column("description", sa.String(length=240), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", name="uq_permissions_code"),
    )

    op.create_table(
        "membership_roles",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("membership_id", sa.String(length=36), nullable=False),
        sa.Column("role_id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(
            ["membership_id"], ["organization_memberships.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("membership_id", "role_id", name="uq_membership_role"),
    )

    op.create_table(
        "role_permissions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("role_id", sa.String(length=36), nullable=False),
        sa.Column("permission_id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["permission_id"], ["permissions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("role_id", "permission_id", name="uq_role_permission"),
    )

    bind = op.get_bind()
    permission_ids: dict[str, str] = {}
    for code, description in PERMISSIONS.items():
        permission_id = str(uuid4())
        permission_ids[code] = permission_id
        bind.execute(
            sa.text(
                "INSERT INTO permissions (id, code, description) "
                "VALUES (:id, :code, :description)"
            ),
            {"id": permission_id, "code": code, "description": description},
        )

    for code, (name, scope) in ROLES.items():
        role_id = str(uuid4())
        bind.execute(
            sa.text(
                "INSERT INTO roles (id, code, name, scope) "
                "VALUES (:id, :code, :name, :scope)"
            ),
            {"id": role_id, "code": code, "name": name, "scope": scope},
        )
        for permission_code in ROLE_PERMISSIONS[code]:
            bind.execute(
                sa.text(
                    "INSERT INTO role_permissions (id, role_id, permission_id) "
                    "VALUES (:id, :role_id, :permission_id)"
                ),
                {
                    "id": str(uuid4()),
                    "role_id": role_id,
                    "permission_id": permission_ids[permission_code],
                },
            )


def downgrade() -> None:
    """Remove seeded authorization data and tenancy tables."""
    op.drop_table("role_permissions")
    op.drop_table("membership_roles")
    op.drop_table("permissions")
    op.drop_table("roles")
    op.drop_index("ix_memberships_org_status", table_name="organization_memberships")
    op.drop_index("ix_memberships_user_status", table_name="organization_memberships")
    op.drop_table("organization_memberships")
    op.drop_index("ix_organizations_kind_status", table_name="organizations")
    op.drop_table("organizations")
