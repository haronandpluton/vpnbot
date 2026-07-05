from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

import app.bot.handlers.admin_actions_lookup as actions_module
import app.bot.handlers.admin_subscription_lookup as subscription_module
import app.bot.handlers.admin_user_lookup as user_module
from app.bot.handlers.admin_actions_lookup import (
    admin_actions_command,
    admin_actions_subscription_command,
    admin_actions_user_command,
)
from app.bot.handlers.admin_subscription_lookup import admin_subscription_command
from app.bot.handlers.admin_user_lookup import admin_user_command, admin_user_tg_command


class FakeMessage:
    def __init__(self, *, text: str | None = None, from_user=None) -> None:
        self.text = text
        self.from_user = from_user
        self.answer_calls: list[dict] = []

    async def answer(self, text: str, **kwargs) -> None:
        self.answer_calls.append({"text": text, **kwargs})


class FakeAdminUserLookupService:
    instances: list["FakeAdminUserLookupService"] = []
    by_user_id_result = None
    by_telegram_id_result = None

    def __init__(self, session) -> None:
        self.session = session
        self.user_id_calls: list[int] = []
        self.telegram_id_calls: list[int] = []
        self.__class__.instances.append(self)

    async def get_user_card_by_user_id(self, *, user_id: int):
        self.user_id_calls.append(user_id)
        return self.__class__.by_user_id_result

    async def get_user_card_by_telegram_id(self, *, telegram_id: int):
        self.telegram_id_calls.append(telegram_id)
        return self.__class__.by_telegram_id_result


class FakeAdminSubscriptionLookupService:
    instances: list["FakeAdminSubscriptionLookupService"] = []
    result = None

    def __init__(self, session) -> None:
        self.session = session
        self.calls: list[int] = []
        self.__class__.instances.append(self)

    async def get_subscription_card(self, *, subscription_id: int):
        self.calls.append(subscription_id)
        return self.__class__.result


class FakeAdminActionLookupService:
    instances: list["FakeAdminActionLookupService"] = []
    last_actions = []
    subscription_actions = []
    user_actions = []

    def __init__(self, session) -> None:
        self.session = session
        self.last_calls: list[dict] = []
        self.subscription_calls: list[dict] = []
        self.user_calls: list[dict] = []
        self.__class__.instances.append(self)

    async def get_last_actions(self, **kwargs):
        self.last_calls.append(kwargs)
        return self.__class__.last_actions

    async def get_actions_by_subscription_id(self, **kwargs):
        self.subscription_calls.append(kwargs)
        return self.__class__.subscription_actions

    async def get_actions_by_target_user_id(self, **kwargs):
        self.user_calls.append(kwargs)
        return self.__class__.user_actions


@pytest.fixture(autouse=True)
def patch_dependencies(monkeypatch):
    FakeAdminUserLookupService.instances = []
    FakeAdminUserLookupService.by_user_id_result = None
    FakeAdminUserLookupService.by_telegram_id_result = None

    FakeAdminSubscriptionLookupService.instances = []
    FakeAdminSubscriptionLookupService.result = None

    FakeAdminActionLookupService.instances = []
    FakeAdminActionLookupService.last_actions = []
    FakeAdminActionLookupService.subscription_actions = []
    FakeAdminActionLookupService.user_actions = []

    monkeypatch.setattr(
        user_module,
        "AdminUserLookupService",
        FakeAdminUserLookupService,
    )
    monkeypatch.setattr(
        subscription_module,
        "AdminSubscriptionLookupService",
        FakeAdminSubscriptionLookupService,
    )
    monkeypatch.setattr(
        actions_module,
        "AdminActionLookupService",
        FakeAdminActionLookupService,
    )
    monkeypatch.setattr(
        user_module,
        "get_settings",
        lambda: SimpleNamespace(admin_ids=[777]),
    )
    monkeypatch.setattr(
        subscription_module,
        "get_settings",
        lambda: SimpleNamespace(admin_ids=[777]),
    )
    monkeypatch.setattr(
        actions_module,
        "get_settings",
        lambda: SimpleNamespace(admin_ids=[777]),
    )


