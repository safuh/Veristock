"""Link approved purchase requisitions to generated purchase orders."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0031_requisition_purchase_order_link"
down_revision: str | None = "0030_purchase_requisitions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("purchase_requisitions") as batch_op:
        batch_op.add_column(
            sa.Column(
                "converted_purchase_order_id",
                sa.String(36),
                sa.ForeignKey(
                    "purchase_orders.id",
                    ondelete="RESTRICT",
                    name="fk_purchase_requisitions_converted_purchase_order",
                ),
                nullable=True,
            )
        )
        batch_op.create_unique_constraint(
            "uq_purchase_requisitions_purchase_order",
            ["converted_purchase_order_id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("purchase_requisitions") as batch_op:
        batch_op.drop_constraint(
            "uq_purchase_requisitions_purchase_order",
            type_="unique",
        )
        batch_op.drop_column("converted_purchase_order_id")
