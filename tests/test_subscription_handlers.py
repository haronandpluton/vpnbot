from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

import app.bot.handlers.my_subscription as my_subscription_module
import app.bot.handlers.vpn_access as vpn_access_module
from app.bot.handlers.my_subscription import my_subscription_command
from app.bot.handlers.vpn_access import (
    happ_android_callback,
    happ_fallback_callback,
    happ_ios_callback,
    show_vpn_config_callback,
)


class FakeMessage:
    def __init__(self, *, from_user=None) -> None:
        self.from_user = from_user or SimpleNamespace(id=123)
        self.answer_calls: list[dict] = []

    async def answer(self, text: str, **kwargs) -> None:
        self.answer_calls.append({"text": text, **kwargs})


class FakeCallback:
    def __init__(
        self,
        *,
        from_user=None,
        data: str = "vpn_access:show_config:50",
    ) -> None:
        self.from_user = from_user
        self.data = data
        self.message = FakeMessage()
        self.answer_calls: list[dict] = []

    async def answer(self, text: str | None = None, **kwargs) -> None:
        self.answer_calls.append({"text": text, **kwargs})


class FakeMySubscriptionService:
    subscriptions_result = None
    access_result = None
    instances: list["FakeMySubscriptionService"] = []

    def __init__(self, session) -> None:
        self.session = session
        self.subscriptions_calls: list[int] = []
        self.access_calls: list[dict] = []
        self.__class__.instances.append(self)

    async def get_active_subscriptions_by_telegram_id(self, *, telegram_id: int):
        self.subscriptions_calls.append(telegram_id)
        return self.__class__.subscriptions_result

    async def get_access_by_subscription_id(
        self,
        *,
        telegram_id: int,
        subscription_id: int,
    ):
        self.access_calls.append(
            {
                "telegram_id": telegram_id,
                "subscription_id": subscription_id,
            }
        )
        return self.__class__.access_result


@pytest.fixture(autouse=True)
def patch_service(monkeypatch):
    FakeMySubscriptionService.instances = []
    FakeMySubscriptionService.subscriptions_result = None
    FakeMySubscriptionService.access_result = None
    monkeypatch.setattr(
        my_subscription_module,
        "MySubscriptionService",
        FakeMySubscriptionService,
    )
    monkeypatch.setattr(
        vpn_access_module,
        "MySubscriptionService",
        FakeMySubscriptionService,
    )


def row_callbacks(markup):
    return [[button.callback_data for button in row] for row in markup.inline_keyboard]


def row_urls(markup):
    return [[button.url for button in row] for row in markup.inline_keyboard]


@pytest.mark.asyncio
async def test_my_subscription_sends_separate_card_for_each_active_subscription():
    first_expires_at = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
    second_expires_at = datetime(2026, 9, 5, 18, 30, tzinfo=timezone.utc)
    FakeMySubscriptionService.subscriptions_result = SimpleNamespace(
        status="active",
        subscriptions=(
            SimpleNamespace(
                subscription_id=50,
                device_limit=1,
                expires_at=first_expires_at,
            ),
            SimpleNamespace(
                subscription_id=77,
                device_limit=1,
                expires_at=second_expires_at,
            ),
        ),
    )
    message = FakeMessage(from_user=SimpleNamespace(id=777))

    await my_subscription_command(message, session="session")

    service = FakeMySubscriptionService.instances[0]
    assert service.session == "session"
    assert service.subscriptions_calls == [777]
    assert len(message.answer_calls) == 2

    first_message = message.answer_calls[0]
    assert "Подписка №1" in first_message["text"]
    assert "ID подписки: 50" in first_message["text"]
    assert "Устройств: 1" in first_message["text"]
    assert "Активна до: 01.08.2026 12:00" in first_message["text"]
    assert row_callbacks(first_message["reply_markup"]) == [
        ["vpn_access:show_config:50"],
        ["vpn_access:show_config:50"],
        ["renew_subscription:50"],
        ["buy_vpn"],
        ["vpn_access:happ_android", "vpn_access:happ_ios"],
        ["vpn_access:happ_fallback"],
    ]

    second_message = message.answer_calls[1]
    assert "Подписка №2" in second_message["text"]
    assert "ID подписки: 77" in second_message["text"]
    assert "Активна до: 05.09.2026 18:30" in second_message["text"]
    assert row_callbacks(second_message["reply_markup"])[0] == [
        "vpn_access:show_config:77"
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "expected_text"),
    [
        (
            "user_not_found",
            "Я пока не нашел твой профиль.\n\n"
            "Сначала создай заказ или запусти бота через /start.",
        ),
        (
            "subscription_not_found",
            "Активные подписки не найдены.\n\n"
            "Если ты уже оплатил заказ, нажми «Проверить оплату» "
            "в сообщении с заказом.",
        ),
        (
            "subscription_expired",
            "Срок всех подписок истек.\n\n"
            "Открой подписку и нажми «Продлить подписку».",
        ),
        (
            "unknown",
            "Не удалось определить состояние подписок.\n\n"
            "Обратись в поддержку.",
        ),
    ],
)
async def test_my_subscription_non_active_statuses_send_clear_user_message(
    status,
    expected_text,
):
    FakeMySubscriptionService.subscriptions_result = SimpleNamespace(status=status)
    message = FakeMessage(from_user=SimpleNamespace(id=123))

    await my_subscription_command(message, session="session")

    assert message.answer_calls == [{"text": expected_text}]
    assert FakeMySubscriptionService.instances[0].subscriptions_calls == [123]