def admin_message(text: str | None):
    return FakeMessage(text=text, from_user=SimpleNamespace(id=777))


def non_admin_message(text: str | None):
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
        updated_at=datetime(2026, 7, 5, 12, 0, tzinfo=timezone.utc),
    )


def make_order(order_id: int = 23):
    return SimpleNamespace(
        id=order_id,
        status="activated",
        tariff_code="devices_1",
        device_limit=1,
        price_usd=Decimal("4.00"),
        payment_method="crypto",
        payment_option_id=5,
        expected_amount=Decimal("4.00"),
        expected_currency="USDT",
        expected_network="TRC20",
        destination_address="receiver-wallet",
        expires_at=datetime(2026, 7, 5, 12, 0, tzinfo=timezone.utc),
        paid_at=datetime(2026, 7, 5, 12, 1, tzinfo=timezone.utc),
        activated_at=datetime(2026, 7, 5, 12, 2, tzinfo=timezone.utc),
        failure_reason=None,
        created_at=datetime(2026, 7, 5, 11, 0, tzinfo=timezone.utc),
    )


def make_payment(payment_id: int = 31):
    return SimpleNamespace(
        id=payment_id,
        order_id=23,
        status="confirmed",
        amount=Decimal("4.00"),
        currency="USDT",
        network="TRC20",
        txid="tx-1",
        confirmations=12,
        created_at=datetime(2026, 7, 5, 12, 1, tzinfo=timezone.utc),
    )


def make_event(event_id: int = 41):
    return SimpleNamespace(
        id=event_id,
        payment_id=31,
        event_type="payment_confirmed",
        processing_status="processed",
        error_message=None,
        txid="tx-1",
        processed=True,
        processed_at=datetime(2026, 7, 5, 12, 2, tzinfo=timezone.utc),
        created_at=datetime(2026, 7, 5, 12, 1, tzinfo=timezone.utc),
    )


def make_subscription(subscription_id: int = 51):
    return SimpleNamespace(
        id=subscription_id,
        order_id=23,
        user_id=7,
        vpn_server_id=3,
        status="active",
        uuid="uuid-1",
        device_limit=1,
        starts_at=datetime(2026, 7, 5, 12, 2, tzinfo=timezone.utc),
        expires_at=datetime(2026, 8, 5, 12, 2, tzinfo=timezone.utc),
        last_access_sent_at=None,
        disabled_at=None,
        config_version=1,
        error_reason=None,
        created_at=datetime(2026, 7, 5, 12, 2, tzinfo=timezone.utc),
        updated_at=datetime(2026, 7, 5, 12, 2, tzinfo=timezone.utc),
    )


def make_action(action_id: int = 91):
    return SimpleNamespace(
        action_id=action_id,
        action_type="subscription_extended",
        admin_user_id=1,
        admin_telegram_id=777,
        admin_username="admin",
        target_user_id=7,
        order_id=23,
        payment_id=None,
        subscription_id=51,
        reason="manual fix",
        payload='{"days": 30}',
        created_at=datetime(2026, 7, 5, 12, 0, tzinfo=timezone.utc),
    )


@pytest.mark.asyncio
async def test_admin_user_command_rejects_non_admin_before_service():
    message = non_admin_message("/admin_user 7")

    await admin_user_command(message, session="session")

    assert message.answer_calls == [{"text": "Нет доступа."}]
    assert FakeAdminUserLookupService.instances == []


@pytest.mark.asyncio
async def test_admin_user_command_sends_usage_for_invalid_args():
    message = admin_message("/admin_user broken")

    await admin_user_command(message, session="session")

    assert message.answer_calls == [
        {"text": "Использование:\n<code>/admin_user 46</code>", "parse_mode": "HTML"}
    ]
    assert FakeAdminUserLookupService.instances == []


