from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

import app.bot.handlers.admin_active_subscriptions as active_module
import app.bot.handlers.admin_invalid_payments as invalid_module
from app.bot.handlers.admin_active_subscriptions import (
    _split_messages,
    admin_active_subscriptions_command,
)
from app.bot.handlers.admin_invalid_payments import admin_invalid_payments_command


class FakeMessage:
    def __init__(self, *, text: str | None = None, from_user=None) -> None:
        self.text = text
        self.from_user = from_user
        self.answer_calls: list[dict] = []

    async def answer(self, text: str, **kwargs) -> None:
        self.answer_calls.append({"text": text, **kwargs})


class FakeInvalidPaymentsService:
    instances: list["FakeInvalidPaymentsService"] = []
    items = []

    def __init__(self, session) -> None:
        self.session = session
        self.calls: list[dict] = []
        self.__class__.instances.append(self)

    async def get_last_invalid_payments(self, **kwargs):
        self.calls.append(kwargs)
        return self.__class__.items


class FakeActiveSubscriptionsService:
    instances: list["FakeActiveSubscriptionsService"] = []
    items = []

    def __init__(self, session) -> None:
        self.session = session
        self.calls: list[dict] = []
        self.__class__.instances.append(self)

    async def get_active_subscriptions(self, **kwargs):
        self.calls.append(kwargs)
        return self.__class__.items


@pytest.fixture(autouse=True)
def patch_dependencies(monkeypatch):
    FakeInvalidPaymentsService.instances = []
    FakeInvalidPaymentsService.items = []
    FakeActiveSubscriptionsService.instances = []
    FakeActiveSubscriptionsService.items = []

    monkeypatch.setattr(
        invalid_module,
        "AdminInvalidPaymentsService",
        FakeInvalidPaymentsService,
    )
    monkeypatch.setattr(
        active_module,
        "AdminActiveSubscriptionsService",
        FakeActiveSubscriptionsService,
    )
    monkeypatch.setattr(
        invalid_module,
        "get_settings",
        lambda: SimpleNamespace(admin_ids=[777]),
    )
    monkeypatch.setattr(
        active_module,
        "get_settings",
        lambda: SimpleNamespace(admin_ids=[777]),
    )


def make_admin_message():
    return FakeMessage(from_user=SimpleNamespace(id=777))


def make_non_admin_message():
    return FakeMessage(from_user=SimpleNamespace(id=123))


def test_invalid_payments_helpers_format_decimal_datetime_and_empty_values():
    assert invalid_module._format_decimal(None) == "—"
    assert invalid_module._format_decimal(Decimal("4.00000000")) == "4"
    assert invalid_module._format_decimal(Decimal("4.123456789")) == "4.12345679"
    assert invalid_module._format_datetime(None) == "—"
    assert (
        invalid_module._format_datetime(
            datetime(2026, 7, 5, 12, 34, tzinfo=timezone.utc)
        )
        == "05.07.2026 12:34"
    )
    assert invalid_module._clean(None) == "—"
    assert invalid_module._clean("") == "—"
    assert invalid_module._clean("x") == "x"


@pytest.mark.asyncio
async def test_invalid_payments_command_returns_when_message_has_no_from_user():
    message = FakeMessage(from_user=None)

    await admin_invalid_payments_command(message, session="session")

    assert message.answer_calls == []
    assert FakeInvalidPaymentsService.instances == []


@pytest.mark.asyncio
async def test_invalid_payments_command_rejects_non_admin_before_service():
    message = make_non_admin_message()

    await admin_invalid_payments_command(message, session="session")

    assert message.answer_calls == [{"text": "Нет доступа."}]
    assert FakeInvalidPaymentsService.instances == []


@pytest.mark.asyncio
async def test_invalid_payments_command_sends_empty_state_for_no_items():
    message = make_admin_message()

    await admin_invalid_payments_command(message, session="session")

    service = FakeInvalidPaymentsService.instances[0]
    assert service.session == "session"
    assert service.calls == [{"limit": 10}]
    assert message.answer_calls == [{"text": "Некорректных платежей пока нет."}]


@pytest.mark.asyncio
async def test_invalid_payments_command_formats_invalid_payment_items():
    FakeInvalidPaymentsService.items = [
        SimpleNamespace(
            payment_id=11,
            order_id=22,
            event_id=33,
            user_id=44,
            telegram_id=555,
            username="ivan",
            amount=Decimal("4.00000000"),
            currency="USDT",
            network="TRC20",
            reason="wrong_network",
            txid="tx-1",
            created_at=datetime(2026, 7, 5, 12, 34, tzinfo=timezone.utc),
        )
    ]
    message = make_admin_message()

    await admin_invalid_payments_command(message, session="session")

    call = message.answer_calls[0]
    assert call["parse_mode"] == "HTML"
    text = call["text"]
    assert "<b>Некорректные платежи</b>" in text
    assert "Последние 10 записей:" in text
    assert "<b>Payment #11</b>" in text
    assert "Order ID: 22" in text
    assert "Event ID: 33" in text
    assert "User ID: 44" in text
    assert "Telegram ID: 555" in text
    assert "Username: @ivan" in text
    assert "Amount: 4 USDT" in text
    assert "Network: TRC20" in text
    assert "Reason: wrong_network" in text
    assert "TXID: <code>tx-1</code>" in text
    assert "Created: 05.07.2026 12:34" in text


