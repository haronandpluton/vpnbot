from __future__ import annotations

import asyncio

import pytest

import app.bot.main as main_module


class FakeScheduler:
    instances: list["FakeScheduler"] = []

    def __init__(self, *args: object) -> None:
        self.args = args
        self.started = False
        self.cancelled = False
        self.__class__.instances.append(self)

    async def run_forever(self) -> None:
        self.started = True

        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise


@pytest.mark.asyncio
async def test_scheduler_tasks_include_cryptobot_and_shutdown_cleanly(
    monkeypatch,
):
    FakeScheduler.instances = []

    session_factory = object()
    bot = object()

    monkeypatch.setattr(
        main_module,
        "SessionLocal",
        session_factory,
    )
    monkeypatch.setattr(
        main_module,
        "SubscriptionExpirationScheduler",
        FakeScheduler,
    )
    monkeypatch.setattr(
        main_module,
        "OrderExpirationScheduler",
        FakeScheduler,
    )
    monkeypatch.setattr(
        main_module,
        "SubscriptionMetaRetryScheduler",
        FakeScheduler,
    )
    monkeypatch.setattr(
        main_module,
        "CryptoBotBackgroundSyncScheduler",
        FakeScheduler,
    )

    tasks = main_module.create_scheduler_tasks(bot)

    try:
        await asyncio.sleep(0)

        assert [task.get_name() for task in tasks] == [
            "subscription-expiration-scheduler",
            "order-expiration-scheduler",
            "subscription-meta-retry-scheduler",
            "cryptobot-background-sync-scheduler",
        ]

        assert len(FakeScheduler.instances) == 4
        assert FakeScheduler.instances[0].args == (session_factory,)
        assert FakeScheduler.instances[1].args == (session_factory,)
        assert FakeScheduler.instances[2].args == (session_factory,)
        assert FakeScheduler.instances[3].args == (
            session_factory,
            bot,
        )
        assert all(
            scheduler.started
            for scheduler in FakeScheduler.instances
        )
    finally:
        await main_module.stop_scheduler_tasks(tasks)

    assert all(
        scheduler.cancelled
        for scheduler in FakeScheduler.instances
    )
    assert all(task.done() for task in tasks)
    assert all(task.cancelled() for task in tasks)
