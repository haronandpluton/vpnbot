from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.common.enums import AppEnv, CurrencyCode, NetworkCode, TariffCode
from app.config import constants
from app.config.payment_options import (
    CRYPTOBOT_PAYMENT_OPTION_CODES,
    PAYMENT_OPTIONS,
    PaymentOptionConfig,
    get_active_payment_options,
    get_payment_option,
)
from app.config.settings import Settings, get_settings
from app.config.tariffs import (
    TARIFFS,
    TariffConfig,
    get_purchasable_tariffs,
    get_tariff,
)
from app.payment_core.enums.payment_method import PaymentMethod


def make_settings(**overrides):
    values = {
        "_env_file": None,
        "BOT_TOKEN": "bot-token",
        "DATABASE_URL": "sqlite+aiosqlite:///test.db",
    }
    values.update(overrides)
    return Settings(**values)


def test_settings_required_aliases_and_safe_defaults_are_stable():
    settings = make_settings()

    assert settings.bot_token == "bot-token"
    assert settings.database_url == "sqlite+aiosqlite:///test.db"
    assert settings.app_env == AppEnv.DEV
    assert settings.log_level == "INFO"
    assert settings.dev_mode is False
    assert settings.order_ttl_minutes == 15
    assert settings.payment_poll_interval_seconds == 15
    assert settings.volet_sci_enabled is False
    assert settings.volet_sci_url == "https://account.volet.com/sci/"
    assert settings.volet_sci_default_currency == "USDT_TRX"
    assert settings.volet_sci_web_host == "0.0.0.0"
    assert settings.volet_sci_web_port == 2098
    assert settings.cryptobot_enabled is False
    assert settings.cryptobot_api_url == "https://pay.crypt.bot/api"
    assert settings.cryptobot_asset == "USDT"
    assert settings.cryptobot_expires_in == 900
    assert settings.telegram_stars_enabled is False
    assert settings.telegram_stars_invoice_secret == ""
    assert settings.xui_inbound_id == 9
    assert settings.vpn_default_server_name == "default-node"
    assert settings.vpn_default_inbound_id == 1
    assert (
        settings.vpn_subscription_public_base_url == "https://connect.presentvpn.click"
    )
    assert settings.subscription_meta_retry_scheduler_enabled is True
    assert settings.subscription_meta_retry_interval_seconds == 120
    assert settings.subscription_meta_retry_initial_delay_seconds == 60
    assert settings.subscription_expiration_scheduler_enabled is True
    assert settings.order_expiration_scheduler_enabled is True


@pytest.mark.parametrize(
    ("raw_level", "expected"),
    [
        ("debug", "DEBUG"),
        ("Info", "INFO"),
        ("WARNING", "WARNING"),
        ("error", "ERROR"),
        ("critical", "CRITICAL"),
    ],
)
def test_settings_log_level_is_normalized(raw_level, expected):
    assert make_settings(LOG_LEVEL=raw_level).log_level == expected


def test_settings_normalizes_vpn_subscription_public_base_url():
    settings = make_settings(
        VPN_SUBSCRIPTION_PUBLIC_BASE_URL=" https://gateway.example.com/ ",
    )

    assert settings.vpn_subscription_public_base_url == "https://gateway.example.com"


def test_settings_rejects_vpn_subscription_public_base_url_without_scheme():
    with pytest.raises(ValidationError) as exc_info:
        make_settings(VPN_SUBSCRIPTION_PUBLIC_BASE_URL="gateway.example.com")

    assert "VPN_SUBSCRIPTION_PUBLIC_BASE_URL must be an HTTP(S) URL" in str(
        exc_info.value
    )


def test_settings_rejects_invalid_log_level():
    with pytest.raises(ValidationError) as exc_info:
        make_settings(LOG_LEVEL="verbose")

    assert "Invalid LOG_LEVEL: verbose" in str(exc_info.value)


