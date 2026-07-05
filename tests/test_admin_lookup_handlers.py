from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

import app.bot.handlers.admin_lookup as lookup_module
from app.bot.handlers.admin_lookup import (
    _parse_id_from_command,
    admin_order_command,
    admin_payment_command,
)


class FakeMessage:
    def __init__(self, *, text: str | None = None, from_user=None) -> None:
        self.text = text
        self.from_user = from_user
        self.answer_calls: list[dict] = []

    async def answer(self, text: str, **kwargs) -> None:
        self.answer_calls.append({"text": text, **kwargs})


class FakeAdminLookupService:
    instances: list["FakeAdminLookupService"] = []
    order_result = None
    payment_result = None

    def __init__(self, session) -> None:
        self.session = session
        self.order_calls: list[int] = []
        self.payment_calls: list[int] = []
        self.__class__.instances.append(self)

    async def get_order_card(self, order_id: int):
        self.order_calls.append(order_id)
        return self.__class__.order_result

    async def get_payment_card(self, payment_id: int):
        self.payment_calls.append(payment_id)
        return self.__class__.payment_result


@pytest.fixture(autouse=True)
def patch_dependencies(monkeypatch):
    FakeAdminLookupService.instances = []
    FakeAdminLookupService.order_result = None
    FakeAdminLookupService.payment_result = None
    monkeypatch.setattr(lookup_module, "AdminLookupService", FakeAdminLookupService)
    monkeypatch.setattr(
        lookup_module,
        "get_settings",
        lambda: SimpleNamespace(admin_ids=[777]),
    )


def make_admin_message(text: str | None):
    return FakeMessage(text=text, from_user=SimpleNamespace(id=777))


def make_non_admin_message(text: str | None):
    return FakeMessage(text=text, from_user=SimpleNamespace(id=123))


def make_user():
    return SimpleNamespace(
        id=7,
        telegram_id=777000,
        username="ivan",
        first_name="Ivan",
        last_name="Redeemer",
        language_code="ru",
        is_admin=False,
        is_blocked=False,
        created_at=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
    )


def make_order():
    return SimpleNamespace(
        id=23,
        status="activated",
        user_id=7,
        tariff_code="devices_1",
        device_limit=1,
        price_usd=Decimal("4.00"),
        payment_method="crypto",
        payment_option_id=5,
        expected_amount=Decimal("4.00"),
        expected_currency="USDT",
        expected_network="TRC20",
        destination_address="receiver-wallet",
        destination_memo_tag="memo-1",
        expires_at=datetime(2026, 7, 5, 12, 0, tzinfo=timezone.utc),
        paid_at=datetime(2026, 7, 5, 12, 1, tzinfo=timezone.utc),
        activated_at=datetime(2026, 7, 5, 12, 2, tzinfo=timezone.utc),
        source="bot",
        failure_reason=None,
        created_at=datetime(2026, 7, 5, 11, 0, tzinfo=timezone.utc),
        updated_at=datetime(2026, 7, 5, 12, 2, tzinfo=timezone.utc),
    )


def make_payment(payment_id: int = 31):
    return SimpleNamespace(
        id=payment_id,
        order_id=23,
        user_id=7,
        status="confirmed",
        payment_method="crypto",
        payment_option_id=5,
        amount=Decimal("4.00"),
        currency="USDT",
        network="TRC20",
        txid="tx-1",
        provider_payment_id="invoice-1",
        address_from="from-wallet",
        address_to="to-wallet",
        memo_tag="memo-1",
        confirmations=12,
        detected_at=datetime(2026, 7, 5, 12, 1, tzinfo=timezone.utc),
        confirmed_at=datetime(2026, 7, 5, 12, 2, tzinfo=timezone.utc),
        created_at=datetime(2026, 7, 5, 12, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 7, 5, 12, 2, tzinfo=timezone.utc),
    )


def make_event(event_id: int = 41):
    return SimpleNamespace(
        id=event_id,
        payment_id=31,
        event_type="payment_confirmed",
        processing_status="processed",
        error_message=None,
        external_event_id="ext-1",
        txid="tx-1",
        processed=True,
        processed_at=datetime(2026, 7, 5, 12, 2, tzinfo=timezone.utc),
        created_at=datetime(2026, 7, 5, 12, 1, tzinfo=timezone.utc),
    )


def make_subscription(subscription_id: int = 51):
    return SimpleNamespace(
        id=subscription_id,
        status="active",
        uuid="uuid-1",
        vpn_server_id=3,
        device_limit=1,
        starts_at=datetime(2026, 7, 5, 12, 2, tzinfo=timezone.utc),
        expires_at=datetime(2026, 8, 5, 12, 2, tzinfo=timezone.utc),
        last_access_sent_at=None,
        disabled_at=None,
        config_version=1,
        error_reason=None,
        created_at=datetime(2026, 7, 5, 12, 2, tzinfo=timezone.utc),
    )


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("/admin_order 23", 23),
        ("  /admin_order   23  ", 23),
        (None, None),
        ("/admin_order", None),
        ("/admin_order abc", None),
        ("/admin_order 23 extra", None),
    ],
)
def test_parse_id_from_command_accepts_single_numeric_argument(text, expected):
    assert _parse_id_from_command(FakeMessage(text=text)) == expected


