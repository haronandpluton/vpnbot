from __future__ import annotations

import json
from decimal import Decimal
from types import SimpleNamespace

import pytest

import app.services.cryptobot_payment_service as cryptobot_module
from app.common.enums import CurrencyCode
from app.payment_adapters.cryptobot import CryptoBotAPIError
from app.payment_core.enums.order_status import OrderStatus
from app.services.cryptobot_payment_service import CryptoBotPaymentService


class FakeSession:
    def __init__(self) -> None:
        self.commit_count = 0

    async def commit(self) -> None:
        self.commit_count += 1


class FakeOrderRepository:
    def __init__(self, order) -> None:
        self.order = order
        self.requested_ids: list[int] = []

    async def get_by_id(self, order_id: int):
        self.requested_ids.append(order_id)

        if self.order is None or self.order.id != order_id:
            return None

        return self.order


class FakeCryptoBotClient:
    def __init__(self, invoice: dict | None = None) -> None:
        self.invoice = invoice or {}
        self.create_invoice_calls: list[dict] = []
        self.get_invoice_calls: list[int | str] = []

    async def create_invoice(self, **kwargs):
        self.create_invoice_calls.append(kwargs)
        return self.invoice

    async def get_invoice(self, invoice_id: int | str):
        self.get_invoice_calls.append(invoice_id)
        return self.invoice


def make_order(
    *,
    order_id: int = 100,
    expected_amount=None,
    price_usd=Decimal("4.00"),
    expected_currency: CurrencyCode = CurrencyCode.USDT,
    destination_address: str | None = None,
    destination_memo_tag: str | None = None,
    comment: str | None = None,
):
    return SimpleNamespace(
        id=order_id,
        expected_amount=expected_amount,
        price_usd=price_usd,
        expected_currency=expected_currency,
        expected_network=None,
        destination_address=destination_address,
        destination_memo_tag=destination_memo_tag,
        comment=comment,
        status=OrderStatus.WAITING_PAYMENT,
    )


def make_settings(*, enabled: bool = True, expires_in: int = 900):
    return SimpleNamespace(
        cryptobot_enabled=enabled,
        cryptobot_asset="USDT",
        cryptobot_expires_in=expires_in,
        cryptobot_api_url="https://pay.crypt.bot/api",
        cryptobot_api_token="test-token",
    )


def make_service(
    *,
    order,
    client: FakeCryptoBotClient | None = None,
    settings=None,
):
    service = CryptoBotPaymentService.__new__(CryptoBotPaymentService)
    service.session = FakeSession()
    service.settings = settings or make_settings()
    service.order_repository = FakeOrderRepository(order)
    service._fake_client = client or FakeCryptoBotClient()
    service._client = lambda: service._fake_client
    return service


def paid_fiat_invoice(
    *,
    order_id: int = 23,
    invoice_id: int = 55822653,
    paid_asset: str = "USDT",
    paid_amount: str = "4.00",
    amount: str = "4.00",
) -> dict:
    return {
        "invoice_id": invoice_id,
        "status": "paid",
        "currency_type": "fiat",
        "fiat": "USD",
        "amount": amount,
        "accepted_assets": paid_asset,
        "paid_asset": paid_asset,
        "paid_amount": paid_amount,
        "payload": f"order:{order_id}",
    }


def test_invoice_id_from_order_reads_memo_tag_first():
    service = CryptoBotPaymentService.__new__(CryptoBotPaymentService)
    order = make_order(
        destination_memo_tag="55822653",
        comment=json.dumps({"provider": "cryptobot", "invoice_id": "111"}),
    )

    assert service._invoice_id_from_order(order) == 55822653


def test_invoice_id_from_order_reads_cryptobot_comment():
    service = CryptoBotPaymentService.__new__(CryptoBotPaymentService)
    order = make_order(
        comment=json.dumps({"provider": "cryptobot", "invoice_id": "55822653"}),
    )

    assert service._invoice_id_from_order(order) == 55822653


def test_invoice_id_from_order_ignores_invalid_comment():
    service = CryptoBotPaymentService.__new__(CryptoBotPaymentService)
    malformed_order = make_order(comment="{not-json")
    wrong_provider_order = make_order(
        comment=json.dumps({"provider": "other", "invoice_id": "55822653"})
    )

    assert service._invoice_id_from_order(malformed_order) is None
    assert service._invoice_id_from_order(wrong_provider_order) is None


