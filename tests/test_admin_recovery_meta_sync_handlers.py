from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

import app.bot.handlers.admin_recovery as recovery_module
import app.bot.handlers.admin_subscription_meta_sync as meta_module
from app.bot.handlers.admin_recovery import (
    _format_datetime,
    _parse_id_from_command,
    admin_resend_config_command,
)
from app.bot.handlers.admin_subscription_meta_sync import admin_sync_subscriptions_command


class FakeEditableMessage:
    def __init__(self) -> None:
        self.edit_text_calls: list[dict] = []

    async def edit_text(self, text: str, **kwargs) -> None:
        self.edit_text_calls.append({"text": text, **kwargs})


class FakeMessage:
    def __init__(self, *, text: str | None = None, from_user=None) -> None:
        self.text = text
        self.from_user = from_user
        self.answer_calls: list[dict] = []
        self.returned_messages: list[FakeEditableMessage] = []

    async def answer(self, text: str, **kwargs):
        self.answer_calls.append({"text": text, **kwargs})
        editable = FakeEditableMessage()
        self.returned_messages.append(editable)
        return editable


class FakeBot:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.send_message_calls: list[dict] = []

    async def send_message(self, **kwargs) -> None:
        if self.error is not None:
            raise self.error

        self.send_message_calls.append(kwargs)


class FakeSession:
    def __init__(self) -> None:
        self.rollback_count = 0

    async def rollback(self) -> None:
        self.rollback_count += 1


class FakeAdminRecoveryService:
    instances: list["FakeAdminRecoveryService"] = []
    result = None

    def __init__(self, session) -> None:
        self.session = session
        self.order_ids: list[int] = []
        self.__class__.instances.append(self)

    async def prepare_resend_config(self, order_id: int):
        self.order_ids.append(order_id)
        return self.__class__.result


class FakeAdminActionLogService:
    instances: list["FakeAdminActionLogService"] = []
    result = SimpleNamespace(status="created", action_id=99)

    def __init__(self, session) -> None:
        self.session = session
        self.calls: list[dict] = []
        self.__class__.instances.append(self)

    async def create_action_by_admin_telegram_id(self, **kwargs):
        self.calls.append(kwargs)
        return self.__class__.result


class FakeSubscriptionMetaSyncService:
    instances: list["FakeSubscriptionMetaSyncService"] = []
    result = None
    error: Exception | None = None

    def __init__(self, session) -> None:
        self.session = session
        self.sync_count = 0
        self.__class__.instances.append(self)

    async def sync(self):
        self.sync_count += 1

        if self.__class__.error is not None:
            raise self.__class__.error

        return self.__class__.result


@pytest.fixture(autouse=True)
def patch_dependencies(monkeypatch):
    FakeAdminRecoveryService.instances = []
    FakeAdminRecoveryService.result = None

    FakeAdminActionLogService.instances = []
    FakeAdminActionLogService.result = SimpleNamespace(status="created", action_id=99)

    FakeSubscriptionMetaSyncService.instances = []
    FakeSubscriptionMetaSyncService.result = SimpleNamespace(
        exported_count=2,
        skipped_count=1,
        output_path="/tmp/subscriptions_meta.json",
        remote_target="user@host:/var/www/subscriptions_meta.json",
        stdout="uploaded",
        stderr="",
    )
    FakeSubscriptionMetaSyncService.error = None

    monkeypatch.setattr(
        recovery_module,
        "AdminRecoveryService",
        FakeAdminRecoveryService,
    )
    monkeypatch.setattr(
        recovery_module,
        "AdminActionLogService",
        FakeAdminActionLogService,
    )
    monkeypatch.setattr(
        recovery_module,
        "get_settings",
        lambda: SimpleNamespace(admin_ids=[777]),
    )
    monkeypatch.setattr(
        meta_module,
        "SubscriptionMetaSyncService",
        FakeSubscriptionMetaSyncService,
    )
    monkeypatch.setattr(
        meta_module,
        "AdminActionLogService",
        FakeAdminActionLogService,
    )
    monkeypatch.setattr(meta_module, "is_admin", lambda telegram_id: telegram_id == 777)


def admin_message(text: str | None = "/admin_resend_config 23"):
    return FakeMessage(text=text, from_user=SimpleNamespace(id=777))


def non_admin_message(text: str | None = "/admin_resend_config 23"):
    return FakeMessage(text=text, from_user=SimpleNamespace(id=123))


def ready_result(**overrides):
    values = {
        "status": "ready",
        "order_id": 23,
        "user_id": 7,
        "telegram_id": 777000,
        "username": "ivan",
        "subscription_id": 51,
        "expires_at": datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc),
        "config_uri": "https://connect.example/sub-uuid",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("/admin_resend_config 23", 23),
        ("  /admin_resend_config   23  ", 23),
        (None, None),
        ("/admin_resend_config", None),
        ("/admin_resend_config abc", None),
        ("/admin_resend_config 23 extra", None),
    ],
)
def test_recovery_parse_id_from_command_accepts_single_numeric_argument(text, expected):
    assert _parse_id_from_command(FakeMessage(text=text)) == expected


