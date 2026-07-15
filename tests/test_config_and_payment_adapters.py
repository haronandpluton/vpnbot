from __future__ import annotations

from decimal import Decimal

import pytest

import app.payment_adapters.mock.adapter as mock_adapter_module
from app.common.enums import CurrencyCode, NetworkCode, TariffCode
from app.config.payment_options import (
    PAYMENT_OPTIONS,
    PaymentOptionConfig,
    get_active_payment_options,
    get_payment_option,
)
from app.config.tariffs import (
    TARIFFS,
    TariffConfig,
    get_purchasable_tariffs,
    get_tariff,
)
from app.payment_adapters.base import NormalizedTransaction
from app.payment_adapters.mock import MockPaymentAdapter
from app.payment_adapters.registry import (
    PaymentAdapterRegistry,
    get_payment_adapter_registry,
)
from app.payment_core.enums.payment_method import PaymentMethod


def test_tariffs_have_expected_public_prices_device_limits_and_duration():
    one_month = get_tariff(TariffCode.PERIOD_1_MONTH)
    two_months = get_tariff(TariffCode.PERIOD_2_MONTHS)
    three_months = get_tariff(TariffCode.PERIOD_3_MONTHS)

    assert one_month == TariffConfig(
        code=TariffCode.PERIOD_1_MONTH,
        title="33 days (30 days + 3 days 🎁)",
        device_limit=1,
        price_usd=Decimal("4.00"),
        base_days=30,
        bonus_days=3,
        stars_price=300,
    )
    assert one_month.duration_days == 33

    assert two_months.device_limit == 1
    assert two_months.price_usd == Decimal("7.50")
    assert two_months.base_days == 60
    assert two_months.bonus_days == 6
    assert two_months.duration_days == 66

    assert three_months.device_limit == 1
    assert three_months.price_usd == Decimal("11.00")
    assert three_months.base_days == 90
    assert three_months.bonus_days == 9
    assert three_months.duration_days == 99

    assert [tariff.code for tariff in get_purchasable_tariffs()] == [
        TariffCode.PERIOD_1_MONTH,
        TariffCode.PERIOD_2_MONTHS,
        TariffCode.PERIOD_3_MONTHS,
    ]


def test_tariff_configs_are_frozen_and_key_matches_code():
    assert set(TARIFFS) == {
        TariffCode.DEVICES_1,
        TariffCode.DEVICES_2,
        TariffCode.DEVICES_3,
        TariffCode.PERIOD_1_MONTH,
        TariffCode.PERIOD_2_MONTHS,
        TariffCode.PERIOD_3_MONTHS,
    }
    assert all(key == tariff.code for key, tariff in TARIFFS.items())

    with pytest.raises(Exception):
        get_tariff(TariffCode.PERIOD_1_MONTH).price_usd = Decimal("0.01")


def test_get_tariff_rejects_unsupported_code():
    with pytest.raises(ValueError, match="Unsupported tariff code: unknown"):
        get_tariff("unknown")


def test_payment_options_have_stable_codes_and_unique_sort_orders():
    assert all(code == option.code for code, option in PAYMENT_OPTIONS.items())
    assert len({option.sort_order for option in PAYMENT_OPTIONS.values()}) == len(
        PAYMENT_OPTIONS
    )
    assert all(
        isinstance(option, PaymentOptionConfig) for option in PAYMENT_OPTIONS.values()
    )


def test_get_active_payment_options_returns_active_options_sorted_and_includes_stars():
    options = get_active_payment_options()

    assert options == sorted(
        options,
        key=lambda item: item.sort_order,
    )
    assert all(option.is_active for option in options)
    assert "telegram_stars" in {
        option.code for option in options
    }
    assert options[0].code == "cryptobot_usdt"
    assert options[-1].code == "telegram_stars"