@pytest.mark.asyncio
async def test_admin_user_command_sends_not_found():
    FakeAdminUserLookupService.by_user_id_result = SimpleNamespace(found=False)
    message = admin_message("/admin_user 7")

    await admin_user_command(message, session="session")

    service = FakeAdminUserLookupService.instances[0]
    assert service.session == "session"
    assert service.user_id_calls == [7]
    assert message.answer_calls == [{"text": "User #7 не найден."}]


@pytest.mark.asyncio
async def test_admin_user_command_formats_user_card_with_related_entities():
    FakeAdminUserLookupService.by_user_id_result = SimpleNamespace(
        found=True,
        user=make_user(),
        invalid_payments_count=2,
        orders=[make_order()],
        payments=[make_payment()],
        subscriptions=[make_subscription()],
    )
    message = admin_message("/admin_user 7")

    await admin_user_command(message, session="session")

    call = message.answer_calls[0]
    assert call["parse_mode"] == "HTML"
    text = call["text"]
    assert "<b>Admin User Lookup</b>" in text
    assert "Telegram ID: 777000" in text
    assert "Username: @ivan" in text
    assert "Invalid payments count: 2" in text
    assert "<b>Order #23</b>" in text
    assert "Command: <code>/admin_order 23</code>" in text
    assert "<b>Payment #31</b>" in text
    assert "Command: <code>/admin_payment 31</code>" in text
    assert "<b>Subscription #51</b>" in text
    assert "<code>/admin_resend_config 23</code>" in text


@pytest.mark.asyncio
async def test_admin_user_tg_command_uses_telegram_id_lookup_and_not_found_text():
    FakeAdminUserLookupService.by_telegram_id_result = SimpleNamespace(found=False)
    message = admin_message("/admin_user_tg 777000")

    await admin_user_tg_command(message, session="session")

    service = FakeAdminUserLookupService.instances[0]
    assert service.telegram_id_calls == [777000]
    assert message.answer_calls == [{"text": "User с Telegram ID 777000 не найден."}]


@pytest.mark.asyncio
async def test_admin_subscription_command_rejects_non_admin_before_service():
    message = non_admin_message("/admin_subscription 51")

    await admin_subscription_command(message, session="session")

    assert message.answer_calls == [{"text": "Нет доступа."}]
    assert FakeAdminSubscriptionLookupService.instances == []


@pytest.mark.asyncio
async def test_admin_subscription_command_sends_usage_for_invalid_args():
    message = admin_message("/admin_subscription broken")

    await admin_subscription_command(message, session="session")

    assert message.answer_calls == [
        {
            "text": "Использование:\n<code>/admin_subscription 14</code>",
            "parse_mode": "HTML",
        }
    ]
    assert FakeAdminSubscriptionLookupService.instances == []


@pytest.mark.asyncio
async def test_admin_subscription_command_sends_not_found():
    FakeAdminSubscriptionLookupService.result = SimpleNamespace(found=False)
    message = admin_message("/admin_subscription 51")

    await admin_subscription_command(message, session="session")

    service = FakeAdminSubscriptionLookupService.instances[0]
    assert service.session == "session"
    assert service.calls == [51]
    assert message.answer_calls == [{"text": "Subscription #51 не найдена."}]


@pytest.mark.asyncio
async def test_admin_subscription_command_formats_subscription_card_with_related_entities():
    FakeAdminSubscriptionLookupService.result = SimpleNamespace(
        found=True,
        subscription=make_subscription(),
        user=make_user(),
        order=make_order(),
        payments=[make_payment()],
        events=[make_event()],
    )
    message = admin_message("/admin_subscription 51")

    await admin_subscription_command(message, session="session")

    call = message.answer_calls[0]
    assert call["parse_mode"] == "HTML"
    text = call["text"]
    assert "<b>Admin Subscription Lookup</b>" in text
    assert "<b>Subscription</b>" in text
    assert "ID: 51" in text
    assert "UUID: <code>uuid-1</code>" in text
    assert "<b>User</b>" in text
    assert "Username: @ivan" in text
    assert "<b>Order</b>" in text
    assert "Destination address: <code>receiver-wallet</code>" in text
    assert "<b>Payments</b>" in text
    assert "Payment #31" in text
    assert "<b>Events</b>" in text
    assert "Event #41" in text
    assert "<code>/admin_order 23</code>" in text
    assert "<code>/admin_resend_config 23</code>" in text


