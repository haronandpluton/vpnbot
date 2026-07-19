from __future__ import annotations

from types import SimpleNamespace

import pytest

import app.bot.main as bot_main_module
from app.bot.middlewares.db_session import DbSessionMiddleware


CALLS: list[tuple] = []


class FakeSession:
    def __init__(self, session_id: int) -> None:
        self.session_id = session_id


class FakeSessionContext:
    def __init__(self, session: FakeSession) -> None:
        self.session = session
        self.enter_count = 0
        self.exit_count = 0

    async def __aenter__(self):
        self.enter_count += 1
        CALLS.append(("session_enter", self.session.session_id))
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        self.exit_count += 1
        CALLS.append(
            (
                "session_exit",
                self.session.session_id,
                exc_type.__name__ if exc_type else None,
            )
        )
        return False


class FakeSessionFactory:
    def __init__(self) -> None:
        self.contexts: list[FakeSessionContext] = []

    def __call__(self):
        context = FakeSessionContext(FakeSession(len(self.contexts) + 1))
        self.contexts.append(context)
        return context


class FakeMiddlewareManager:
    def __init__(self, kind: str) -> None:
        self.kind = kind
        self.items: list[object] = []

    def middleware(self, item) -> None:
        self.items.append(item)
        CALLS.append((f"{self.kind}_middleware", type(item).__name__))


class FakeUpdateScope:
    def __init__(self) -> None:
        self.manager = FakeMiddlewareManager("update")

    def middleware(self, item) -> None:
        self.manager.middleware(item)


class FakeMessageScope:
    def __init__(self) -> None:
        self.manager = FakeMiddlewareManager("message")

    def middleware(self, item) -> None:
        self.manager.middleware(item)


class FakeDispatcher:
    instances: list["FakeDispatcher"] = []

    def __init__(self) -> None:
        self.update = FakeUpdateScope()
        self.message = FakeMessageScope()
        self.routers: list[object] = []
        self.polling_bot = None
        self.__class__.instances.append(self)

    def include_router(self, router) -> None:
        self.routers.append(router)
        CALLS.append(("include_router", router))

    async def start_polling(self, bot) -> None:
        self.polling_bot = bot
        CALLS.append(("start_polling", bot.token))


class FakeBot:
    instances: list["FakeBot"] = []

    def __init__(self, *, token: str) -> None:
        self.token = token
        self.__class__.instances.append(self)
        self.commands = None
        self.commands_scope = None
        CALLS.append(("bot", token))
    async def set_my_commands(self, commands, scope=None):
        self.commands = commands
        self.commands_scope = scope


class FakeTask:
    instances: list["FakeTask"] = []

    def __init__(self, name: str | None) -> None:
        self.name = name
        self.cancel_count = 0
        self.__class__.instances.append(self)

    def cancel(self) -> None:
        self.cancel_count += 1
        CALLS.append(("task_cancel", self.name, self.cancel_count))


class FakeSubscriptionExpirationScheduler:
    instances: list["FakeSubscriptionExpirationScheduler"] = []

    def __init__(self, session_factory) -> None:
        self.session_factory = session_factory
        self.__class__.instances.append(self)

    async def run_forever(self) -> None:
        CALLS.append(("subscription_scheduler_run",))


class FakeOrderExpirationScheduler:
    instances: list["FakeOrderExpirationScheduler"] = []

    def __init__(self, session_factory) -> None:
        self.session_factory = session_factory
        self.__class__.instances.append(self)

    async def run_forever(self) -> None:
        CALLS.append(("order_scheduler_run",))


class FakeSubscriptionMetaRetryScheduler:
    instances: list["FakeSubscriptionMetaRetryScheduler"] = []

    def __init__(self, session_factory) -> None:
        self.session_factory = session_factory
        self.__class__.instances.append(self)

    async def run_forever(self) -> None:
        CALLS.append(("subscription_meta_retry_scheduler_run",))


