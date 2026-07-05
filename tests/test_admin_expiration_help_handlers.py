from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

import app.bot.handlers.admin_commands_help as help_module
import app.bot.handlers.admin_order_expiration as order_module
import app.bot.handlers.admin_subscription_expiration as subscription_module
from app.bot.handlers.admin_commands_help import (
    _commands_help_text,
    admin_commands_command,
    admin_menu_commands_help_callback,
)
from app.bot.handlers.admin_order_expiration import admin_expire_orders_command
from app.bot.handlers.admin_subscription_expiration import (
    admin_expire_subscriptions_command,
)


class FakeMessage:
    def __init__(self, *, from_user=None) -> None:
        self.from_user = from_user
        self.answer_calls: list[dict] = []
        self.edit_text_calls: list[dict] = []

    async def answer(self, text: str, **kwargs) -> None:
        self.answer_calls.append({"text": text, **kwargs})

    async def edit_text(self, text: str, **kwargs) -> None:
        self.edit_text_calls.append({"text": text, **kwargs})


class FakeCallback:
    def __init__(self, *, from_user=None) -> None:
        self.from_user = from_user
        self.message = FakeMessage()
        self.answer_calls: list[dict] = []

    async def answer(self, text: str | None = None, **kwargs) -> None:
        self.answer_calls.append({"text": text, **kwargs})


class FakeOrderExpirationService:
    instances: list["FakeOrderExpirationService"] = []
    result = None

    def __init__(self, session) -> None:
        self.session = session
        self.calls = 0
        self.__class__.instances.append(self)

    async def expire_due_orders(self):
        self.calls += 1
        return self.__class__.result


class FakeSubscriptionExpirationService:
    instances: list["FakeSubscriptionExpirationService"] = []
    result = None

    def __init__(self, session) -> None:
        self.session = session
        self.calls: list[dict] = []
        self.__class__.instances.append(self)

    async def expire_due_subscriptions(self, **kwargs):
        self.calls.append(kwargs)
        return self.__class__.result


@pytest.fixture(autouse=True)
def patch_dependencies(monkeypatch):
    FakeOrderExpirationService.instances = []
    FakeOrderExpirationService.result = SimpleNamespace(
        status="no_expired_orders",
        checked_at=datetime(2026, 7, 5, 12, 0, tzinfo=timezone.utc),
    )
    FakeSubscriptionExpirationService.instances = []
    FakeSubscriptionExpirationService.result = SimpleNamespace(
        status="no_expired_subscriptions",
        checked_at=datetime(2026, 7, 5, 12, 0, tzinfo=timezone.utc),
    )

    monkeypatch.setattr(
        order_module,
        "OrderExpirationService",
        FakeOrderExpirationService,
    )
    monkeypatch.setattr(
        subscription_module,
        "SubscriptionExpirationService",
        FakeSubscriptionExpirationService,
    )
    monkeypatch.setattr(
        order_module,
        "get_settings",
        lambda: SimpleNamespace(admin_ids=[777]),
    )
    monkeypatch.setattr(
        subscription_module,
        "get_settings",
        lambda: SimpleNamespace(admin_ids=[777]),
    )
    monkeypatch.setattr(
        help_module,
        "get_settings",
        lambda: SimpleNamespace(admin_ids=[777]),
    )


def admin_message():
    return FakeMessage(from_user=SimpleNamespace(id=777))


def non_admin_message():
    return FakeMessage(from_user=SimpleNamespace(id=123))


def admin_callback():
    return FakeCallback(from_user=SimpleNamespace(id=777))


def non_admin_callback():
    return FakeCallback(from_user=SimpleNamespace(id=123))


def make_order_item(index: int = 1):
    return SimpleNamespace(
        order_id=index,
        user_id=index + 100,
        old_status="waiting_payment",
        new_status="expired",
        expires_at=datetime(2026, 7, 5, 12, 0, tzinfo=timezone.utc),
        tariff_code="devices_1",
        payment_method="crypto",
    )