def test_recovery_format_datetime_handles_none_and_datetime():
    value = datetime(2026, 7, 5, 12, 34, tzinfo=timezone.utc)

    assert _format_datetime(None) == "—"
    assert _format_datetime(value) == "05.07.2026 12:34"


@pytest.mark.asyncio
async def test_resend_config_returns_when_message_has_no_from_user():
    message = FakeMessage(text="/admin_resend_config 23", from_user=None)
    bot = FakeBot()

    await admin_resend_config_command(message, session="session", bot=bot)

    assert message.answer_calls == []
    assert bot.send_message_calls == []
    assert FakeAdminRecoveryService.instances == []


@pytest.mark.asyncio
async def test_resend_config_rejects_non_admin_before_service():
    message = non_admin_message()
    bot = FakeBot()

    await admin_resend_config_command(message, session="session", bot=bot)

    assert message.answer_calls == [{"text": "Нет доступа."}]
    assert bot.send_message_calls == []
    assert FakeAdminRecoveryService.instances == []


@pytest.mark.asyncio
async def test_resend_config_sends_usage_for_invalid_args():
    message = admin_message("/admin_resend_config broken")
    bot = FakeBot()

    await admin_resend_config_command(message, session="session", bot=bot)

    assert message.answer_calls == [
        {
            "text": "Использование:\n<code>/admin_resend_config 62</code>",
            "parse_mode": "HTML",
        }
    ]
    assert FakeAdminRecoveryService.instances == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("order_not_found", "Order #23 не найден."),
        ("user_not_found", "Order #23 найден, но пользователь не найден."),
        (
            "subscription_not_found",
            "Нельзя отправить конфиг.\n\n"
            "Order ID: 23\n"
            "Подписка по этому заказу не найдена.",
        ),
    ],
)
async def test_resend_config_maps_basic_recovery_statuses(status, expected):
    FakeAdminRecoveryService.result = SimpleNamespace(status=status, order_id=23)
    message = admin_message()
    bot = FakeBot()

    await admin_resend_config_command(message, session="session", bot=bot)

    service = FakeAdminRecoveryService.instances[0]
    assert service.session == "session"
    assert service.order_ids == [23]
    assert message.answer_calls == [{"text": expected}]
    assert bot.send_message_calls == []


@pytest.mark.asyncio
async def test_resend_config_blocks_inactive_subscription():
    FakeAdminRecoveryService.result = SimpleNamespace(
        status="subscription_not_active",
        order_id=23,
        subscription_id=51,
        subscription_status="disabled",
    )
    message = admin_message()
    bot = FakeBot()

    await admin_resend_config_command(message, session="session", bot=bot)

    assert message.answer_calls == [
        {
            "text": (
                "Нельзя отправить конфиг.\n\n"
                "Order ID: 23\n"
                "Subscription ID: 51\n"
                "Status: disabled"
            )
        }
    ]
    assert bot.send_message_calls == []


@pytest.mark.asyncio
async def test_resend_config_blocks_expired_subscription_with_expiry_time():
    FakeAdminRecoveryService.result = SimpleNamespace(
        status="subscription_expired",
        order_id=23,
        subscription_id=51,
        expires_at=datetime(2026, 7, 5, 12, 0, tzinfo=timezone.utc),
    )
    message = admin_message()
    bot = FakeBot()

    await admin_resend_config_command(message, session="session", bot=bot)

    assert message.answer_calls == [
        {
            "text": (
                "Нельзя отправить конфиг.\n\n"
                "Order ID: 23\n"
                "Subscription ID: 51\n"
                "Истекла: 05.07.2026 12:00"
            )
        }
    ]
    assert bot.send_message_calls == []


@pytest.mark.asyncio
async def test_resend_config_blocks_unexpected_not_ready_result():
    FakeAdminRecoveryService.result = ready_result(status="bad_state", config_uri=None)
    message = admin_message()
    bot = FakeBot()

    await admin_resend_config_command(message, session="session", bot=bot)

    assert message.answer_calls == [
        {
            "text": (
                "Не удалось подготовить конфиг для отправки.\n\n"
                "Order ID: 23\n"
                "Status: bad_state"
            )
        }
    ]
    assert bot.send_message_calls == []


