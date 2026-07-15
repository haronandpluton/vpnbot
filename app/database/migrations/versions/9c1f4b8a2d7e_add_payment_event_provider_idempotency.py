"""add provider-scoped payment event idempotency

Revision ID: 9c1f4b8a2d7e
Revises: 0476c617da20
Create Date: 2026-07-12
"""

from collections.abc import Sequence

from alembic import op

revision: str = "9c1f4b8a2d7e"
down_revision: str | Sequence[str] | None = "0476c617da20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        WITH ranked AS (
            SELECT
                id,
                ROW_NUMBER() OVER (
                    PARTITION BY provider, external_event_id
                    ORDER BY id
                ) AS row_number
            FROM payment_events
            WHERE external_event_id IS NOT NULL
        )
        UPDATE payment_events AS payment_event
        SET
            external_event_id = NULL,
            processing_status = COALESCE(
                payment_event.processing_status,
                'duplicate_migration'
            ),
            error_message = COALESCE(
                payment_event.error_message,
                'Duplicate external event normalized before unique constraint'
            )
        FROM ranked
        WHERE payment_event.id = ranked.id
          AND ranked.row_number > 1
        """
    )

    op.create_unique_constraint(
        "uq_payment_events_provider_external_event_id",
        "payment_events",
        ["provider", "external_event_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_payment_events_provider_external_event_id",
        "payment_events",
        type_="unique",
    )