def make_subscription_item(index: int = 1):
    return SimpleNamespace(
        subscription_id=index,
        user_id=index + 100,
        old_status="active",
        new_status="expired",
        expires_at=datetime(2026, 7, 5, 12, 0, tzinfo=timezone.utc),
        uuid=f"uuid-{index}",
    )


def test_commands_help_text_contains_core_production_and_dev_sections():
    text = _commands_help_text()

    assert "<b>Список доступных команд</b>" in text
    assert "<code>/admin_resend_config 72</code>" in text
    assert "<code>/admin_extend_subscription 15 30</code>" in text
    assert "<code>/admin_disable_subscription 17 test_cleanup</code>" in text
    assert "<code>/dev_create_active_subscription</code>" in text
    assert "<code>DEV_MODE=false</code>" in text


@pytest.mark.asyncio
async def test_admin_commands_command_returns_when_message_has_no_from_user():
    message = FakeMessage(from_user=None)

    await admin_commands_command(message)

    assert message.answer_calls == []


@pytest.mark.asyncio
async def test_admin_commands_command_rejects_non_admin():
    message = non_admin_message()

    await admin_commands_command(message)

    assert message.answer_calls == [{"text": "Нет доступа."}]


@pytest.mark.asyncio
async def test_admin_commands_command_sends_help_text_and_back_keyboard():
    message = admin_message()

    await admin_commands_command(message)

    assert message.answer_calls[0]["text"] == _commands_help_text()
    assert message.answer_calls[0]["parse_mode"] == "HTML"
    assert (
        message.answer_calls[0]["reply_markup"]
        .inline_keyboard[0][0]
        .callback_data
        == "admin_menu:home"
    )


@pytest.mark.asyncio
async def test_admin_menu_commands_help_callback_returns_when_no_from_user():
    callback = FakeCallback(from_user=None)

    await admin_menu_commands_help_callback(callback)

    assert callback.message.edit_text_calls == []
    assert callback.answer_calls == []


@pytest.mark.asyncio
async def test_admin_menu_commands_help_callback_rejects_non_admin_with_alert():
    callback = non_admin_callback()

    await admin_menu_commands_help_callback(callback)

    assert callback.message.edit_text_calls == []
    assert callback.answer_calls == [{"text": "Нет доступа.", "show_alert": True}]


@pytest.mark.asyncio
async def test_admin_menu_commands_help_callback_edits_help_text_and_answers():
    callback = admin_callback()

    await admin_menu_commands_help_callback(callback)

    assert callback.message.edit_text_calls[0]["text"] == _commands_help_text()
    assert callback.message.edit_text_calls[0]["parse_mode"] == "HTML"
    assert (
        callback.message.edit_text_calls[0]["reply_markup"]
        .inline_keyboard[0][0]
        .callback_data
        == "admin_menu:home"
    )
    assert callback.answer_calls == [{"text": None}]


@pytest.mark.asyncio
async def test_admin_expire_orders_returns_when_message_has_no_from_user():
    message = FakeMessage(from_user=None)

    await admin_expire_orders_command(message, session="session")

    assert message.answer_calls == []
    assert FakeOrderExpirationService.instances == []


@pytest.mark.asyncio
async def test_admin_expire_orders_rejects_non_admin_before_service():
    message = non_admin_message()

    await admin_expire_orders_command(message, session="session")

    assert message.answer_calls == [{"text": "Нет доступа."}]
    assert FakeOrderExpirationService.instances == []


@pytest.mark.asyncio
async def test_admin_expire_orders_sends_no_expired_orders_message():
    message = admin_message()

    await admin_expire_orders_command(message, session="session")

    service = FakeOrderExpirationService.instances[0]
    assert service.session == "session"
    assert service.calls == 1
    assert message.answer_calls == [
        {
            "text": (
                "<b>Просроченных неоплаченных заказов нет</b>\n\n"
                "Checked at: 05.07.2026 12:00:00"
            ),
            "parse_mode": "HTML",
        }
    ]


