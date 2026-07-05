from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest

import app.bot.handlers.admin as admin_module
from app.bot.handlers.admin import (
    _admin_menu_text,
    _format_admin_actions_text,
    _format_decimal,
    _format_stats_text,
    _split_messages,
    admin_command,
    admin_menu_actions_callback,
    admin_menu_home_callback,
    admin_menu_order_lookup_help_callback,
    admin_menu_payment_lookup_help_callback,
    admin_menu_stats_callback,
    admin_menu_subscription_lookup_help_callback,
    admin_menu_user_lookup_help_callback,
    admin_stats_command,
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


class FakeAdminStatsService:
    instances: list["FakeAdminStatsService"] = []
    result = None

    def __init__(self, session) -> None:
        self.session = session
        self.get_stats_count = 0
        self.__class__.instances.append(self)

    async def get_stats(self):
        self.get_stats_count += 1
        return self.__class__.result


class FakeAdminActionLookupService:
    instances: list["FakeAdminActionLookupService"] = []
    items = []

    def __init__(self, session) -> None:
        self.session = session
        self.calls: list[dict] = []
        self.__class__.instances.append(self)

    async def get_last_actions(self, **kwargs):
        self.calls.append(kwargs)
        return self.__class__.items


@pytest.fixture(autouse=True)
def patch_dependencies(monkeypatch):
    FakeAdminStatsService.instances = []
    FakeAdminStatsService.result = SimpleNamespace(
        users_total=10,
        orders_total=20,
        orders_waiting_payment=3,
        orders_paid=4,
        orders_activated=5,
        orders_expired=6,
        orders_failed=1,
        orders_cancelled=2,
        payments_total=30,
        payments_confirmed=12,
        payments_invalid=2,
        payments_duplicate=1,
        payments_error=0,
        subscriptions_total=8,
        subscriptions_active=6,
        subscriptions_expired=1,
        subscriptions_disabled=1,
        confirmed_revenue_total=Decimal("44.50000000"),
    )
    FakeAdminActionLookupService.instances = []
    FakeAdminActionLookupService.items = []

    monkeypatch.setattr(admin_module, "AdminStatsService", FakeAdminStatsService)
    monkeypatch.setattr(
        admin_module,
        "AdminActionLookupService",
        FakeAdminActionLookupService,
    )
    monkeypatch.setattr(
        admin_module,
        "get_settings",
        lambda: SimpleNamespace(admin_ids=[777]),
    )


def admin_user():
    return SimpleNamespace(id=777)


def non_admin_user():
    return SimpleNamespace(id=123)


def row_callbacks(markup):
    return [[button.callback_data for button in row] for row in markup.inline_keyboard]


def test_admin_helpers_format_decimal_split_and_menu_text_are_stable():
    assert _format_decimal(None) == "—"
    assert _format_decimal(Decimal("4.00000000")) == "4"
    assert _format_decimal(Decimal("4.123456789")) == "4.12345679"
    assert _split_messages(["aaa", "bbb", "ccc"], limit=6) == ["aaabbb", "ccc"]
    assert "<b>Админ-панель</b>" in _admin_menu_text()
    assert "Статистика — общие цифры проекта." in _admin_menu_text()


def test_format_stats_text_contains_all_dashboard_sections():
    text = _format_stats_text(FakeAdminStatsService.result)

    assert "<b>Статистика проекта</b>" in text
    assert "Всего: 10" in text
    assert "Ожидают оплату: 3" in text
    assert "Активированы: 5" in text
    assert "Подтверждены: 12" in text
    assert "Активные: 6" in text
    assert "Confirmed payments: 44.5" in text


def test_format_admin_actions_text_returns_empty_state_with_lookup_commands():
    text = _format_admin_actions_text([])

    assert "<b>Журнал действий</b>" in text
    assert "Записей пока нет." in text
    assert "<code>/admin_actions</code>" in text
    assert "<code>/admin_actions_subscription 15</code>" in text


@pytest.mark.asyncio
async def test_admin_command_returns_when_message_has_no_from_user():
    message = FakeMessage(from_user=None)

    await admin_command(message)

    assert message.answer_calls == []


@pytest.mark.asyncio
async def test_admin_command_rejects_non_admin_before_menu():
    message = FakeMessage(from_user=non_admin_user())

    await admin_command(message)

    assert message.answer_calls == [{"text": "Нет доступа."}]


@pytest.mark.asyncio
async def test_admin_command_sends_main_admin_menu():
    message = FakeMessage(from_user=admin_user())

    await admin_command(message)

    assert message.answer_calls[0]["text"] == _admin_menu_text()
    assert message.answer_calls[0]["parse_mode"] == "HTML"
    assert row_callbacks(message.answer_calls[0]["reply_markup"])[0] == [
        "admin_menu:stats"
    ]


@pytest.mark.asyncio
async def test_admin_stats_command_rejects_non_admin_before_service():
    message = FakeMessage(from_user=non_admin_user())

    await admin_stats_command(message, session="session")

    assert message.answer_calls == [{"text": "Нет доступа."}]
    assert FakeAdminStatsService.instances == []


@pytest.mark.asyncio
async def test_admin_stats_command_sends_stats_with_back_keyboard():
    message = FakeMessage(from_user=admin_user())

    await admin_stats_command(message, session="session")

    service = FakeAdminStatsService.instances[0]
    assert service.session == "session"
    assert service.get_stats_count == 1
    assert "<b>Статистика проекта</b>" in message.answer_calls[0]["text"]
    assert message.answer_calls[0]["parse_mode"] == "HTML"
    assert row_callbacks(message.answer_calls[0]["reply_markup"]) == [["admin_menu:home"]]


@pytest.mark.asyncio
async def test_admin_menu_home_callback_rejects_non_admin_with_alert():
    callback = FakeCallback(from_user=non_admin_user())

    await admin_menu_home_callback(callback)

    assert callback.message.edit_text_calls == []
    assert callback.answer_calls == [{"text": "Нет доступа.", "show_alert": True}]


@pytest.mark.asyncio
async def test_admin_menu_home_callback_edits_main_menu_and_answers():
    callback = FakeCallback(from_user=admin_user())

    await admin_menu_home_callback(callback)

    assert callback.message.edit_text_calls[0]["text"] == _admin_menu_text()
    assert callback.message.edit_text_calls[0]["parse_mode"] == "HTML"
    assert row_callbacks(callback.message.edit_text_calls[0]["reply_markup"])[0] == [
        "admin_menu:stats"
    ]
    assert callback.answer_calls == [{"text": None}]


@pytest.mark.asyncio
async def test_admin_menu_stats_callback_uses_stats_service_and_edits_message():
    callback = FakeCallback(from_user=admin_user())

    await admin_menu_stats_callback(callback, session="session")

    assert FakeAdminStatsService.instances[0].session == "session"
    assert "<b>Статистика проекта</b>" in callback.message.edit_text_calls[0]["text"]
    assert callback.message.edit_text_calls[0]["parse_mode"] == "HTML"
    assert callback.answer_calls == [{"text": None}]


@pytest.mark.asyncio
async def test_admin_menu_actions_callback_empty_state_uses_action_lookup_service():
    callback = FakeCallback(from_user=admin_user())

    await admin_menu_actions_callback(callback, session="session")

    service = FakeAdminActionLookupService.instances[0]
    assert service.session == "session"
    assert service.calls == [{"limit": 20}]
    assert "Записей пока нет." in callback.message.edit_text_calls[0]["text"]
    assert callback.message.edit_text_calls[0]["parse_mode"] == "HTML"
    assert callback.answer_calls == [{"text": None}]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("handler", "title", "command"),
    [
        (admin_menu_order_lookup_help_callback, "<b>Поиск заказа</b>", "/admin_order 68"),
        (admin_menu_payment_lookup_help_callback, "<b>Поиск платежа</b>", "/admin_payment 96"),
        (
            admin_menu_subscription_lookup_help_callback,
            "<b>Поиск подписки</b>",
            "/admin_subscription 14",
        ),
        (admin_menu_user_lookup_help_callback, "<b>Поиск пользователя</b>", "/admin_user 46"),
    ],
)
async def test_admin_menu_lookup_help_callbacks_edit_expected_help_text(
    handler,
    title,
    command,
):
    callback = FakeCallback(from_user=admin_user())

    await handler(callback)

    assert title in callback.message.edit_text_calls[0]["text"]
    assert command in callback.message.edit_text_calls[0]["text"]
    assert callback.message.edit_text_calls[0]["parse_mode"] == "HTML"
    assert row_callbacks(callback.message.edit_text_calls[0]["reply_markup"]) == [
        ["admin_menu:home"]
    ]
    assert callback.answer_calls == [{"text": None}]