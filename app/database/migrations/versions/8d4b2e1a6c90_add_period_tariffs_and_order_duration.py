"""add period tariffs and order duration

Revision ID: 8d4b2e1a6c90
Revises: 120a64c0ed0a
Create Date: 2026-07-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "8d4b2e1a6c90"
down_revision: str | None = "120a64c0ed0a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()

    # В PostgreSQL enum хранится как отдельный тип.
    # В SQLite SQLAlchemy хранит такие значения как строки.
    if bind.dialect.name == "postgresql":
        op.execute(
            "ALTER TYPE tariff_code_enum "
            "ADD VALUE IF NOT EXISTS 'period_1_month'"
        )
        op.execute(
            "ALTER TYPE tariff_code_enum "
            "ADD VALUE IF NOT EXISTS 'period_2_months'"
        )
        op.execute(
            "ALTER TYPE tariff_code_enum "
            "ADD VALUE IF NOT EXISTS 'period_3_months'"
        )

    op.add_column(
        "orders",
        sa.Column(
            "duration_days",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("30"),
        ),
    )


def downgrade() -> None:
    op.drop_column("orders", "duration_days")

    # Значения PostgreSQL ENUM намеренно не удаляются:
    # их безопасное удаление требует пересоздания enum-типа.