@pytest.mark.asyncio
async def test_admin_expire_orders_sends_error_status_message():
    FakeOrderExpirationService.result = SimpleNamespace(
        status="db_failed",
        message="db down",
    )
    message = admin_message()

    await admin_expire_orders_command(message, session="session")

    assert message.answer_calls == [
        {
            "text": (
                "<b>Не удалось обработать истечение заказов</b>\n\n"
                "Status: db_failed\n"
                "Message: db down"
            ),
            "parse_mode": "HTML",
        }
    ]


@pytest.mark.asyncio
async def test_admin_expire_orders_formats_expired_items_and_truncates_after_twenty():
    FakeOrderExpirationService.result = SimpleNamespace(
        status="expired",
        checked_at=datetime(2026, 7, 5, 12, 0, tzinfo=timezone.utc),
        expired_count=21,
        expired_items=[make_order_item(index) for index in range(1, 22)],
    )
    message = admin_message()

    await admin_expire_orders_command(message, session="session")

    text = message.answer_calls[0]["text"]
    assert message.answer_calls[0]["parse_mode"] == "HTML"
    assert "<b>Истечение неоплаченных заказов обработано</b>" in text
    assert "Expired count: 21" in text
    assert "#1 | user_id=101 | waiting_payment → expired" in text
    assert "#20 | user_id=120 | waiting_payment → expired" in text
    assert "#21 |" not in text
    assert "...и ещё 1" in text


@pytest.mark.asyncio
async def test_admin_expire_subscriptions_returns_when_message_has_no_from_user():
    message = FakeMessage(from_user=None)

    await admin_expire_subscriptions_command(message, session="session")

    assert message.answer_calls == []
    assert FakeSubscriptionExpirationService.instances == []


@pytest.mark.asyncio
async def test_admin_expire_subscriptions_rejects_non_admin_before_service():
    message = non_admin_message()

    await admin_expire_subscriptions_command(message, session="session")

    assert message.answer_calls == [{"text": "Нет доступа."}]
    assert FakeSubscriptionExpirationService.instances == []


@pytest.mark.asyncio
async def test_admin_expire_subscriptions_sends_no_expired_subscriptions_message():
    message = admin_message()

    await admin_expire_subscriptions_command(message, session="session")

    service = FakeSubscriptionExpirationService.instances[0]
    assert service.session == "session"
    assert service.calls == [{"sync_metadata": True}]
    assert message.answer_calls == [
        {
            "text": (
                "<b>Просроченных active-подписок нет</b>\n\n"
                "Checked at: 05.07.2026 12:00:00"
            ),
            "parse_mode": "HTML",
        }
    ]


@pytest.mark.asyncio
async def test_admin_expire_subscriptions_sends_error_status_message():
    FakeSubscriptionExpirationService.result = SimpleNamespace(
        status="db_failed",
        message=None,
    )
    message = admin_message()

    await admin_expire_subscriptions_command(message, session="session")

    assert message.answer_calls == [
        {
            "text": (
                "<b>Не удалось обработать истечение подписок</b>\n\n"
                "Status: db_failed\n"
                "Message: —"
            ),
            "parse_mode": "HTML",
        }
    ]


@pytest.mark.asyncio
async def test_admin_expire_subscriptions_formats_expired_items_sync_error_and_truncates():
    FakeSubscriptionExpirationService.result = SimpleNamespace(
        status="expired",
        checked_at=datetime(2026, 7, 5, 12, 0, tzinfo=timezone.utc),
        expired_count=21,
        sync_status="sync_failed",
        sync_error="scp failed",
        expired_items=[make_subscription_item(index) for index in range(1, 22)],
    )
    message = admin_message()

    await admin_expire_subscriptions_command(message, session="session")

    text = message.answer_calls[0]["text"]
    assert message.answer_calls[0]["parse_mode"] == "HTML"
    assert "<b>Истечение подписок обработано</b>" in text
    assert "Expired count: 21" in text
    assert "Sync status: sync_failed" in text
    assert "Sync error: <code>scp failed</code>" in text
    assert "#1 | user_id=101 | active → expired" in text
    assert "uuid=<code>uuid-1</code>" in text
    assert "#20 | user_id=120 | active → expired" in text
    assert "#21 |" not in text
    assert "...и ещё 1" in text