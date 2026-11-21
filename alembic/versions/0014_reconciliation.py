"""Add immutable reconciliation runs, lines and approval decisions.

Revision ID: 0014_reconciliation
Revises: 0013_client_stocktake_submit
"""

from collections.abc import Sequence
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision: str = "0014_reconciliation"
down_revision: str | None = "0013_client_stocktake_submit"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "stock_balances",
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "stocktake_scope_items",
        sa.Column("expected_balance_version", sa.Integer(), nullable=False, server_default="0"),
    )
    op.execute(
        sa.text(
            "UPDATE stocktake_scope_items "
            "SET expected_balance_version = COALESCE(("
            "SELECT stock_balances.version "
            "FROM stock_balances "
            "JOIN stocktakes ON stocktakes.id = stocktake_scope_items.stocktake_id "
            "AND stocktakes.organization_id = stock_balances.organization_id "
            "AND stocktakes.branch_id = stock_balances.branch_id "
            "WHERE stock_balances.organization_id = stocktake_scope_items.organization_id "
            "AND stock_balances.item_id = stocktake_scope_items.item_id"
            "), 0)"
        )
    )

    op.create_table(
        "reconciliation_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(36),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "stocktake_id",
            sa.String(36),
            sa.ForeignKey("stocktakes.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "round_id",
            sa.String(36),
            sa.ForeignKey("stocktake_rounds.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column(
            "calculated_by_user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "calculated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "decided_by_user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT")
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.Column("decision_note", sa.String(1000)),
        sa.CheckConstraint(
            "status IN ('calculated', 'approved', 'rejected')", name="ck_reconciliation_runs_status"
        ),
        sa.CheckConstraint("version >= 1", name="ck_reconciliation_runs_version"),
        sa.UniqueConstraint("stocktake_id", "version", name="uq_reconciliation_stocktake_version"),
        sa.UniqueConstraint("stocktake_id", "round_id", name="uq_reconciliation_stocktake_round"),
    )
    op.create_index(
        "ix_reconciliation_runs_org_status", "reconciliation_runs", ["organization_id", "status"]
    )

    op.create_table(
        "reconciliation_lines",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(36),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "run_id",
            sa.String(36),
            sa.ForeignKey("reconciliation_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "item_id",
            sa.String(36),
            sa.ForeignKey("inventory_items.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("expected_quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("physical_quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("variance_quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("unit_code", sa.String(24), nullable=False),
        sa.Column("classification", sa.String(16), nullable=False),
        sa.CheckConstraint("expected_quantity >= 0", name="ck_reconciliation_expected_nonnegative"),
        sa.CheckConstraint("physical_quantity >= 0", name="ck_reconciliation_physical_nonnegative"),
        sa.CheckConstraint(
            "variance_quantity = physical_quantity - expected_quantity",
            name="ck_reconciliation_variance_consistent",
        ),
        sa.CheckConstraint(
            "classification IN ('matched', 'shortage', 'surplus')",
            name="ck_reconciliation_line_classification",
        ),
        sa.UniqueConstraint("run_id", "item_id", name="uq_reconciliation_line_run_item"),
    )
    op.create_index(
        "ix_reconciliation_lines_org_item", "reconciliation_lines", ["organization_id", "item_id"]
    )

    bind = op.get_bind()
    permission_ids = bind.execute(
        sa.text(
            "SELECT id FROM permissions "
            "WHERE code IN ('reconciliation.run', 'reconciliation.approve')"
        )
    ).scalars()
    reviewer_role_id = bind.execute(
        sa.text("SELECT id FROM roles WHERE code = 'client_reviewer'")
    ).scalar_one()
    for permission_id in permission_ids:
        bind.execute(
            sa.text(
                "INSERT INTO role_permissions (id, role_id, permission_id) "
                "VALUES (:id, :role_id, :permission_id)"
            ),
            {
                "id": str(uuid4()),
                "role_id": reviewer_role_id,
                "permission_id": permission_id,
            },
        )

    op.create_table(
        "reconciliation_approvals",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(36),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "run_id",
            sa.String(36),
            sa.ForeignKey("reconciliation_runs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column(
            "decided_by_user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("note", sa.String(1000)),
        sa.Column(
            "decided_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "decision IN ('approved', 'rejected')", name="ck_reconciliation_approval_decision"
        ),
        sa.UniqueConstraint("run_id", name="uq_reconciliation_approval_run"),
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "DELETE FROM role_permissions WHERE role_id = "
            "(SELECT id FROM roles WHERE code = 'client_reviewer') "
            "AND permission_id IN "
            "(SELECT id FROM permissions "
            "WHERE code IN ('reconciliation.run', 'reconciliation.approve'))"
        )
    )
    op.drop_table("reconciliation_approvals")
    with op.batch_alter_table("stocktake_scope_items") as batch_op:
        batch_op.drop_column("expected_balance_version")
    with op.batch_alter_table("stock_balances") as batch_op:
        batch_op.drop_column("version")
    op.drop_index("ix_reconciliation_lines_org_item", table_name="reconciliation_lines")
    op.drop_table("reconciliation_lines")
    op.drop_index("ix_reconciliation_runs_org_status", table_name="reconciliation_runs")
    op.drop_table("reconciliation_runs")