class FakeVoletSciWebServer:
    instances: list["FakeVoletSciWebServer"] = []

    def __init__(self, session_factory, settings) -> None:
        self.session_factory = session_factory
        self.settings = settings
        self.start_count = 0
        self.stop_count = 0
        self.__class__.instances.append(self)

    async def start(self) -> None:
        self.start_count += 1
        CALLS.append(("volet_start",))

    async def stop(self) -> None:
        self.stop_count += 1
        CALLS.append(("volet_stop",))


class MarkerMiddleware:
    def __init__(self, name: str) -> None:
        self.name = name


@pytest.fixture(autouse=True)
def patch_bot_main(monkeypatch):
    CALLS.clear()
    FakeDispatcher.instances = []
    FakeBot.instances = []
    FakeTask.instances = []
    FakeSubscriptionExpirationScheduler.instances = []
    FakeOrderExpirationScheduler.instances = []
    FakeSubscriptionMetaRetryScheduler.instances = []
    FakeVoletSciWebServer.instances = []

    monkeypatch.setattr(bot_main_module, "Bot", FakeBot)
    monkeypatch.setattr(bot_main_module, "Dispatcher", FakeDispatcher)
    monkeypatch.setattr(bot_main_module, "SessionLocal", "SESSION_FACTORY")
    monkeypatch.setattr(
        bot_main_module,
        "DbSessionMiddleware",
        lambda session_factory: MarkerMiddleware(f"db:{session_factory}"),
    )
    monkeypatch.setattr(
        bot_main_module,
        "DevCommandsGuardMiddleware",
        lambda: MarkerMiddleware("dev_guard"),
    )
    monkeypatch.setattr(
        bot_main_module,
        "SubscriptionExpirationScheduler",
        FakeSubscriptionExpirationScheduler,
    )
    monkeypatch.setattr(
        bot_main_module,
        "OrderExpirationScheduler",
        FakeOrderExpirationScheduler,
    )
    monkeypatch.setattr(
        bot_main_module,
        "SubscriptionMetaRetryScheduler",
        FakeSubscriptionMetaRetryScheduler,
    )
    monkeypatch.setattr(bot_main_module, "VoletSciWebServer", FakeVoletSciWebServer)

    def fake_create_task(coro, *, name=None):
        coro.close()
        CALLS.append(("create_task", name))
        return FakeTask(name)

    async def fake_gather(*tasks, return_exceptions=False):
        CALLS.append(("gather", [task.name for task in tasks], return_exceptions))
        return []

    monkeypatch.setattr(bot_main_module.asyncio, "create_task", fake_create_task)
    monkeypatch.setattr(bot_main_module.asyncio, "gather", fake_gather)


def settings(*, dev_mode: bool = False, volet_sci_enabled: bool = False):
    return SimpleNamespace(
        bot_token="bot-token",
        log_level="INFO",
        dev_mode=dev_mode,
        volet_sci_enabled=volet_sci_enabled,
    )


async def fake_handler(event, data):
    CALLS.append(("handler", event, data["session"].session_id))
    return "handler-result"


@pytest.mark.asyncio
async def test_db_session_middleware_injects_session_and_closes_context():
    factory = FakeSessionFactory()
    middleware = DbSessionMiddleware(factory)
    data = {"existing": "value"}

    result = await middleware(fake_handler, event="event", data=data)

    assert result == "handler-result"
    assert data["existing"] == "value"
    assert data["session"].session_id == 1
    assert factory.contexts[0].enter_count == 1
    assert factory.contexts[0].exit_count == 1
    assert CALLS == [
        ("session_enter", 1),
        ("handler", "event", 1),
        ("session_exit", 1, None),
    ]


@pytest.mark.asyncio
async def test_db_session_middleware_closes_context_when_handler_raises():
    factory = FakeSessionFactory()
    middleware = DbSessionMiddleware(factory)

    async def failing_handler(event, data):
        raise RuntimeError("handler failed")

    with pytest.raises(RuntimeError, match="handler failed"):
        await middleware(failing_handler, event="event", data={})

    assert factory.contexts[0].enter_count == 1
    assert factory.contexts[0].exit_count == 1
    assert CALLS == [
        ("session_enter", 1),
        ("session_exit", 1, "RuntimeError"),
    ]