@pytest.mark.asyncio
async def test_resend_config_sends_user_message_logs_admin_action_and_answers_admin():
    FakeAdminRecoveryService.result = ready_result()
    message = admin_message()
    bot = FakeBot()

    await admin_resend_config_command(message, session="session", bot=bot)

    assert bot.send_message_calls[0]["chat_id"] == 777000
    assert (
        "Твой VPN-доступ повторно отправлен администратором."
        in bot.send_message_calls[0]["text"]
    )
    assert "Активна до: 05.08.2026 12:00" in bot.send_message_calls[0]["text"]
    assert bot.send_message_calls[0]["parse_mode"] == "HTML"
    assert bot.send_message_calls[0]["reply_markup"] is not None

    action_service = FakeAdminActionLogService.instances[0]
    assert action_service.session == "session"
    assert action_service.calls == [
        {
            "admin_telegram_id": 777,
            "action_type": "admin_resend_config",
            "target_user_id": 7,
            "order_id": 23,
            "subscription_id": 51,
            "reason": "manual_resend_config",
            "payload": "telegram_id=777000; expires_at=2026-08-05 12:00:00+00:00",
            "commit": True,
        }
    ]

    assert message.answer_calls == [
        {
            "text": (
                "Конфиг повторно отправлен пользователю.\n\n"
                "Order ID: 23\n"
                "User ID: 7\n"
                "Telegram ID: 777000\n"
                "Username: @ivan\n"
                "Subscription ID: 51\n"
                "Активна до: 05.08.2026 12:00\n"
                "Admin action ID: 99"
            )
        }
    ]


@pytest.mark.asyncio
async def test_resend_config_reports_telegram_send_error_without_admin_action():
    FakeAdminRecoveryService.result = ready_result()
    message = admin_message()
    bot = FakeBot(error=RuntimeError("bot blocked"))

    await admin_resend_config_command(message, session="session", bot=bot)

    assert message.answer_calls == [
        {
            "text": (
                "Конфиг подготовлен, но не удалось отправить пользователю в Telegram.\n\n"
                "Order ID: 23\n"
                "Telegram ID: 777000\n"
                "Ошибка: <code>RuntimeError: bot blocked</code>"
            ),
            "parse_mode": "HTML",
        }
    ]
    assert FakeAdminActionLogService.instances == []


@pytest.mark.asyncio
async def test_sync_subscriptions_returns_when_message_has_no_from_user():
    message = FakeMessage(from_user=None)
    session = FakeSession()

    await admin_sync_subscriptions_command(message, session=session)

    assert message.answer_calls == []
    assert FakeSubscriptionMetaSyncService.instances == []


@pytest.mark.asyncio
async def test_sync_subscriptions_rejects_non_admin_before_service():
    message = FakeMessage(from_user=SimpleNamespace(id=123))
    session = FakeSession()

    await admin_sync_subscriptions_command(message, session=session)

    assert message.answer_calls == [{"text": "Нет доступа."}]
    assert FakeSubscriptionMetaSyncService.instances == []


@pytest.mark.asyncio
async def test_sync_subscriptions_success_edits_status_and_logs_action():
    message = admin_message("/admin_sync_subscriptions")
    session = FakeSession()

    await admin_sync_subscriptions_command(message, session=session)

    assert message.answer_calls == [
        {"text": "Синхронизирую metadata подписок с VPS..."}
    ]

    service = FakeSubscriptionMetaSyncService.instances[0]
    assert service.session is session
    assert service.sync_count == 1

    action_service = FakeAdminActionLogService.instances[0]
    assert action_service.session is session
    assert action_service.calls[0]["admin_telegram_id"] == 777
    assert action_service.calls[0]["action_type"] == "sync_subscriptions_meta"
    assert action_service.calls[0]["reason"] == "Manual admin metadata sync."
    assert "exported_count" in action_service.calls[0]["payload"]
    assert "remote_target" in action_service.calls[0]["payload"]

    assert message.returned_messages[0].edit_text_calls == [
        {
            "text": (
                "<b>Metadata подписок синхронизирована</b>\n\n"
                "Экспортировано: <b>2</b>\n"
                "Пропущено: <b>1</b>\n"
                "Файл: <code>/tmp/subscriptions_meta.json</code>\n"
                "VPS: <code>user@host:/var/www/subscriptions_meta.json</code>"
            ),
            "parse_mode": "HTML",
        }
    ]
    assert session.rollback_count == 0


@pytest.mark.asyncio
async def test_sync_subscriptions_failure_rolls_back_logs_failure_and_edits_status():
    FakeSubscriptionMetaSyncService.error = RuntimeError("scp <failed>")
    message = admin_message("/admin_sync_subscriptions")
    session = FakeSession()

    await admin_sync_subscriptions_command(message, session=session)

    assert session.rollback_count == 1

    action_service = FakeAdminActionLogService.instances[0]
    assert action_service.session is session
    assert action_service.calls[0]["admin_telegram_id"] == 777
    assert action_service.calls[0]["action_type"] == "sync_subscriptions_meta_failed"
    assert action_service.calls[0]["reason"] == "scp <failed>"
    assert '"error": "scp <failed>"' in action_service.calls[0]["payload"]

    assert message.returned_messages[0].edit_text_calls == [
        {
            "text": (
                "<b>Ошибка синхронизации subscriptions_meta.json</b>\n\n"
                "<code>scp &lt;failed&gt;</code>\n\n"
                "Проверь SSH-ключ, путь до scp и доступ к VPS."
            ),
            "parse_mode": "HTML",
        }
    ]