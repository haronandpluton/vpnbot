"""add XTR currency

Revision ID: e6a4c8f21b73
Revises: 9c1f4b8a2d7e
Create Date: 2026-07-15
"""

from collections.abc import Sequence

from alembic import op


revision: str = "e6a4c8f21b73"
down_revision: str | Sequence[str] | None = "9c1f4b8a2d7e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()

    if bind.dialect.name == "postgresql":
        # PostgreSQL requires a newly added enum value to be committed
        # before it can be used by later transactions.
        with op.get_context().autocommit_block():
            op.execute(
                "ALTER TYPE currency_code_enum "
                "ADD VALUE IF NOT EXISTS 'XTR'"
            )


def downgrade() -> None:
    # XTR intentionally remains in the PostgreSQL enum.
    # Removing one enum value safely requires recreating the enum
    # and every dependent column.
    pass
