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
from app.config.tariffs import TARIFFS, TariffConfig, get_tariff
from app.payment_adapters.base import NormalizedTransaction
from app.payment_adapters.mock import MockPaymentAdapter
from app.payment_adapters.registry import (
    PaymentAdapterRegistry,
    get_payment_adapter_registry,
)
from app.payment_core.enums.payment_method import PaymentMethod


def test_tariffs_have_expected_public_prices_device_limits_and_duration():
    assert get_tariff(TariffCode.DEVICES_1) == TariffConfig(
        code=TariffCode.DEVICES_1,
        title="1 устройство",
        device_limit=1,
        price_usd=Decimal("4.00"),
        duration_days=30,
    )
    assert get_tariff(TariffCode.DEVICES_2).device_limit == 2
    assert get_tariff(TariffCode.DEVICES_2).price_usd == Decimal("7.00")
    assert get_tariff(TariffCode.DEVICES_3).device_limit == 3
    assert get_tariff(TariffCode.DEVICES_3).price_usd == Decimal("10.00")


def test_tariff_configs_are_frozen_and_key_matches_code():
    assert set(TARIFFS) == {
        TariffCode.DEVICES_1,
        TariffCode.DEVICES_2,
        TariffCode.DEVICES_3,
    }
    assert all(key == tariff.code for key, tariff in TARIFFS.items())

    with pytest.raises(Exception):
        get_tariff(TariffCode.DEVICES_1).price_usd = Decimal("0.01")


def test_get_tariff_rejects_unsupported_code():
    with pytest.raises(ValueError, match="Unsupported tariff code: unknown"):
        get_tariff("unknown")


def test_payment_options_have_stable_codes_and_unique_sort_orders():
    assert all(code == option.code for code, option in PAYMENT_OPTIONS.items())
    assert len({option.sort_order for option in PAYMENT_OPTIONS.values()}) == len(
        PAYMENT_OPTIONS
    )
    assert all(isinstance(option, PaymentOptionConfig) for option in PAYMENT_OPTIONS.values())


def test_get_active_payment_options_returns_active_options_sorted_and_excludes_inactive_stars():
    options = get_active_payment_options()

    assert options == sorted(options, key=lambda item: item.sort_order)
    assert all(option.is_active for option in options)
    assert "telegram_stars" not in {option.code for option in options}
    assert options[0].code == "cryptobot_usdt"


def test_crypto_payment_options_have_currency_and_valid_network_rules():
    cryptobot = get_payment_option("cryptobot_usdt")
    usdt_trc20 = get_payment_option("usdt_trc20")
    xrp = get_payment_option("xrp_xrpl")

    assert cryptobot.payment_method == PaymentMethod.CRYPTO
    assert cryptobot.currency == CurrencyCode.USDT
    assert cryptobot.network is None

    assert usdt_trc20.payment_method == PaymentMethod.CRYPTO
    assert usdt_trc20.currency == CurrencyCode.USDT
    assert usdt_trc20.network == NetworkCode.TRC20

    assert xrp.currency == CurrencyCode.XRP
    assert xrp.network == NetworkCode.XRPL


def test_telegram_stars_option_is_present_but_inactive_and_has_no_crypto_network():
    option = get_payment_option("telegram_stars")

    assert option.payment_method == PaymentMethod.TELEGRAM_STARS
    assert option.currency is None
    assert option.network is None
    assert option.is_active is False
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
        "NormalizedTransaction(txid='tx-1', amount=4.00, "
        "currency=USDT, network=TRC20)"
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