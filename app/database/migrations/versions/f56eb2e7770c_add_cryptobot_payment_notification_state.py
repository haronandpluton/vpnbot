"""add cryptobot payment notification state

Revision ID: f56eb2e7770c
Revises: 0f2703fb4484
Create Date: 2026-07-19 05:42:51.226580
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "f56eb2e7770c"
down_revision: str | Sequence[str] | None = "0f2703fb4484"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "payment_events",
        sa.Column(
            "notification_claimed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "payment_events",
        sa.Column(
            "notification_claim_token",
            sa.String(length=64),
            nullable=True,
        ),
    )
    op.add_column(
        "payment_events",
        sa.Column(
            "notification_sent_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    op.create_index(
        "ix_payment_events_notification_claimed_at",
        "payment_events",
        ["notification_claimed_at"],
        unique=False,
    )
    op.create_index(
        "ix_payment_events_notification_sent_at",
        "payment_events",
        ["notification_sent_at"],
        unique=False,
    )

    # Previously confirmed CryptoBot payments were already handled through
    # the manual payment-check flow. Mark them as notified so deployment of
    # the scheduler does not message historical buyers.
    op.execute(
        """
        UPDATE payment_events
        SET notification_sent_at = COALESCE(
            processed_at,
            created_at,
            CURRENT_TIMESTAMP
        )
        WHERE provider = 'cryptobot'
          AND event_type = 'invoice_paid'
          AND processed IS TRUE
          AND processing_status = 'confirmed'
          AND payment_id IS NOT NULL
          AND notification_sent_at IS NULL
          AND EXISTS (
              SELECT 1
              FROM orders
              WHERE orders.id = payment_events.order_id
                AND orders.status = 'activated'
                AND orders.activated_subscription_id IS NOT NULL
          )
        """
    )


def downgrade() -> None:
    op.drop_index(
        "ix_payment_events_notification_sent_at",
        table_name="payment_events",
    )
    op.drop_index(
        "ix_payment_events_notification_claimed_at",
        table_name="payment_events",
    )

    op.drop_column(
        "payment_events",
        "notification_sent_at",
    )
    op.drop_column(
        "payment_events",
        "notification_claim_token",
    )
    op.drop_column(
        "payment_events",
        "notification_claimed_at",
    )
