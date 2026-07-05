from __future__ import annotations

from types import SimpleNamespace

import pytest

import app.bot.middlewares.dev_commands_guard as guard_module
import app.bot.utils.access as access_module
from app.bot.middlewares.dev_commands_guard import DEV_COMMANDS, DevCommandsGuardMiddleware


class FakeMessage:
    def __init__(self, *, text=None, from_user=None) -> None:
        self.text = text
        self.from_user = from_user
        self.answer_calls: list[dict] = []

    async def answer(self, text: str, **kwargs) -> None:
        self.answer_calls.append({"text": text, **kwargs})


class FakeOtherEvent:
    pass


async def fake_handler(event, data):
    data.setdefault("handled", []).append(event)
    return "handled-result"


@pytest.fixture(autouse=True)
def patch_message_class(monkeypatch):
    monkeypatch.setattr(guard_module, "Message", FakeMessage)


def make_middleware():
    return DevCommandsGuardMiddleware()


@pytest.mark.asyncio
async def test_non_message_event_passes_through_handler():
    event = FakeOtherEvent()
    data = {}
    middleware = make_middleware()

    result = await middleware(fake_handler, event, data)

    assert result == "handled-result"
    assert data["handled"] == [event]


@pytest.mark.asyncio
async def test_message_without_text_passes_through_handler():
    event = FakeMessage(text=None, from_user=SimpleNamespace(id=123))
    data = {}
    middleware = make_middleware()

    result = await middleware(fake_handler, event, data)

    assert result == "handled-result"
    assert data["handled"] == [event]
    assert event.answer_calls == []


@pytest.mark.asyncio
async def test_regular_command_passes_through_without_admin_or_dev_checks(monkeypatch):
    calls = []

    def fake_is_admin(telegram_id: int) -> bool:
        calls.append(("is_admin", telegram_id))
        return False

    def fake_is_dev_mode_enabled() -> bool:
        calls.append(("is_dev", None))
        return False

    monkeypatch.setattr(guard_module, "is_admin", fake_is_admin)
    monkeypatch.setattr(guard_module, "is_dev_mode_enabled", fake_is_dev_mode_enabled)

    event = FakeMessage(text="/start", from_user=SimpleNamespace(id=123))
    data = {}
    middleware = make_middleware()

    result = await middleware(fake_handler, event, data)

    assert result == "handled-result"
    assert calls == []
    assert event.answer_calls == []


@pytest.mark.asyncio
async def test_dev_command_without_from_user_is_blocked_silently(monkeypatch):
    calls = []

    monkeypatch.setattr(
        guard_module,
        "is_admin",
        lambda telegram_id: calls.append("admin"),
    )
    monkeypatch.setattr(
        guard_module,
        "is_dev_mode_enabled",
        lambda: calls.append("dev"),
    )

    event = FakeMessage(text="/dev_payment", from_user=None)
    data = {}
    middleware = make_middleware()

    result = await middleware(fake_handler, event, data)

    assert result is None
    assert data == {}
    assert calls == []
    assert event.answer_calls == []


@pytest.mark.asyncio
async def test_dev_command_from_non_admin_is_blocked_with_no_access_message(monkeypatch):
    monkeypatch.setattr(guard_module, "is_admin", lambda telegram_id: False)
    monkeypatch.setattr(guard_module, "is_dev_mode_enabled", lambda: True)

    event = FakeMessage(text="/dev_payment", from_user=SimpleNamespace(id=123))
    data = {}
    middleware = make_middleware()

    result = await middleware(fake_handler, event, data)

    assert result is None
    assert data == {}
    assert event.answer_calls == [{"text": "Нет доступа."}]


@pytest.mark.asyncio
async def test_dev_command_from_admin_is_blocked_when_dev_mode_is_disabled(monkeypatch):
    monkeypatch.setattr(guard_module, "is_admin", lambda telegram_id: True)
    monkeypatch.setattr(guard_module, "is_dev_mode_enabled", lambda: False)

    event = FakeMessage(text="/dev_payment", from_user=SimpleNamespace(id=123))
    data = {}
    middleware = make_middleware()

    result = await middleware(fake_handler, event, data)

    assert result is None
    assert data == {}
    assert event.answer_calls == [
        {
            "text": (
                "Dev-команды отключены.\n\n"
                "Для локальной разработки установи в .env:\n"
                "<code>DEV_MODE=true</code>"
            ),
            "parse_mode": "HTML",
        }
    ]


@pytest.mark.asyncio
async def test_dev_command_from_admin_passes_when_dev_mode_is_enabled(monkeypatch):
    monkeypatch.setattr(guard_module, "is_admin", lambda telegram_id: telegram_id == 123)
    monkeypatch.setattr(guard_module, "is_dev_mode_enabled", lambda: True)

    event = FakeMessage(text="/dev_payment order_id=23", from_user=SimpleNamespace(id=123))
    data = {}
    middleware = make_middleware()

    result = await middleware(fake_handler, event, data)

    assert result == "handled-result"
    assert data["handled"] == [event]
    assert event.answer_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("command", sorted(DEV_COMMANDS))
async def test_all_registered_dev_commands_are_guarded(monkeypatch, command):
    monkeypatch.setattr(guard_module, "is_admin", lambda telegram_id: False)
    monkeypatch.setattr(guard_module, "is_dev_mode_enabled", lambda: True)

    event = FakeMessage(text=f"{command} payload", from_user=SimpleNamespace(id=123))
    data = {}
    middleware = make_middleware()

    result = await middleware(fake_handler, event, data)

    assert result is None
    assert data == {}
    assert event.answer_calls == [{"text": "Нет доступа."}]


def test_is_admin_reads_admin_ids_from_settings(monkeypatch):
    monkeypatch.setattr(
        access_module,
        "get_settings",
        lambda: SimpleNamespace(admin_ids=[1, 2, 3], dev_mode=False),
    )

    assert access_module.is_admin(2) is True
    assert access_module.is_admin(99) is False


def test_is_dev_mode_enabled_reads_dev_mode_from_settings(monkeypatch):
    monkeypatch.setattr(
        access_module,
        "get_settings",
        lambda: SimpleNamespace(admin_ids=[], dev_mode=True),
    )

    assert access_module.is_dev_mode_enabled() is True


@pytest.mark.parametrize(
    ("admin_ids", "dev_mode", "expected"),
    [
        ([123], True, True),
        ([123], False, False),
        ([], True, False),
        ([], False, False),
    ],
)
def test_can_use_dev_commands_requires_admin_and_dev_mode(
    monkeypatch,
    admin_ids,
    dev_mode,
    expected,
):
    monkeypatch.setattr(
        access_module,
        "get_settings",
        lambda: SimpleNamespace(admin_ids=admin_ids, dev_mode=dev_mode),
    )

    assert access_module.can_use_dev_commands(123) is expected