@pytest.mark.asyncio
async def test_admin_actions_command_rejects_non_admin_before_service():
    message = non_admin_message("/admin_actions")

    await admin_actions_command(message, session="session")

    assert message.answer_calls == [{"text": "Нет доступа."}]
    assert FakeAdminActionLookupService.instances == []


@pytest.mark.asyncio
async def test_admin_actions_command_formats_empty_state():
    message = admin_message("/admin_actions")

    await admin_actions_command(message, session="session")

    service = FakeAdminActionLookupService.instances[0]
    assert service.session == "session"
    assert service.last_calls == [{"limit": 20}]
    assert message.answer_calls == [
        {
            "text": "<b>Admin actions — последние 20</b>\n\nЗаписей нет.",
            "parse_mode": "HTML",
        }
    ]


@pytest.mark.asyncio
async def test_admin_actions_command_formats_action_items():
    FakeAdminActionLookupService.last_actions = [make_action()]
    message = admin_message("/admin_actions")

    await admin_actions_command(message, session="session")

    call = message.answer_calls[0]
    assert call["parse_mode"] == "HTML"
    text = call["text"]
    assert "<b>Admin actions — последние 20</b>" in text
    assert "Найдено: 1" in text
    assert "<b>AdminAction #91</b>" in text
    assert "Action: subscription_extended" in text
    assert "Admin username: @admin" in text
    assert "Target user ID: 7" in text
    assert "Order ID: 23" in text
    assert "Subscription ID: 51" in text
    assert "Reason: manual fix" in text
    assert 'Payload: <code>{"days": 30}</code>' in text


@pytest.mark.asyncio
async def test_admin_actions_subscription_command_sends_usage_for_invalid_args():
    message = admin_message("/admin_actions_subscription broken")

    await admin_actions_subscription_command(message, session="session")

    assert message.answer_calls == [
        {
            "text": "Использование:\n<code>/admin_actions_subscription 14</code>",
            "parse_mode": "HTML",
        }
    ]
    assert FakeAdminActionLookupService.instances == []


@pytest.mark.asyncio
async def test_admin_actions_subscription_command_uses_subscription_lookup():
    FakeAdminActionLookupService.subscription_actions = [make_action()]
    message = admin_message("/admin_actions_subscription 51")

    await admin_actions_subscription_command(message, session="session")

    service = FakeAdminActionLookupService.instances[0]
    assert service.subscription_calls == [{"subscription_id": 51, "limit": 20}]
    assert "Admin actions по Subscription #51" in message.answer_calls[0]["text"]
    assert "AdminAction #91" in message.answer_calls[0]["text"]


@pytest.mark.asyncio
async def test_admin_actions_user_command_sends_usage_for_invalid_args():
    message = admin_message("/admin_actions_user broken")

    await admin_actions_user_command(message, session="session")

    assert message.answer_calls == [
        {
            "text": "Использование:\n<code>/admin_actions_user 1</code>",
            "parse_mode": "HTML",
        }
    ]
    assert FakeAdminActionLookupService.instances == []


@pytest.mark.asyncio
async def test_admin_actions_user_command_uses_target_user_lookup():
    FakeAdminActionLookupService.user_actions = [make_action()]
    message = admin_message("/admin_actions_user 7")

    await admin_actions_user_command(message, session="session")

    service = FakeAdminActionLookupService.instances[0]
    assert service.user_calls == [{"target_user_id": 7, "limit": 20}]
    assert "Admin actions по User #7" in message.answer_calls[0]["text"]
    assert "AdminAction #91" in message.answer_calls[0]["text"]