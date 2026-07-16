"""add trial access fields

Revision ID: 0f2703fb4484
Revises: e6a4c8f21b73
Create Date: 2026-07-15
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0f2703fb4484"
down_revision: str | Sequence[str] | None = "e6a4c8f21b73"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # New users are eligible by default.
    op.add_column(
        "users",
        sa.Column(
            "trial_eligible",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "trial_claimed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    # Users that existed before this migration must not receive the trial.
    op.execute(
        sa.text(
            "UPDATE users "
            "SET trial_eligible = false"
        )
    )

    op.add_column(
        "subscriptions",
        sa.Column(
            "is_trial",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    op.create_index(
        "uq_subscriptions_one_trial_per_user",
        "subscriptions",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("is_trial IS TRUE"),
        sqlite_where=sa.text("is_trial = 1"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_subscriptions_one_trial_per_user",
        table_name="subscriptions",
    )
    op.drop_column("subscriptions", "is_trial")
    op.drop_column("users", "trial_claimed_at")
    op.drop_column("users", "trial_eligible")