def test_crypto_payment_options_have_currency_and_valid_network_rules():
    cryptobot_usdt = get_payment_option("cryptobot_usdt")
    cryptobot_usdc = get_payment_option("cryptobot_usdc")
    cryptobot_btc = get_payment_option("cryptobot_btc")
    cryptobot_eth = get_payment_option("cryptobot_eth")
    cryptobot_ton = get_payment_option("cryptobot_ton")
    cryptobot_ltc = get_payment_option("cryptobot_ltc")
    cryptobot_bnb = get_payment_option("cryptobot_bnb")
    cryptobot_trx = get_payment_option("cryptobot_trx")
    usdt_trc20 = get_payment_option("usdt_trc20")
    xrp = get_payment_option("xrp_xrpl")

    assert cryptobot_usdt.payment_method == PaymentMethod.CRYPTO
    assert cryptobot_usdt.currency == CurrencyCode.USDT
    assert cryptobot_usdc.currency == CurrencyCode.USDC
    assert cryptobot_btc.currency == CurrencyCode.BTC
    assert cryptobot_eth.currency == CurrencyCode.ETH
    assert cryptobot_ton.currency == CurrencyCode.TON
    assert cryptobot_ltc.currency == CurrencyCode.LTC
    assert cryptobot_bnb.currency == CurrencyCode.BNB
    assert cryptobot_trx.currency == CurrencyCode.TRX
    assert all(
        option.network is None
        for option in (
            cryptobot_usdt,
            cryptobot_usdc,
            cryptobot_btc,
            cryptobot_eth,
            cryptobot_ton,
            cryptobot_ltc,
            cryptobot_bnb,
            cryptobot_trx,
        )
    )

    assert usdt_trc20.payment_method == PaymentMethod.CRYPTO
    assert usdt_trc20.currency == CurrencyCode.USDT
    assert usdt_trc20.network == NetworkCode.TRC20
    assert usdt_trc20.is_active is False

    assert xrp.currency == CurrencyCode.XRP
    assert xrp.network == NetworkCode.XRPL
    assert xrp.is_active is False


def test_telegram_stars_option_is_active_and_has_no_crypto_network():
    option = get_payment_option("telegram_stars")

    assert (
        option.payment_method
        == PaymentMethod.TELEGRAM_STARS
    )
    assert option.currency is None
    assert option.network is None
    assert option.is_active is True
    assert option.display_name == "Telegram Stars"


def test_get_payment_option_rejects_unsupported_code():
    with pytest.raises(ValueError, match="Unsupported payment option code: unknown"):
        get_payment_option("unknown")


@pytest.mark.asyncio
async def test_mock_payment_adapter_uses_stable_generated_txid_when_time_is_patched(
    monkeypatch,
):
    monkeypatch.setattr(mock_adapter_module.time, "time", lambda: 1234.567)
    adapter = MockPaymentAdapter()

    transactions = await adapter.fetch_transactions()

    assert adapter.txid == "mock_txid_1234567"
    assert len(transactions) == 1
    tx = transactions[0]
    assert tx.txid == "mock_txid_1234567"
    assert tx.amount == Decimal("4.00")
    assert tx.currency == "USDT"
    assert tx.network == "TRC20"
    assert tx.provider == "mock"
    assert tx.raw_payload["source"] == "mock_adapter"


@pytest.mark.asyncio
async def test_mock_payment_adapter_custom_values_are_copied_to_normalized_transaction():
    adapter = MockPaymentAdapter(
        txid="custom-tx",
        amount=Decimal("7.25"),
        currency="USDC",
        network="POLYGON",
        address_from="from-wallet",
        address_to="to-wallet",
        confirmations=19,
    )

    [tx] = await adapter.fetch_transactions()

    assert tx == NormalizedTransaction(
        txid="custom-tx",
        amount=Decimal("7.25"),
        currency="USDC",
        network="POLYGON",
        address_from="from-wallet",
        address_to="to-wallet",
        memo_tag=None,
        confirmations=19,
        provider="mock",
        raw_payload={
            "source": "mock_adapter",
            "txid": "custom-tx",
            "amount": "7.25",
            "currency": "USDC",
            "network": "POLYGON",
            "address_from": "from-wallet",
            "address_to": "to-wallet",
            "confirmations": 19,
        },
    )


def test_normalized_transaction_repr_contains_only_core_public_diagnostics():
    tx = NormalizedTransaction(
        txid="tx-1",
        amount=Decimal("4.00"),
        currency="USDT",
        network="TRC20",
        address_from="secret-from",
        address_to="secret-to",
    )

    assert repr(tx) == (
        "NormalizedTransaction(txid='tx-1', amount=4.00, currency=USDT, network=TRC20)"
    )
    assert "secret-from" not in repr(tx)
    assert "secret-to" not in repr(tx)


def test_payment_adapter_registry_returns_mock_adapter_as_active_adapter():
    registry = PaymentAdapterRegistry()

    adapters = registry.get_active_adapters()

    assert len(adapters) == 1
    assert isinstance(adapters[0], MockPaymentAdapter)
    assert adapters[0].name == "mock"


def test_get_payment_adapter_registry_returns_new_registry_instance_each_call():
    first = get_payment_adapter_registry()
    second = get_payment_adapter_registry()

    assert isinstance(first, PaymentAdapterRegistry)
    assert isinstance(second, PaymentAdapterRegistry)
    assert first is not second
    assert first.get_active_adapters() is not second.get_active_adapters()
