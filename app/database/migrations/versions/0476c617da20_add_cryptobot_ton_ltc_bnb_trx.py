"""add CryptoBot TON LTC BNB TRX

Revision ID: 0476c617da20
Revises: 7b73d741822c
Create Date: 2026-07-10
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0476c617da20"
down_revision: str | None = "7b73d741822c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


CRYPTOBOT_OPTIONS = (
    ("cryptobot_ton", "TON", "CryptoBot \u2014 TON", 50),
    ("cryptobot_ltc", "LTC", "CryptoBot \u2014 LTC", 60),
    ("cryptobot_bnb", "BNB", "CryptoBot \u2014 BNB", 70),
    ("cryptobot_trx", "TRX", "CryptoBot \u2014 TRX", 80),
)

CRYPTOBOT_OPTION_CODES = tuple(
    option[0] for option in CRYPTOBOT_OPTIONS
)


def _payment_options_table(
    dialect_name: str,
) -> sa.TableClause:
    if dialect_name == "postgresql":
        payment_method_type = postgresql.ENUM(
            name="payment_method_enum",
            create_type=False,
        )
        currency_type = postgresql.ENUM(
            name="currency_code_enum",
            create_type=False,
        )
        network_type = postgresql.ENUM(
            name="network_code_enum",
            create_type=False,
        )
    else:
        payment_method_type = sa.String()
        currency_type = sa.String()
        network_type = sa.String()

    return sa.table(
        "payment_options",
        sa.column("id", sa.Integer()),
        sa.column("code", sa.String()),
        sa.column("payment_method", payment_method_type),
        sa.column("currency", currency_type),
        sa.column("network", network_type),
        sa.column("display_name", sa.String()),
        sa.column("is_active", sa.Boolean()),
        sa.column("sort_order", sa.Integer()),
    )


def upgrade() -> None:
    bind = op.get_bind()

    if bind.dialect.name == "postgresql":
        # PostgreSQL enum values must be committed before they are used
        # by subsequent INSERT or UPDATE statements.
        with op.get_context().autocommit_block():
            for currency in ("TON", "LTC", "BNB", "TRX"):
                op.execute(
                    "ALTER TYPE currency_code_enum "
                    f"ADD VALUE IF NOT EXISTS '{currency}'"
                )

    payment_options = _payment_options_table(bind.dialect.name)

    for code, currency, display_name, sort_order in CRYPTOBOT_OPTIONS:
        existing_id = bind.execute(
            sa.select(payment_options.c.id).where(
                payment_options.c.code == code
            )
        ).scalar_one_or_none()

        values = {
            "payment_method": "crypto",
            "currency": currency,
            "network": None,
            "display_name": display_name,
            "is_active": True,
            "sort_order": sort_order,
        }

        if existing_id is None:
            bind.execute(
                payment_options.insert().values(
                    code=code,
                    **values,
                )
            )
        else:
            bind.execute(
                payment_options.update()
                .where(payment_options.c.id == existing_id)
                .values(**values)
            )


def downgrade() -> None:
    bind = op.get_bind()
    payment_options = _payment_options_table(bind.dialect.name)

    bind.execute(
        payment_options.update()
        .where(
            payment_options.c.code.in_(CRYPTOBOT_OPTION_CODES)
        )
        .values(is_active=False)
    )

    # TON, LTC, BNB and TRX intentionally remain in the PostgreSQL enum.
    # Removing individual enum values safely requires recreating the enum
    # and all dependent columns.