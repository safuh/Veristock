"""Allow audited stocktake rejection decisions.

Revision ID: 0018_stocktake_rejection
Revises: 0017_stocktake_decisions
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0018_stocktake_rejection"
down_revision: str | None = "0017_stocktake_decisions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("stocktake_decisions") as batch_op:
        batch_op.drop_constraint("ck_stocktake_decisions_action", type_="check")
        batch_op.drop_constraint("ck_stocktake_decisions_reason", type_="check")
        batch_op.create_check_constraint(
            "ck_stocktake_decisions_action",
            "action IN ('recount_requested', 'rejected', 'approved')",
        )
        batch_op.create_check_constraint(
            "ck_stocktake_decisions_reason",
            "(action = 'recount_requested' AND reason_code IS NOT NULL AND reason IS NOT NULL) "
            "OR (action = 'rejected' AND reason_code IS NOT NULL AND reason IS NOT NULL) "
            "OR (action = 'approved' AND reason_code IS NULL AND reason IS NULL)",
        )


def downgrade() -> None:
    with op.batch_alter_table("stocktake_decisions") as batch_op:
        batch_op.drop_constraint("ck_stocktake_decisions_reason", type_="check")
        batch_op.drop_constraint("ck_stocktake_decisions_action", type_="check")
        batch_op.create_check_constraint(
            "ck_stocktake_decisions_action",
            "action IN ('recount_requested', 'approved')",
        )
        batch_op.create_check_constraint(
            "ck_stocktake_decisions_reason",
            "(action = 'recount_requested' AND reason_code IS NOT NULL AND reason IS NOT NULL) "
            "OR (action = 'approved' AND reason_code IS NULL AND reason IS NULL)",
        )