@pytest.mark.asyncio
async def test_show_vpn_config_callback_blocks_missing_user():
    callback = FakeCallback(from_user=None)

    await show_vpn_config_callback(callback, session="session")

    assert callback.answer_calls == [
        {"text": "Не удалось определить пользователя.", "show_alert": True}
    ]
    assert callback.message.answer_calls == []
    assert FakeMySubscriptionService.instances == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "data",
    [
        "vpn_access:show_config:not-a-number",
        "vpn_access:show_config:0",
        "vpn_access:show_config:-1",
    ],
)
async def test_show_vpn_config_callback_rejects_invalid_subscription_id(data):
    callback = FakeCallback(from_user=SimpleNamespace(id=123), data=data)

    await show_vpn_config_callback(callback, session="session")

    assert callback.answer_calls == [
        {"text": "Некорректная подписка.", "show_alert": True}
    ]
    assert callback.message.answer_calls == []
    assert FakeMySubscriptionService.instances == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "result",
    [
        SimpleNamespace(status="subscription_not_found", config_uri=None),
        SimpleNamespace(status="active", config_uri=None),
    ],
)
async def test_show_vpn_config_callback_blocks_missing_active_access(result):
    FakeMySubscriptionService.access_result = result
    callback = FakeCallback(
        from_user=SimpleNamespace(id=123),
        data="vpn_access:show_config:50",
    )

    await show_vpn_config_callback(callback, session="session")

    assert FakeMySubscriptionService.instances[0].access_calls == [
        {"telegram_id": 123, "subscription_id": 50}
    ]
    assert callback.answer_calls == [
        {"text": "Активная подписка не найдена.", "show_alert": True}
    ]
    assert callback.message.answer_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "expected_text"),
    [
        ("subscription_expired", "Срок выбранной подписки истек."),
        ("subscription_not_active", "Выбранная подписка не активна."),
    ],
)
async def test_show_vpn_config_callback_reports_unavailable_selected_subscription(
    status,
    expected_text,
):
    FakeMySubscriptionService.access_result = SimpleNamespace(
        status=status,
        config_uri=None,
    )
    callback = FakeCallback(
        from_user=SimpleNamespace(id=123),
        data="vpn_access:show_config:77",
    )

    await show_vpn_config_callback(callback, session="session")

    assert FakeMySubscriptionService.instances[0].access_calls == [
        {"telegram_id": 123, "subscription_id": 77}
    ]
    assert callback.answer_calls == [
        {"text": expected_text, "show_alert": True}
    ]
    assert callback.message.answer_calls == []


@pytest.mark.asyncio
async def test_show_vpn_config_callback_sends_selected_subscription_config():
    FakeMySubscriptionService.access_result = SimpleNamespace(
        status="active",
        config_uri="https://connect.example/sub-uuid-77",
    )
    callback = FakeCallback(
        from_user=SimpleNamespace(id=123),
        data="vpn_access:show_config:77",
    )

    await show_vpn_config_callback(callback, session="session")

    assert FakeMySubscriptionService.instances[0].access_calls == [
        {"telegram_id": 123, "subscription_id": 77}
    ]
    assert "Страница подключения VPN:" in callback.message.answer_calls[0]["text"]
    assert (
        "<code>https://connect.example/sub-uuid-77</code>"
        in callback.message.answer_calls[0]["text"]
    )
    assert callback.message.answer_calls[0]["parse_mode"] == "HTML"
    assert row_urls(callback.message.answer_calls[0]["reply_markup"]) == [
        ["https://connect.example/sub-uuid-77"]
    ]
    assert callback.answer_calls == [{"text": None}]


@pytest.mark.asyncio
async def test_happ_android_callback_sends_android_instruction_and_answers_callback():
    callback = FakeCallback(from_user=SimpleNamespace(id=123))

    await happ_android_callback(callback)

    assert (
        "Подключение через Happ VPN на Android:"
        in callback.message.answer_calls[0]["text"]
    )
    assert callback.answer_calls == [{"text": None}]


@pytest.mark.asyncio
async def test_happ_ios_callback_sends_ios_instruction_and_answers_callback():
    callback = FakeCallback(from_user=SimpleNamespace(id=123))

    await happ_ios_callback(callback)

    assert "Подключение на iPhone:" in callback.message.answer_calls[0]["text"]
    assert callback.answer_calls == [{"text": None}]


@pytest.mark.asyncio
async def test_happ_fallback_callback_sends_fallback_instruction_and_answers_callback():
    callback = FakeCallback(from_user=SimpleNamespace(id=123))

    await happ_fallback_callback(callback)

    assert (
        "Если Happ VPN не открылся автоматически:"
        in callback.message.answer_calls[0]["text"]
    )
    assert callback.answer_calls == [{"text": None}]