@pytest.mark.asyncio
async def test_ensure_invoice_reuses_existing_invoice_without_duplicate():
    order = make_order(
        order_id=23,
        destination_address="https://t.me/CryptoBot?start=existing",
        destination_memo_tag="55822653",
    )
    client = FakeCryptoBotClient()
    service = make_service(order=order, client=client)

    result = await service.ensure_invoice_for_order(order.id)

    assert result == {
        "invoice_id": 55822653,
        "bot_invoice_url": "https://t.me/CryptoBot?start=existing",
        "pay_url": "https://t.me/CryptoBot?start=existing",
        "status": "existing",
    }
    assert client.create_invoice_calls == []
    assert service.session.commit_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("currency", "asset"),
    [
        (CurrencyCode.USDT, "USDT"),
        (CurrencyCode.USDC, "USDC"),
        (CurrencyCode.BTC, "BTC"),
        (CurrencyCode.ETH, "ETH"),
        (CurrencyCode.TON, "TON"),
        (CurrencyCode.LTC, "LTC"),
        (CurrencyCode.BNB, "BNB"),
        (CurrencyCode.TRX, "TRX"),
    ],
)
async def test_ensure_invoice_creates_usd_fiat_invoice_for_selected_asset(
    currency,
    asset,
):
    invoice = {
        "invoice_id": 55822653,
        "hash": "test-hash",
        "currency_type": "fiat",
        "fiat": "USD",
        "amount": "4.00",
        "accepted_assets": asset,
        "bot_invoice_url": "https://t.me/CryptoBot?start=test-hash",
        "pay_url": "https://deprecated.example/test-hash",
        "mini_app_invoice_url": "https://t.me/CryptoBot/app?startapp=test-hash",
        "web_app_invoice_url": "https://pay.crypt.bot/test-hash",
    }
    order = make_order(order_id=23, expected_currency=currency)
    client = FakeCryptoBotClient(invoice=invoice)
    service = make_service(order=order, client=client)

    result = await service.ensure_invoice_for_order(order.id)

    assert result == invoice
    assert client.create_invoice_calls == [
        {
            "fiat": "USD",
            "accepted_assets": asset,
            "amount": Decimal("4.00"),
            "description": "PresentVPN order #23",
            "payload": "order:23",
            "expires_in": 900,
        }
    ]
    assert order.expected_amount is None
    assert order.expected_currency == currency
    assert order.expected_network is None
    assert order.destination_address == "https://t.me/CryptoBot?start=test-hash"
    assert order.destination_memo_tag == "55822653"

    comment = json.loads(order.comment)
    assert comment["provider"] == "cryptobot"
    assert comment["invoice_id"] == "55822653"
    assert comment["currency_type"] == "fiat"
    assert comment["fiat"] == "USD"
    assert comment["amount_usd"] == "4.00"
    assert comment["accepted_assets"] == asset
    assert comment["pay_url"] == "https://t.me/CryptoBot?start=test-hash"
    assert service.session.commit_count == 1


@pytest.mark.asyncio
async def test_ensure_invoice_fails_when_cryptobot_disabled():
    service = make_service(
        order=make_order(order_id=23),
        settings=make_settings(enabled=False),
    )

    with pytest.raises(CryptoBotAPIError, match="disabled"):
        await service.ensure_invoice_for_order(23)


@pytest.mark.asyncio
async def test_sync_unpaid_invoice_does_not_activate(monkeypatch):
    invoice = {"invoice_id": 55822653, "status": "active", "amount": "4.00"}
    order = make_order(order_id=23, destination_memo_tag="55822653")
    service = make_service(order=order, client=FakeCryptoBotClient(invoice))

    class FailingPaymentActivationService:
        def __init__(self, session) -> None:
            raise AssertionError("Unpaid invoice must not activate order")

    monkeypatch.setattr(
        cryptobot_module,
        "PaymentActivationService",
        FailingPaymentActivationService,
    )

    result = await service.sync_paid_invoice_and_activate(order.id)

    assert result == invoice
    assert service._fake_client.get_invoice_calls == [55822653]


