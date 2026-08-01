"""add subscription node access state

Revision ID: c4a7e2d9b531
Revises: f56eb2e7770c
Create Date: 2026-08-01
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "c4a7e2d9b531"
down_revision: str | Sequence[str] | None = "f56eb2e7770c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


DESIRED_STATES = ("enabled", "disabled")
ACTUAL_STATES = ("pending", "enabled", "disabled", "error")


def upgrade() -> None:
    op.create_table(
        "subscription_node_access",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("subscription_id", sa.Integer(), nullable=False),
        sa.Column("node_code", sa.String(length=64), nullable=False),
        sa.Column(
            "desired_state",
            sa.Enum(
                *DESIRED_STATES,
                name="vpn_node_desired_state_enum",
            ),
            server_default="enabled",
            nullable=False,
        ),
        sa.Column(
            "actual_state",
            sa.Enum(
                *ACTUAL_STATES,
                name="vpn_node_actual_state_enum",
            ),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("last_error", sa.String(length=1000), nullable=True),
        sa.Column(
            "retry_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "provisioned_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "disabled_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
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
        sa.ForeignKeyConstraint(
            ["subscription_id"],
            ["subscriptions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "subscription_id",
            "node_code",
            name="uq_subscription_node_access_subscription_node",
        ),
    )
    op.create_index(
        "ix_subscription_node_access_subscription_id",
        "subscription_node_access",
        ["subscription_id"],
        unique=False,
    )
    op.create_index(
        "ix_subscription_node_access_node_code",
        "subscription_node_access",
        ["node_code"],
        unique=False,
    )
    op.create_index(
        "ix_subscription_node_access_desired_state",
        "subscription_node_access",
        ["desired_state"],
        unique=False,
    )
    op.create_index(
        "ix_subscription_node_access_actual_state",
        "subscription_node_access",
        ["actual_state"],
        unique=False,
    )
    op.create_index(
        "ix_subscription_node_access_subscription_states",
        "subscription_node_access",
        ["subscription_id", "desired_state", "actual_state"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_subscription_node_access_subscription_states",
        table_name="subscription_node_access",
    )
    op.drop_index(
        "ix_subscription_node_access_actual_state",
        table_name="subscription_node_access",
    )
    op.drop_index(
        "ix_subscription_node_access_desired_state",
        table_name="subscription_node_access",
    )
    op.drop_index(
        "ix_subscription_node_access_node_code",
        table_name="subscription_node_access",
    )
    op.drop_index(
        "ix_subscription_node_access_subscription_id",
        table_name="subscription_node_access",
    )
    op.drop_table("subscription_node_access")

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        sa.Enum(
            *ACTUAL_STATES,
            name="vpn_node_actual_state_enum",
        ).drop(bind, checkfirst=True)
        sa.Enum(
            *DESIRED_STATES,
            name="vpn_node_desired_state_enum",
        ).drop(bind, checkfirst=True)