@pytest.mark.asyncio
async def test_bot_main_registers_middlewares_schedulers_and_base_routers_when_dev_mode_is_false(
    monkeypatch,
):
    monkeypatch.setattr(bot_main_module, "get_settings", lambda: settings(dev_mode=False))

    await bot_main_module.main()

    dispatcher = FakeDispatcher.instances[0]
    assert FakeBot.instances[0].token == "bot-token"
    assert dispatcher.update.manager.items[0].name == "db:SESSION_FACTORY"
    assert dispatcher.message.manager.items[0].name == "dev_guard"
    assert len(dispatcher.routers) == 21
    assert bot_main_module.test_payment_check_router not in dispatcher.routers
    assert bot_main_module.dev_payment_router not in dispatcher.routers
    assert bot_main_module.dev_subscription_router not in dispatcher.routers
    assert (
        FakeSubscriptionExpirationScheduler.instances[0].session_factory
        == "SESSION_FACTORY"
    )
    assert FakeOrderExpirationScheduler.instances[0].session_factory == "SESSION_FACTORY"
    assert (
        FakeSubscriptionMetaRetryScheduler.instances[0].session_factory
        == "SESSION_FACTORY"
    )
    assert ("create_task", "subscription-expiration-scheduler") in CALLS
    assert ("create_task", "order-expiration-scheduler") in CALLS
    assert ("create_task", "subscription-meta-retry-scheduler") in CALLS
    assert ("start_polling", "bot-token") in CALLS


@pytest.mark.asyncio
async def test_bot_main_registers_dev_routers_only_when_dev_mode_is_true(monkeypatch):
    monkeypatch.setattr(bot_main_module, "get_settings", lambda: settings(dev_mode=True))

    await bot_main_module.main()

    dispatcher = FakeDispatcher.instances[0]
    assert len(dispatcher.routers) == 24
    assert dispatcher.routers[-3:] == [
        bot_main_module.test_payment_check_router,
        bot_main_module.dev_payment_router,
        bot_main_module.dev_subscription_router,
    ]


@pytest.mark.asyncio
async def test_bot_main_starts_and_stops_volet_sci_server_when_enabled(monkeypatch):
    monkeypatch.setattr(
        bot_main_module,
        "get_settings",
        lambda: settings(dev_mode=False, volet_sci_enabled=True),
    )

    await bot_main_module.main()

    server = FakeVoletSciWebServer.instances[0]
    assert server.session_factory == "SESSION_FACTORY"
    assert server.settings.volet_sci_enabled is True
    assert server.start_count == 1
    assert server.stop_count == 1
    assert CALLS.index(("volet_start",)) < CALLS.index(("start_polling", "bot-token"))
    assert CALLS.index(("start_polling", "bot-token")) < CALLS.index(("volet_stop",))


@pytest.mark.asyncio
async def test_bot_main_does_not_create_volet_server_when_disabled(monkeypatch):
    monkeypatch.setattr(
        bot_main_module,
        "get_settings",
        lambda: settings(dev_mode=False, volet_sci_enabled=False),
    )

    await bot_main_module.main()

    assert FakeVoletSciWebServer.instances == []
    assert ("volet_start",) not in CALLS
    assert ("volet_stop",) not in CALLS


@pytest.mark.asyncio
async def test_bot_main_cancels_scheduler_tasks_in_finally(monkeypatch):
    monkeypatch.setattr(bot_main_module, "get_settings", lambda: settings(dev_mode=False))

    await bot_main_module.main()

    tasks_by_name = {task.name: task for task in FakeTask.instances}
    assert tasks_by_name["subscription-expiration-scheduler"].cancel_count == 1
    assert tasks_by_name["order-expiration-scheduler"].cancel_count == 1
    assert tasks_by_name["subscription-meta-retry-scheduler"].cancel_count == 1
    assert tasks_by_name["cryptobot-background-sync-scheduler"].cancel_count == 1
    assert (
        "gather",
        [
            "subscription-expiration-scheduler",
            "order-expiration-scheduler",
            "subscription-meta-retry-scheduler",
            "cryptobot-background-sync-scheduler",
        ],
        True,
    ) in CALLS
