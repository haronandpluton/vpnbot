from __future__ import annotations

import json
from decimal import Decimal
from types import SimpleNamespace

import pytest

import app.services.cryptobot_payment_service as cryptobot_module
from app.common.enums import CurrencyCode
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

        if self.order is None:
            return None

        if self.order.id != order_id:
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
    expected_amount=Decimal("4.00"),
    price_usd=Decimal("4.00"),
    destination_address: str | None = None,
    destination_memo_tag: str | None = None,
    comment: str | None = None,
):
    return SimpleNamespace(
        id=order_id,
        expected_amount=expected_amount,
        price_usd=price_usd,
        expected_currency=None,
        expected_network="TRC20",
        destination_address=destination_address,
        destination_memo_tag=destination_memo_tag,
        comment=comment,
    )


def make_settings(
    *,
    enabled: bool = True,
    asset: str = "USDT",
    expires_in: int = 900,
):
    return SimpleNamespace(
        cryptobot_enabled=enabled,
        cryptobot_asset=asset,
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


def test_invoice_id_from_order_reads_memo_tag_first():
    service = CryptoBotPaymentService.__new__(CryptoBotPaymentService)

    order = make_order(
        destination_memo_tag="55822653",
        comment=json.dumps(
            {
                "provider": "cryptobot",
                "invoice_id": "111",
            }
        ),
    )

    assert service._invoice_id_from_order(order) == 55822653


def test_invoice_id_from_order_reads_cryptobot_comment():
    service = CryptoBotPaymentService.__new__(CryptoBotPaymentService)

    order = make_order(
        destination_memo_tag=None,
        comment=json.dumps(
            {
                "provider": "cryptobot",
                "invoice_id": "55822653",
            }
        ),
    )

    assert service._invoice_id_from_order(order) == 55822653


def test_invoice_id_from_order_ignores_invalid_comment():
    service = CryptoBotPaymentService.__new__(CryptoBotPaymentService)

    malformed_order = make_order(comment="{not-json")
    wrong_provider_order = make_order(
        comment=json.dumps(
            {
                "provider": "other",
                "invoice_id": "55822653",
            }
        )
    )

    assert service._invoice_id_from_order(malformed_order) is None
    assert service._invoice_id_from_order(wrong_provider_order) is None


@pytest.mark.asyncio
async def test_ensure_invoice_reuses_existing_invoice_without_creating_duplicate():
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
        "pay_url": "https://t.me/CryptoBot?start=existing",
        "status": "existing",
    }
    assert client.create_invoice_calls == []
    assert service.session.commit_count == 0


@pytest.mark.asyncio
async def test_ensure_invoice_creates_invoice_and_persists_payment_fields():
    invoice = {
        "invoice_id": 55822653,
        "hash": "test-hash",
        "amount": "4",
        "pay_url": "https://t.me/CryptoBot?start=test-hash",
        "mini_app_invoice_url": "https://t.me/CryptoBot/app?startapp=test-hash",
        "web_app_invoice_url": "https://pay.crypt.bot/test-hash",
    }
    order = make_order(order_id=23)
    client = FakeCryptoBotClient(invoice=invoice)
    service = make_service(order=order, client=client)

    result = await service.ensure_invoice_for_order(order.id)

    assert result == invoice
    assert client.create_invoice_calls == [
        {
            "asset": "USDT",
            "amount": Decimal("4.00"),
            "description": "PresentVPN order #23",
            "payload": "order:23",
            "expires_in": 900,
        }
    ]

    assert order.expected_amount == Decimal("4")
    assert order.expected_currency == CurrencyCode.USDT
    assert order.expected_network is None
    assert order.destination_address == "https://t.me/CryptoBot?start=test-hash"
    assert order.destination_memo_tag == "55822653"

    comment = json.loads(order.comment)
    assert comment["provider"] == "cryptobot"
    assert comment["invoice_id"] == "55822653"
    assert comment["hash"] == "test-hash"
    assert comment["pay_url"] == "https://t.me/CryptoBot?start=test-hash"

    assert service.session.commit_count == 1


@pytest.mark.asyncio
async def test_ensure_invoice_fails_when_cryptobot_disabled():
    order = make_order(order_id=23)
    service = make_service(
        order=order,
        settings=make_settings(enabled=False),
    )

    with pytest.raises(cryptobot_module.CryptoBotAPIError):
        await service.ensure_invoice_for_order(order.id)


@pytest.mark.asyncio
async def test_sync_unpaid_invoice_does_not_activate(monkeypatch):
    invoice = {
        "invoice_id": 55822653,
        "status": "active",
        "amount": "4.00",
    }
    order = make_order(
        order_id=23,
        destination_memo_tag="55822653",
    )
    client = FakeCryptoBotClient(invoice=invoice)
    service = make_service(order=order, client=client)

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
    assert client.get_invoice_calls == [55822653]


@pytest.mark.asyncio
async def test_sync_paid_invoice_delegates_to_activation_service(monkeypatch):
    invoice = {
        "invoice_id": 55822653,
        "status": "paid",
        "amount": "4.00",
        "asset": "USDT",
    }
    order = make_order(
        order_id=23,
        destination_memo_tag="55822653",
    )
    client = FakeCryptoBotClient(invoice=invoice)
    service = make_service(order=order, client=client)

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

    assert client.get_invoice_calls == [55822653]
    assert result["invoice"] == invoice
    assert result["event"].id == 17
    assert result["payment"].id == 17
    assert result["subscription"].id == 4
    assert result["config_uri"] == "vless://test-config"
    assert result["order_status"] == OrderStatus.ACTIVATED.value

    assert len(activation_calls) == 1
    call = activation_calls[0]

    assert call["order_id"] == 23
    assert call["amount"] == Decimal("4.00")
    assert call["provider"] == "cryptobot"
    assert call["event_type"] == "invoice_paid"
    assert call["external_event_id"] == "cryptobot:55822653"
    assert call["txid"] is None

    raw_payload = json.loads(call["raw_payload"])
    assert raw_payload["invoice_id"] == 55822653
    assert raw_payload["status"] == "paid"
    assert raw_payload["amount"] == "4.00"
