"""add adsgram attribution and conversion outbox

Revision ID: b7d4e9a2c610
Revises: c4a7e2d9b531
Create Date: 2026-08-05
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "b7d4e9a2c610"
down_revision: str | Sequence[str] | None = "c4a7e2d9b531"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "adsgram_campaign_id",
            sa.String(length=64),
            nullable=True,
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "adsgram_attributed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_users_adsgram_campaign_id",
        "users",
        ["adsgram_campaign_id"],
        unique=False,
    )

    op.create_table(
        "adsgram_conversions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=True),
        sa.Column("campaign_id", sa.String(length=64), nullable=False),
        sa.Column("goal_type", sa.SmallInteger(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default="pending",
            nullable=False,
        ),
        sa.Column(
            "attempt_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "claimed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("claim_token", sa.String(length=64), nullable=True),
        sa.Column(
            "last_attempt_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "sent_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("last_http_status", sa.Integer(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "goal_type IN (1, 2, 3)",
            name="ck_adsgram_conversions_goal_type",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'sent', 'failed')",
            name="ck_adsgram_conversions_status",
        ),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["orders.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_adsgram_conversions_user_id",
        "adsgram_conversions",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_adsgram_conversions_order_id",
        "adsgram_conversions",
        ["order_id"],
        unique=False,
    )
    op.create_index(
        "ix_adsgram_conversions_campaign_id",
        "adsgram_conversions",
        ["campaign_id"],
        unique=False,
    )
    op.create_index(
        "ix_adsgram_conversions_idempotency_key",
        "adsgram_conversions",
        ["idempotency_key"],
        unique=True,
    )
    op.create_index(
        "ix_adsgram_conversions_claimed_at",
        "adsgram_conversions",
        ["claimed_at"],
        unique=False,
    )
    op.create_index(
        "ix_adsgram_conversions_sent_at",
        "adsgram_conversions",
        ["sent_at"],
        unique=False,
    )
    op.create_index(
        "ix_adsgram_conversions_status_next_attempt_at",
        "adsgram_conversions",
        ["status", "next_attempt_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_adsgram_conversions_status_next_attempt_at",
        table_name="adsgram_conversions",
    )
    op.drop_index(
        "ix_adsgram_conversions_sent_at",
        table_name="adsgram_conversions",
    )
    op.drop_index(
        "ix_adsgram_conversions_claimed_at",
        table_name="adsgram_conversions",
    )
    op.drop_index(
        "ix_adsgram_conversions_idempotency_key",
        table_name="adsgram_conversions",
    )
    op.drop_index(
        "ix_adsgram_conversions_campaign_id",
        table_name="adsgram_conversions",
    )
    op.drop_index(
        "ix_adsgram_conversions_order_id",
        table_name="adsgram_conversions",
    )
    op.drop_index(
        "ix_adsgram_conversions_user_id",
        table_name="adsgram_conversions",
    )
    op.drop_table("adsgram_conversions")

    op.drop_index(
        "ix_users_adsgram_campaign_id",
        table_name="users",
    )
    op.drop_column("users", "adsgram_attributed_at")
    op.drop_column("users", "adsgram_campaign_id")