def test_active_subscriptions_helpers_and_split_messages_are_stable():
    assert active_module._clean(None) == "—"
    assert active_module._clean("") == "—"
    assert active_module._clean(23) == "23"
    assert active_module._format_datetime(None) == "—"
    assert (
        active_module._format_datetime(
            datetime(2026, 7, 5, 12, 34, tzinfo=timezone.utc)
        )
        == "05.07.2026 12:34"
    )
    assert _split_messages(["aaa", "bbb", "ccc"], limit=6) == ["aaabbb", "ccc"]
    assert _split_messages(["aaa", "bbbb", "cc"], limit=6) == ["aaa", "bbbbcc"]


@pytest.mark.asyncio
async def test_active_subscriptions_command_returns_when_message_has_no_from_user():
    message = FakeMessage(from_user=None)

    await admin_active_subscriptions_command(message, session="session")

    assert message.answer_calls == []
    assert FakeActiveSubscriptionsService.instances == []


@pytest.mark.asyncio
async def test_active_subscriptions_command_rejects_non_admin_before_service():
    message = make_non_admin_message()

    await admin_active_subscriptions_command(message, session="session")

    assert message.answer_calls == [{"text": "Нет доступа."}]
    assert FakeActiveSubscriptionsService.instances == []


@pytest.mark.asyncio
async def test_active_subscriptions_command_sends_empty_state_for_no_items():
    message = make_admin_message()

    await admin_active_subscriptions_command(message, session="session")

    service = FakeActiveSubscriptionsService.instances[0]
    assert service.session == "session"
    assert service.calls == [{"limit": 50}]
    assert message.answer_calls == [{"text": "Активных подписок пока нет."}]


@pytest.mark.asyncio
async def test_active_subscriptions_command_formats_active_subscription_items():
    FakeActiveSubscriptionsService.items = [
        SimpleNamespace(
            subscription_id=14,
            order_id=23,
            user_id=7,
            telegram_id=777,
            username="ivan",
            status="active",
            order_tariff_code="devices_1",
            order_status="activated",
            device_limit=1,
            vpn_server_id=3,
            starts_at=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
            expires_at=datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc),
            last_access_sent_at=None,
            uuid="uuid-1",
        )
    ]
    message = make_admin_message()

    await admin_active_subscriptions_command(message, session="session")

    assert len(message.answer_calls) == 1
    call = message.answer_calls[0]
    assert call["parse_mode"] == "HTML"
    text = call["text"]
    assert "<b>Активные подписки</b>" in text
    assert "Найдено: 1" in text
    assert "<b>Subscription #14</b>" in text
    assert "Order ID: 23" in text
    assert "User ID: 7" in text
    assert "Telegram ID: 777" in text
    assert "Username: @ivan" in text
    assert "Status: active" in text
    assert "Tariff: devices_1" in text
    assert "Order status: activated" in text
    assert "Device limit: 1" in text
    assert "VPN server ID: 3" in text
    assert "Starts: 01.07.2026 12:00" in text
    assert "Expires: 01.08.2026 12:00" in text
    assert "Last access sent: —" in text
    assert "UUID: <code>uuid-1</code>" in text
    assert "<code>/admin_order 23</code>" in text
    assert "<code>/admin_resend_config 23</code>" in text


@pytest.mark.asyncio
async def test_active_subscriptions_command_splits_long_output_into_multiple_messages():
    FakeActiveSubscriptionsService.items = [
        SimpleNamespace(
            subscription_id=index,
            order_id=index + 100,
            user_id=index + 200,
            telegram_id=index + 300,
            username=f"user{index}",
            status="active",
            order_tariff_code="devices_1",
            order_status="activated",
            device_limit=1,
            vpn_server_id=3,
            starts_at=None,
            expires_at=None,
            last_access_sent_at=None,
            uuid=f"uuid-{index}",
        )
        for index in range(1, 25)
    ]
    message = make_admin_message()

    await admin_active_subscriptions_command(message, session="session")

    assert len(message.answer_calls) > 1
    assert all(call["parse_mode"] == "HTML" for call in message.answer_calls)
    joined = "".join(call["text"] for call in message.answer_calls)
    assert "Найдено: 24" in joined
    assert "Subscription #1" in joined
    assert "Subscription #24" in joined