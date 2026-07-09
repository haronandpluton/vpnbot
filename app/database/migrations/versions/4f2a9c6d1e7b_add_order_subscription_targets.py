"""add order subscription targets

Revision ID: 4f2a9c6d1e7b
Revises: 8d4b2e1a6c90
Create Date: 2026-07-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "4f2a9c6d1e7b"
down_revision: str | None = "8d4b2e1a6c90"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("orders") as batch_op:
        batch_op.add_column(
            sa.Column(
                "target_subscription_id",
                sa.Integer(),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                "activated_subscription_id",
                sa.Integer(),
                nullable=True,
            )
        )

        batch_op.create_index(
            "ix_orders_target_subscription_id",
            ["target_subscription_id"],
            unique=False,
        )
        batch_op.create_index(
            "ix_orders_activated_subscription_id",
            ["activated_subscription_id"],
            unique=False,
        )

        batch_op.create_foreign_key(
            "fk_orders_target_subscription_id_subscriptions",
            "subscriptions",
            ["target_subscription_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_foreign_key(
            "fk_orders_activated_subscription_id_subscriptions",
            "subscriptions",
            ["activated_subscription_id"],
            ["id"],
            ondelete="SET NULL",
        )

    op.execute(
        sa.text(
            """
            UPDATE orders
            SET activated_subscription_id = (
                SELECT MIN(subscriptions.id)
                FROM subscriptions
                WHERE subscriptions.order_id = orders.id
            )
            WHERE activated_subscription_id IS NULL
              AND EXISTS (
                  SELECT 1
                  FROM subscriptions
                  WHERE subscriptions.order_id = orders.id
              )
            """
        )
    )


def downgrade() -> None:
    with op.batch_alter_table("orders") as batch_op:
        batch_op.drop_constraint(
            "fk_orders_activated_subscription_id_subscriptions",
            type_="foreignkey",
        )
        batch_op.drop_constraint(
            "fk_orders_target_subscription_id_subscriptions",
            type_="foreignkey",
        )

        batch_op.drop_index("ix_orders_activated_subscription_id")
        batch_op.drop_index("ix_orders_target_subscription_id")

        batch_op.drop_column("activated_subscription_id")
        batch_op.drop_column("target_subscription_id")
