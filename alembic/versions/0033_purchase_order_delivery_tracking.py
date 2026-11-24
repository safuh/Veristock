"""Track promised and actual purchase-order completion dates."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0033_purchase_order_delivery_tracking"
down_revision: str | None = "0032_procurement_approval_rules"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("purchase_orders") as batch_op:
        batch_op.add_column(sa.Column("expected_delivery_date", sa.Date(), nullable=True))
        batch_op.add_column(sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("purchase_orders") as batch_op:
        batch_op.drop_column("completed_at")
        batch_op.drop_column("expected_delivery_date")
