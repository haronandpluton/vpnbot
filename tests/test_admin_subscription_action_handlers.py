from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

import app.bot.handlers.admin_subscription_actions as actions_module
from app.bot.handlers.admin_subscription_actions import (
    _clean,
    _format_datetime,
    _parse_disable_args,
    _parse_extend_args,
    admin_disable_subscription_command,
    admin_extend_subscription_command,
)


class FakeMessage:
    def __init__(self, *, text: str | None, from_user=None) -> None:
        self.text = text
        self.from_user = from_user
        self.answer_calls: list[dict] = []

    async def answer(self, text: str, **kwargs) -> None:
        self.answer_calls.append({"text": text, **kwargs})


class FakeAdminSubscriptionActionsService:
    instances: list["FakeAdminSubscriptionActionsService"] = []
    extend_result = None
    disable_result = None

    def __init__(self, session) -> None:
        self.session = session
        self.extend_calls: list[dict] = []
        self.disable_calls: list[dict] = []
        self.__class__.instances.append(self)

    async def extend_subscription(self, **kwargs):
        self.extend_calls.append(kwargs)
        return self.__class__.extend_result

    async def disable_subscription(self, **kwargs):
        self.disable_calls.append(kwargs)
        return self.__class__.disable_result


@pytest.fixture(autouse=True)
def patch_service_and_admin(monkeypatch):
    FakeAdminSubscriptionActionsService.instances = []
    FakeAdminSubscriptionActionsService.extend_result = None
    FakeAdminSubscriptionActionsService.disable_result = None
    monkeypatch.setattr(
        actions_module,
        "AdminSubscriptionActionsService",
        FakeAdminSubscriptionActionsService,
    )
    monkeypatch.setattr(
        actions_module,
        "get_settings",
        lambda: SimpleNamespace(admin_ids=[777]),
    )


def make_admin_message(text: str | None):
    return FakeMessage(text=text, from_user=SimpleNamespace(id=777))


def test_helpers_clean_and_format_datetime_are_stable():
    value = datetime(2026, 7, 5, 12, 34, 56, tzinfo=timezone.utc)

    assert _clean(None) == "—"
    assert _clean("") == "—"
    assert _clean(23) == "23"
    assert _format_datetime(None) == "—"
    assert _format_datetime(value) == "05.07.2026 12:34:56"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("/admin_extend_subscription 14 30", (14, 30)),
        ("  /admin_extend_subscription   14   30  ", (14, 30)),
        (None, None),
        ("/admin_extend_subscription", None),
        ("/admin_extend_subscription abc 30", None),
        ("/admin_extend_subscription 14 abc", None),
        ("/admin_extend_subscription 14 30 extra", None),
    ],
)
def test_parse_extend_args_accepts_only_subscription_id_and_days(text, expected):
    assert _parse_extend_args(FakeMessage(text=text)) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("/admin_disable_subscription 14 abuse", (14, "abuse")),
        ("/admin_disable_subscription 14 manual refund", (14, "manual refund")),
        (None, None),
        ("/admin_disable_subscription", None),
        ("/admin_disable_subscription abc abuse", None),
        ("/admin_disable_subscription 14", None),
    ],
)
def test_parse_disable_args_accepts_id_and_reason_with_spaces(text, expected):
    assert _parse_disable_args(FakeMessage(text=text)) == expected


@pytest.mark.asyncio
async def test_extend_command_returns_when_message_has_no_from_user():
    message = FakeMessage(text="/admin_extend_subscription 14 30", from_user=None)

    await admin_extend_subscription_command(message, session="session")

    assert message.answer_calls == []
    assert FakeAdminSubscriptionActionsService.instances == []


@pytest.mark.asyncio
async def test_extend_command_rejects_non_admin_before_parsing_or_service():
    message = FakeMessage(
        text="/admin_extend_subscription 14 30",
        from_user=SimpleNamespace(id=123),
    )

    await admin_extend_subscription_command(message, session="session")

    assert message.answer_calls == [{"text": "Нет доступа."}]
    assert FakeAdminSubscriptionActionsService.instances == []


@pytest.mark.asyncio
async def test_extend_command_sends_usage_for_invalid_args():
    message = make_admin_message("/admin_extend_subscription broken")

    await admin_extend_subscription_command(message, session="session")

    assert "Использование:" in message.answer_calls[0]["text"]
    assert "<code>/admin_extend_subscription 14 30</code>" in message.answer_calls[0][
        "text"
    ]
    assert message.answer_calls[0]["parse_mode"] == "HTML"
    assert FakeAdminSubscriptionActionsService.instances == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "expected_text"),
    [
        (
            "invalid_days",
            "Некорректное количество дней.\nКоличество дней должно быть больше нуля.",
        ),
        ("subscription_not_found", "Subscription #14 не найдена."),
        (
            "admin_user_not_found",
            "Не удалось записать admin action.\nАдмин не найден в таблице users.",
        ),
        ("db_failed", "Не удалось продлить подписку.\n\nStatus: db_failed"),
    ],
)
async def test_extend_command_maps_non_success_service_statuses(status, expected_text):
    FakeAdminSubscriptionActionsService.extend_result = SimpleNamespace(
        status=status,
        subscription_id=14,
        days=30,
    )
    message = make_admin_message("/admin_extend_subscription 14 30")

    await admin_extend_subscription_command(message, session="session")

    service = FakeAdminSubscriptionActionsService.instances[0]
    assert service.session == "session"
    assert service.extend_calls == [
        {"subscription_id": 14, "days": 30, "admin_telegram_id": 777}
    ]
    assert message.answer_calls == [{"text": expected_text}]