@pytest.mark.asyncio
async def test_sync_paid_fiat_invoice_uses_paid_amount_and_stable_event_id(monkeypatch):
    invoice = paid_fiat_invoice(paid_amount="0.00006125")
    order = make_order(order_id=23, destination_memo_tag="55822653")
    service = make_service(order=order, client=FakeCryptoBotClient(invoice))
    activation_calls: list[dict] = []

    class FakePaymentActivationService:
        def __init__(self, session) -> None:
            self.session = session

        async def process_confirmed_payment_event_and_activate(self, **kwargs):
            activation_calls.append(kwargs)
            return (
                SimpleNamespace(id=17),
                SimpleNamespace(id=17),
                SimpleNamespace(id=4),
                "vless://test-config",
            )

    monkeypatch.setattr(
        cryptobot_module,
        "PaymentActivationService",
        FakePaymentActivationService,
    )

    result = await service.sync_paid_invoice_and_activate(order.id)

    assert result["subscription"].id == 4
    assert result["order_status"] == OrderStatus.ACTIVATED.value
    assert len(activation_calls) == 1
    call = activation_calls[0]
    assert call["order_id"] == 23
    assert call["amount"] == Decimal("0.00006125")
    assert call["provider"] == "cryptobot"
    assert call["event_type"] == "invoice_paid"
    assert call["external_event_id"] == "cryptobot:55822653"
    assert call["txid"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("paid_asset", "ETH", "wrong_currency"),
        ("payload", "order:999", "wrong_payload"),
        ("amount", "7.00", "wrong_amount"),
    ],
)
async def test_sync_invalid_paid_invoice_is_persisted_without_activation(
    monkeypatch,
    field,
    value,
    reason,
):
    invoice = paid_fiat_invoice()
    invoice[field] = value
    order = make_order(order_id=23, destination_memo_tag="55822653")
    service = make_service(order=order, client=FakeCryptoBotClient(invoice))
    invalid_calls: list[dict] = []

    class FakePaymentEventService:
        def __init__(self, session) -> None:
            self.session = session

        async def process_invalid_event(self, **kwargs):
            invalid_calls.append(kwargs)
            return SimpleNamespace(id=1), SimpleNamespace(id=2), order

    class FailingPaymentActivationService:
        def __init__(self, session) -> None:
            raise AssertionError("Invalid invoice must not activate order")

    monkeypatch.setattr(
        cryptobot_module,
        "PaymentEventService",
        FakePaymentEventService,
    )
    monkeypatch.setattr(
        cryptobot_module,
        "PaymentActivationService",
        FailingPaymentActivationService,
    )

    result = await service.sync_paid_invoice_and_activate(order.id)

    assert result["validation_error"] == reason
    assert result["subscription"] is None
    assert len(invalid_calls) == 1
    call = invalid_calls[0]
    assert call["external_event_id"] == "cryptobot:55822653"
    assert call["reason"] == reason
    if field == "paid_asset":
        assert call["amount"] == Decimal("4.000000")


@pytest.mark.asyncio
async def test_sync_legacy_crypto_invoice_remains_supported(monkeypatch):
    invoice = {
        "invoice_id": 55822653,
        "status": "paid",
        "currency_type": "crypto",
        "asset": "USDT",
        "amount": "4.00",
        "paid_amount": "4.00",
        "payload": "order:23",
    }
    order = make_order(
        order_id=23,
        expected_amount=Decimal("4.00"),
        destination_memo_tag="55822653",
    )
    service = make_service(order=order, client=FakeCryptoBotClient(invoice))
    calls: list[dict] = []

    class FakePaymentActivationService:
        def __init__(self, session) -> None:
            pass

        async def process_confirmed_payment_event_and_activate(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(id=1), SimpleNamespace(id=2), None, None

    monkeypatch.setattr(
        cryptobot_module,
        "PaymentActivationService",
        FakePaymentActivationService,
    )

    await service.sync_paid_invoice_and_activate(order.id)

    assert calls[0]["amount"] == Decimal("4.00")


@pytest.mark.asyncio
async def test_sync_paid_fiat_invoice_rejects_missing_paid_amount():
    invoice = paid_fiat_invoice()
    invoice.pop("paid_amount")
    order = make_order(order_id=23, destination_memo_tag="55822653")
    service = make_service(order=order, client=FakeCryptoBotClient(invoice))

    with pytest.raises(CryptoBotAPIError, match="paid_amount"):
        await service.sync_paid_invoice_and_activate(order.id)