@pytest.mark.parametrize(
    ("raw_admin_ids", "expected"),
    [
        ("", []),
        ("   ", []),
        ("1", [1]),
        ("1,2,3", [1, 2, 3]),
        (" 1, 2,, 3 ", [1, 2, 3]),
    ],
)
def test_settings_admin_ids_parser_trims_and_skips_empty_parts(raw_admin_ids, expected):
    assert make_settings(ADMIN_IDS=raw_admin_ids).admin_ids == expected


def test_settings_admin_ids_raises_for_non_numeric_admin_id():
    settings = make_settings(ADMIN_IDS="1,broken")

    with pytest.raises(ValueError):
        _ = settings.admin_ids


def test_settings_environment_helpers_distinguish_dev_prod_and_test():
    assert make_settings(APP_ENV="dev").is_dev is True
    assert make_settings(APP_ENV="dev").is_prod is False
    assert make_settings(APP_ENV="prod").is_prod is True
    assert make_settings(APP_ENV="prod").is_dev is False
    assert make_settings(APP_ENV="test").is_prod is False
    assert make_settings(APP_ENV="test").is_dev is False


def test_get_settings_is_cached_and_reads_environment(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("BOT_TOKEN", "env-token")
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///env.db")
    monkeypatch.setenv("ADMIN_IDS", "7,8")
    monkeypatch.setenv("LOG_LEVEL", "debug")

    first = get_settings()
    second = get_settings()

    assert first is second
    assert first.bot_token == "env-token"
    assert first.database_url == "sqlite+aiosqlite:///env.db"
    assert first.admin_ids == [7, 8]
    assert first.log_level == "DEBUG"
    get_settings.cache_clear()


def test_tariffs_match_public_pricing_and_duration():
    assert set(TARIFFS) == {
        TariffCode.DEVICES_1,
        TariffCode.DEVICES_2,
        TariffCode.DEVICES_3,
        TariffCode.PERIOD_1_MONTH,
        TariffCode.PERIOD_2_MONTHS,
        TariffCode.PERIOD_3_MONTHS,
    }

    assert TARIFFS[TariffCode.PERIOD_1_MONTH] == TariffConfig(
        code=TariffCode.PERIOD_1_MONTH,
        title="33 days (30 days + 3 days 🎁)",
        device_limit=1,
        price_usd=Decimal("4.00"),
        base_days=30,
        bonus_days=3,
        stars_price=300,
    )

    purchasable = get_purchasable_tariffs()
    assert [
        (tariff.price_usd, tariff.duration_days, tariff.device_limit)
        for tariff in purchasable
    ] == [
        (Decimal("4.00"), 33, 1),
        (Decimal("7.50"), 66, 1),
        (Decimal("11.00"), 99, 1),
    ]

    assert TARIFFS[TariffCode.DEVICES_1].duration_days == 30
    assert TARIFFS[TariffCode.DEVICES_2].duration_days == 30
    assert TARIFFS[TariffCode.DEVICES_3].duration_days == 30


def test_get_tariff_returns_config_and_rejects_unknown_code():
    assert get_tariff(TariffCode.DEVICES_1) is TARIFFS[TariffCode.DEVICES_1]

    with pytest.raises(ValueError, match="Unsupported tariff code: broken"):
        get_tariff("broken")  # type: ignore[arg-type]


def test_payment_options_include_cryptobot_assets_future_options_and_stars():
    assert set(PAYMENT_OPTIONS) == {
        "cryptobot_usdt",
        "cryptobot_usdc",
        "cryptobot_btc",
        "cryptobot_eth",
        "cryptobot_ton",
        "cryptobot_ltc",
        "cryptobot_bnb",
        "cryptobot_trx",
        "xrp_xrpl",
        "sol_solana",
        "usdt_trc20",
        "usdt_erc20",
        "usdt_bep20",
        "usdc_erc20",
        "usdc_solana",
        "usdc_polygon",
        "telegram_stars",
    }
    assert CRYPTOBOT_PAYMENT_OPTION_CODES == (
        "cryptobot_usdt",
        "cryptobot_usdc",
        "cryptobot_btc",
        "cryptobot_eth",
        "cryptobot_ton",
        "cryptobot_ltc",
        "cryptobot_bnb",
        "cryptobot_trx",
    )
    assert PAYMENT_OPTIONS["cryptobot_btc"] == PaymentOptionConfig(
        code="cryptobot_btc",
        payment_method=PaymentMethod.CRYPTO,
        currency=CurrencyCode.BTC,
        network=None,
        display_name="CryptoBot — BTC",
        is_active=True,
        sort_order=30,
    )
    assert PAYMENT_OPTIONS["cryptobot_ton"] == PaymentOptionConfig(
        code="cryptobot_ton",
        payment_method=PaymentMethod.CRYPTO,
        currency=CurrencyCode.TON,
        network=None,
        display_name="CryptoBot — TON",
        is_active=True,
        sort_order=50,
    )
    assert PAYMENT_OPTIONS["usdt_trc20"].is_active is False
    assert PAYMENT_OPTIONS["xrp_xrpl"].is_active is False
    assert PAYMENT_OPTIONS["sol_solana"].is_active is False
    assert PAYMENT_OPTIONS["telegram_stars"].is_active is True


def test_active_payment_options_include_cryptobot_assets_and_stars_in_order():
    active = get_active_payment_options()

    assert [option.code for option in active] == [
        "cryptobot_usdt",
        "cryptobot_usdc",
        "cryptobot_btc",
        "cryptobot_eth",
        "cryptobot_ton",
        "cryptobot_ltc",
        "cryptobot_bnb",
        "cryptobot_trx",
        "telegram_stars",
    ]

    assert [
        option.currency
        for option in active
        if option.currency is not None
    ] == [
        CurrencyCode.USDT,
        CurrencyCode.USDC,
        CurrencyCode.BTC,
        CurrencyCode.ETH,
        CurrencyCode.TON,
        CurrencyCode.LTC,
        CurrencyCode.BNB,
        CurrencyCode.TRX,
    ]

    assert all(option.is_active for option in active)


def test_get_payment_option_returns_config_and_rejects_unknown_code():
    assert get_payment_option("usdt_trc20") is PAYMENT_OPTIONS["usdt_trc20"]

    with pytest.raises(ValueError, match="Unsupported payment option code: broken"):
        get_payment_option("broken")


def test_common_enums_keep_external_string_values_stable():
    assert AppEnv.DEV.value == "dev"
    assert AppEnv.PROD.value == "prod"
    assert AppEnv.TEST.value == "test"
    assert [item.value for item in CurrencyCode] == [
        "USDT",
        "USDC",
        "BTC",
        "ETH",
        "TON",
        "LTC",
        "BNB",
        "TRX",
        "XRP",
        "SOL",
    ]
    assert [item.value for item in NetworkCode] == [
        "TRC20",
        "ERC20",
        "BEP20",
        "POLYGON",
        "SOLANA",
        "XRPL",
    ]
    assert [item.value for item in TariffCode] == [
        "devices_1",
        "devices_2",
        "devices_3",
        "period_1_month",
        "period_2_months",
        "period_3_months",
    ]


def test_text_constants_and_callback_constants_are_stable_for_user_navigation():
    assert "Welcome" in constants.START_TEXT
    assert "FAQ" in constants.FAQ_TEXT
    assert "support" in constants.SUPPORT_TEXT
    assert "exact amount" in constants.PAYMENT_EXACT_AMOUNT_WARNING
    assert "XRP" in constants.XRP_MEMO_WARNING
    assert constants.CALLBACK_MAIN_MENU == "main_menu"
    assert constants.CALLBACK_BUY == "buy"
    assert constants.CALLBACK_DOWNLOAD == "download"
    assert constants.CALLBACK_MY_SUBSCRIPTION == "my_subscription"
    assert constants.CALLBACK_SUPPORT == "support"
    assert constants.CALLBACK_FAQ == "faq"
