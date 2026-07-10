"""add CryptoBot multi-currency payment options

Revision ID: 7b73d741822c
Revises: 4f2a9c6d1e7b
Create Date: 2026-07-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op


revision: str = "7b73d741822c"
down_revision: str | None = "4f2a9c6d1e7b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


CRYPTOBOT_OPTIONS = (
    ("cryptobot_usdt", "USDT", "CryptoBot вЂ” USDT", 10),
    ("cryptobot_usdc", "USDC", "CryptoBot вЂ” USDC", 20),
    ("cryptobot_btc", "BTC", "CryptoBot вЂ” BTC", 30),
    ("cryptobot_eth", "ETH", "CryptoBot вЂ” ETH", 40),
)

INACTIVE_ONCHAIN_OPTIONS = (
    "xrp_xrpl",
    "sol_solana",
    "usdt_trc20",
    "usdt_erc20",
    "usdt_bep20",
    "usdc_erc20",
    "usdc_solana",
    "usdc_polygon",
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
        # PostgreSQL С‚СЂРµР±СѓРµС‚ Р·Р°С„РёРєСЃРёСЂРѕРІР°С‚СЊ РЅРѕРІС‹Рµ Р·РЅР°С‡РµРЅРёСЏ enum РґРѕ С‚РѕРіРѕ,
        # РєР°Рє РѕРЅРё Р±СѓРґСѓС‚ РёСЃРїРѕР»СЊР·РѕРІР°РЅС‹ РІ СЃР»РµРґСѓСЋС‰РёС… INSERT/UPDATE.
        with op.get_context().autocommit_block():
            op.execute("ALTER TYPE currency_code_enum ADD VALUE IF NOT EXISTS 'BTC'")
            op.execute("ALTER TYPE currency_code_enum ADD VALUE IF NOT EXISTS 'ETH'")

    payment_options = _payment_options_table(bind.dialect.name)

    for code, currency, display_name, sort_order in CRYPTOBOT_OPTIONS:
        existing_id = bind.execute(
            sa.select(payment_options.c.id).where(payment_options.c.code == code)
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

    bind.execute(
        payment_options.update()
        .where(payment_options.c.code.in_(INACTIVE_ONCHAIN_OPTIONS))
        .values(is_active=False)
    )


def downgrade() -> None:
    bind = op.get_bind()
    payment_options = _payment_options_table(bind.dialect.name)

    bind.execute(
        payment_options.update()
        .where(
            payment_options.c.code.in_(
                (
                    "cryptobot_usdc",
                    "cryptobot_btc",
                    "cryptobot_eth",
                )
            )
        )
        .values(is_active=False)
    )

    bind.execute(
        payment_options.update()
        .where(payment_options.c.code == "cryptobot_usdt")
        .values(
            is_active=True,
            sort_order=5,
        )
    )

    bind.execute(
        payment_options.update()
        .where(payment_options.c.code.in_(INACTIVE_ONCHAIN_OPTIONS))
        .values(is_active=True)
    )

    # BTC Рё ETH РЅР°РјРµСЂРµРЅРЅРѕ РѕСЃС‚Р°СЋС‚СЃСЏ РІ PostgreSQL enum.
    # Р‘РµР·РѕРїР°СЃРЅРѕРµ СѓРґР°Р»РµРЅРёРµ Р·РЅР°С‡РµРЅРёР№ enum С‚СЂРµР±СѓРµС‚ РїРµСЂРµСЃРѕР·РґР°РЅРёСЏ С‚РёРїР°
    # Рё РІСЃРµС… Р·Р°РІРёСЃРёРјС‹С… РєРѕР»РѕРЅРѕРє.