@pytest.mark.asyncio
async def test_admin_order_command_returns_when_message_has_no_from_user():
    message = FakeMessage(text="/admin_order 23", from_user=None)

    await admin_order_command(message, session="session")

    assert message.answer_calls == []
    assert FakeAdminLookupService.instances == []


@pytest.mark.asyncio
async def test_admin_order_command_rejects_non_admin_before_service():
    message = make_non_admin_message("/admin_order 23")

    await admin_order_command(message, session="session")

    assert message.answer_calls == [{"text": "Нет доступа."}]
    assert FakeAdminLookupService.instances == []


@pytest.mark.asyncio
async def test_admin_order_command_sends_usage_for_invalid_args():
    message = make_admin_message("/admin_order abc")

    await admin_order_command(message, session="session")

    assert message.answer_calls == [
        {"text": "Использование:\n<code>/admin_order 68</code>", "parse_mode": "HTML"}
    ]
    assert FakeAdminLookupService.instances == []


@pytest.mark.asyncio
async def test_admin_order_command_sends_not_found_when_service_does_not_find_order():
    FakeAdminLookupService.order_result = SimpleNamespace(found=False)
    message = make_admin_message("/admin_order 23")

    await admin_order_command(message, session="session")

    service = FakeAdminLookupService.instances[0]
    assert service.session == "session"
    assert service.order_calls == [23]
    assert message.answer_calls == [{"text": "Order #23 не найден."}]


@pytest.mark.asyncio
async def test_admin_order_command_formats_order_card_with_related_entities():
    FakeAdminLookupService.order_result = SimpleNamespace(
        found=True,
        order=make_order(),
        user=make_user(),
        payments=[make_payment()],
        events=[make_event()],
        subscriptions=[make_subscription()],
    )
    message = make_admin_message("/admin_order 23")

    await admin_order_command(message, session="session")

    call = message.answer_calls[0]
    assert call["parse_mode"] == "HTML"
    text = call["text"]
    assert "<b>Admin Order Lookup</b>" in text
    assert "<b>Order</b>" in text
    assert "ID: 23" in text
    assert "Status: activated" in text
    assert "Destination address: <code>receiver-wallet</code>" in text
    assert "<b>User</b>" in text
    assert "Username: @ivan" in text
    assert "<b>Payments</b>" in text
    assert "Payment #31" in text
    assert "TXID: <code>tx-1</code>" in text
    assert "<b>Events</b>" in text
    assert "Event #41" in text
    assert "<b>Subscriptions</b>" in text
    assert "Subscription #51" in text
    assert "UUID: <code>uuid-1</code>" in text


@pytest.mark.asyncio
async def test_admin_order_command_formats_empty_related_sections():
    FakeAdminLookupService.order_result = SimpleNamespace(
        found=True,
        order=make_order(),
        user=None,
        payments=[],
        events=[],
        subscriptions=[],
    )
    message = make_admin_message("/admin_order 23")

    await admin_order_command(message, session="session")

    text = message.answer_calls[0]["text"]
    assert "<b>User</b>\nНе найден" in text
    assert "Нет платежей" in text
    assert "Нет событий" in text
    assert "Нет подписок" in text


@pytest.mark.asyncio
async def test_admin_payment_command_rejects_non_admin_before_service():
    message = make_non_admin_message("/admin_payment 31")

    await admin_payment_command(message, session="session")

    assert message.answer_calls == [{"text": "Нет доступа."}]
    assert FakeAdminLookupService.instances == []


@pytest.mark.asyncio
async def test_admin_payment_command_sends_usage_for_invalid_args():
    message = make_admin_message("/admin_payment abc")

    await admin_payment_command(message, session="session")

    assert message.answer_calls == [
        {"text": "Использование:\n<code>/admin_payment 96</code>", "parse_mode": "HTML"}
    ]
    assert FakeAdminLookupService.instances == []


@pytest.mark.asyncio
async def test_admin_payment_command_sends_not_found_when_service_does_not_find_payment():
    FakeAdminLookupService.payment_result = SimpleNamespace(found=False)
    message = make_admin_message("/admin_payment 31")

    await admin_payment_command(message, session="session")

    service = FakeAdminLookupService.instances[0]
    assert service.session == "session"
    assert service.payment_calls == [31]
    assert message.answer_calls == [{"text": "Payment #31 не найден."}]


@pytest.mark.asyncio
async def test_admin_payment_command_formats_payment_card_with_related_entities():
    FakeAdminLookupService.payment_result = SimpleNamespace(
        found=True,
        payment=make_payment(),
        order=make_order(),
        user=make_user(),
        events=[make_event()],
        subscriptions=[make_subscription()],
    )
    message = make_admin_message("/admin_payment 31")

    await admin_payment_command(message, session="session")

    call = message.answer_calls[0]
    assert call["parse_mode"] == "HTML"
    text = call["text"]
    assert "<b>Admin Payment Lookup</b>" in text
    assert "<b>Payment</b>" in text
    assert "ID: 31" in text
    assert "Order ID: 23" in text
    assert "Address from: <code>from-wallet</code>" in text
    assert "Address to: <code>to-wallet</code>" in text
    assert "<b>Order</b>" in text
    assert "<b>User</b>" in text
    assert "<b>Events</b>" in text
    assert "Event #41" in text
    assert "<b>Subscriptions</b>" in text
    assert "Subscription #51" in text