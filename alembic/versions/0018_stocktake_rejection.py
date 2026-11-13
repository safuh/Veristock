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
    op.drop_constraint(
        "ck_stocktake_decisions_action", "stocktake_decisions", type_="check"
    )
    op.drop_constraint(
        "ck_stocktake_decisions_reason", "stocktake_decisions", type_="check"
    )
    op.create_check_constraint(
        "ck_stocktake_decisions_action",
        "stocktake_decisions",
        "action IN ('recount_requested', 'rejected', 'approved')",
    )
    op.create_check_constraint(
        "ck_stocktake_decisions_reason",
        "stocktake_decisions",
        "(action = 'recount_requested' AND reason_code IS NOT NULL AND reason IS NOT NULL) "
        "OR (action = 'rejected' AND reason_code IS NOT NULL AND reason IS NOT NULL) "
        "OR (action = 'approved' AND reason_code IS NULL AND reason IS NULL)",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_stocktake_decisions_reason", "stocktake_decisions", type_="check"
    )
    op.drop_constraint(
        "ck_stocktake_decisions_action", "stocktake_decisions", type_="check"
    )
    op.create_check_constraint(
        "ck_stocktake_decisions_action",
        "stocktake_decisions",
        "action IN ('recount_requested', 'approved')",
    )
    op.create_check_constraint(
        "ck_stocktake_decisions_reason",
        "stocktake_decisions",
        "(action = 'recount_requested' AND reason_code IS NOT NULL AND reason IS NOT NULL) "
        "OR (action = 'approved' AND reason_code IS NULL AND reason IS NULL)",
    )