@pytest.mark.asyncio
async def test_extend_command_success_sends_full_admin_summary():
    old_expires_at = datetime(2026, 7, 1, 12, 0, 0, tzinfo=timezone.utc)
    new_expires_at = datetime(2026, 7, 31, 12, 0, 0, tzinfo=timezone.utc)
    FakeAdminSubscriptionActionsService.extend_result = SimpleNamespace(
        status="extended",
        subscription_id=14,
        user_id=7,
        order_id=23,
        days=30,
        old_expires_at=old_expires_at,
        new_expires_at=new_expires_at,
        uuid="uuid-1",
        admin_action_id=99,
    )
    message = make_admin_message("/admin_extend_subscription 14 30")

    await admin_extend_subscription_command(message, session="session")

    text = message.answer_calls[0]["text"]
    assert "<b>Подписка продлена</b>" in text
    assert "Subscription ID: 14" in text
    assert "User ID: 7" in text
    assert "Order ID: 23" in text
    assert "Days added: 30" in text
    assert "Old expires at: 01.07.2026 12:00:00" in text
    assert "New expires at: 31.07.2026 12:00:00" in text
    assert "UUID: <code>uuid-1</code>" in text
    assert "Admin action ID: 99" in text
    assert "<code>/admin_subscription 14</code>" in text
    assert message.answer_calls[0]["parse_mode"] == "HTML"


@pytest.mark.asyncio
async def test_disable_command_returns_when_message_has_no_from_user():
    message = FakeMessage(text="/admin_disable_subscription 14 abuse", from_user=None)

    await admin_disable_subscription_command(message, session="session")

    assert message.answer_calls == []
    assert FakeAdminSubscriptionActionsService.instances == []


@pytest.mark.asyncio
async def test_disable_command_rejects_non_admin_before_service():
    message = FakeMessage(
        text="/admin_disable_subscription 14 abuse",
        from_user=SimpleNamespace(id=123),
    )

    await admin_disable_subscription_command(message, session="session")

    assert message.answer_calls == [{"text": "Нет доступа."}]
    assert FakeAdminSubscriptionActionsService.instances == []


@pytest.mark.asyncio
async def test_disable_command_sends_usage_for_invalid_args():
    message = make_admin_message("/admin_disable_subscription broken")

    await admin_disable_subscription_command(message, session="session")

    assert "Использование:" in message.answer_calls[0]["text"]
    assert "<code>/admin_disable_subscription 14 abuse</code>" in message.answer_calls[0][
        "text"
    ]
    assert message.answer_calls[0]["parse_mode"] == "HTML"
    assert FakeAdminSubscriptionActionsService.instances == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "expected_text"),
    [
        ("invalid_reason", "Причина отключения обязательна."),
        ("subscription_not_found", "Subscription #14 не найдена."),
        (
            "admin_user_not_found",
            "Не удалось записать admin action.\nАдмин не найден в таблице users.",
        ),
        ("db_failed", "Не удалось отключить подписку.\n\nStatus: db_failed"),
    ],
)
async def test_disable_command_maps_non_success_service_statuses(status, expected_text):
    FakeAdminSubscriptionActionsService.disable_result = SimpleNamespace(
        status=status,
        subscription_id=14,
    )
    message = make_admin_message("/admin_disable_subscription 14 abuse")

    await admin_disable_subscription_command(message, session="session")

    service = FakeAdminSubscriptionActionsService.instances[0]
    assert service.session == "session"
    assert service.disable_calls == [
        {"subscription_id": 14, "reason": "abuse", "admin_telegram_id": 777}
    ]
    assert message.answer_calls == [{"text": expected_text}]


@pytest.mark.asyncio
async def test_disable_command_success_sends_full_admin_summary():
    disabled_at = datetime(2026, 7, 5, 12, 0, 0, tzinfo=timezone.utc)
    FakeAdminSubscriptionActionsService.disable_result = SimpleNamespace(
        status="disabled",
        subscription_id=14,
        user_id=7,
        order_id=23,
        old_status="active",
        new_status="disabled",
        disabled_at=disabled_at,
        reason="abuse",
        uuid="uuid-1",
        admin_action_id=99,
    )
    message = make_admin_message("/admin_disable_subscription 14 abuse")

    await admin_disable_subscription_command(message, session="session")

    text = message.answer_calls[0]["text"]
    assert "<b>Подписка отключена</b>" in text
    assert "Subscription ID: 14" in text
    assert "User ID: 7" in text
    assert "Order ID: 23" in text
    assert "Old status: active" in text
    assert "New status: disabled" in text
    assert "Disabled at: 05.07.2026 12:00:00" in text
    assert "Reason: abuse" in text
    assert "UUID: <code>uuid-1</code>" in text
    assert "Admin action ID: 99" in text
    assert "<code>/admin_actions_subscription 14</code>" in text
    assert message.answer_calls[0]["parse_mode"] == "HTML"