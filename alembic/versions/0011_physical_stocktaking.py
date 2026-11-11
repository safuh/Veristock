# ruff: noqa: E501
"""Add physical stocktake snapshots, rounds and observations.

Revision ID: 0011_physical_stocktaking
Revises: 0010_sales_recording_permission
"""

from collections.abc import Sequence
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision: str = "0011_physical_stocktaking"
down_revision: str | None = "0010_sales_recording_permission"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "stocktakes",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("branch_id", sa.String(36), nullable=False),
        sa.Column("reference", sa.String(80), nullable=False),
        sa.Column("blind_count", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_by_user_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("status IN ('open', 'submitted', 'cancelled')", name="ck_stocktakes_status"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_stocktakes_org_branch_status",
        "stocktakes",
        ["organization_id", "branch_id", "status"],
    )
    op.create_table(
        "stocktake_scope_items",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("stocktake_id", sa.String(36), nullable=False),
        sa.Column("item_id", sa.String(36), nullable=False),
        sa.Column("expected_quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("unit_code", sa.String(24), nullable=False),
        sa.CheckConstraint("expected_quantity >= 0", name="ck_stocktake_expected_nonnegative"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["stocktake_id"], ["stocktakes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["item_id"], ["inventory_items.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("stocktake_id", "item_id", name="uq_stocktake_scope_item"),
    )
    op.create_table(
        "stocktake_rounds",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("stocktake_id", sa.String(36), nullable=False),
        sa.Column("round_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("opened_by_user_id", sa.String(36), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("status IN ('open', 'submitted')", name="ck_stocktake_round_status"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["stocktake_id"], ["stocktakes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["opened_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("stocktake_id", "round_number", name="uq_stocktake_round_number"),
    )
    op.create_table(
        "stocktake_observations",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("stocktake_id", sa.String(36), nullable=False),
        sa.Column("round_id", sa.String(36), nullable=False),
        sa.Column("item_id", sa.String(36), nullable=False),
        sa.Column("counted_quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("unit_code", sa.String(24), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("counted_by_user_id", sa.String(36), nullable=False),
        sa.Column("counted_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("counted_quantity >= 0", name="ck_stocktake_count_nonnegative"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["stocktake_id"], ["stocktakes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["round_id"], ["stocktake_rounds.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["item_id"], ["inventory_items.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["counted_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("round_id", "item_id", name="uq_stocktake_observation_round_item"),
        sa.UniqueConstraint("organization_id", "idempotency_key", name="uq_stocktake_observation_idempotency"),
    )
    op.create_index(
        "ix_stocktake_observations_org_item",
        "stocktake_observations",
        ["organization_id", "item_id"],
    )

    bind = op.get_bind()
    permission_id = str(uuid4())
    bind.execute(
        sa.text(
            "INSERT INTO permissions (id, code, description) "
            "VALUES (:id, :code, :description)"
        ),
        {
            "id": permission_id,
            "code": "stocktake.manage",
            "description": "Create and manage physical stocktakes",
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
        sa.text("SELECT id FROM permissions WHERE code = 'stocktake.manage'")
    ).scalar_one_or_none()
    if permission_id is not None:
        bind.execute(sa.text("DELETE FROM role_permissions WHERE permission_id = :id"), {"id": permission_id})
        bind.execute(sa.text("DELETE FROM permissions WHERE id = :id"), {"id": permission_id})
    op.drop_index("ix_stocktake_observations_org_item", table_name="stocktake_observations")
    op.drop_table("stocktake_observations")
    op.drop_table("stocktake_rounds")
    op.drop_table("stocktake_scope_items")
    op.drop_index("ix_stocktakes_org_branch_status", table_name="stocktakes")
    op.drop_table("stocktakes")
