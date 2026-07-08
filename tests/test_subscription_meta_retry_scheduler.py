from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

import app.services.subscription_meta_retry_scheduler as scheduler_module
from app.services.subscription_meta_retry_scheduler import SubscriptionMetaRetryScheduler


class FakeSessionContext:
    def __init__(self, session) -> None:
        self.session = session
        self.enter_count = 0
        self.exit_count = 0

    async def __aenter__(self):
        self.enter_count += 1
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        self.exit_count += 1
        return False


class FakeSessionFactory:
    def __init__(self, session="session") -> None:
        self.session = session
        self.contexts: list[FakeSessionContext] = []

    def __call__(self):
        context = FakeSessionContext(self.session)
        self.contexts.append(context)
        return context


class FakeSubscriptionMetaSyncService:
    instances: list["FakeSubscriptionMetaSyncService"] = []
    result = SimpleNamespace(
        pending_count=0,
        attempted=False,
        ok=True,
        resolved_count=0,
        error=None,
        sync_result=None,
    )

    def __init__(self, session) -> None:
        self.session = session
        self.retry_count = 0
        self.__class__.instances.append(self)

    async def retry_pending(self):
        self.retry_count += 1
        return self.__class__.result


@pytest.fixture(autouse=True)
def reset_fakes(monkeypatch):
    FakeSubscriptionMetaSyncService.instances = []
    FakeSubscriptionMetaSyncService.result = SimpleNamespace(
        pending_count=0,
        attempted=False,
        ok=True,
        resolved_count=0,
        error=None,
        sync_result=None,
    )
    monkeypatch.setattr(
        scheduler_module,
        "SubscriptionMetaSyncService",
        FakeSubscriptionMetaSyncService,
    )


@pytest.mark.asyncio
async def test_retry_scheduler_returns_immediately_when_disabled(monkeypatch):
    monkeypatch.setattr(
        scheduler_module,
        "get_settings",
        lambda: SimpleNamespace(subscription_meta_retry_scheduler_enabled=False),
    )
    session_factory = FakeSessionFactory()
    scheduler = SubscriptionMetaRetryScheduler(session_factory)

    await scheduler.run_forever()

    assert session_factory.contexts == []
    assert FakeSubscriptionMetaSyncService.instances == []


@pytest.mark.asyncio
async def test_retry_scheduler_run_once_uses_fresh_session_and_service():
    session_factory = FakeSessionFactory(session="retry-session")
    scheduler = SubscriptionMetaRetryScheduler.__new__(SubscriptionMetaRetryScheduler)
    scheduler.session_factory = session_factory

    await scheduler.run_once()

    assert len(session_factory.contexts) == 1
    assert session_factory.contexts[0].enter_count == 1
    assert session_factory.contexts[0].exit_count == 1
    service = FakeSubscriptionMetaSyncService.instances[0]
    assert service.session == "retry-session"
    assert service.retry_count == 1


@pytest.mark.asyncio
async def test_retry_scheduler_logs_successful_retry(caplog):
    caplog.set_level(logging.INFO)
    FakeSubscriptionMetaSyncService.result = SimpleNamespace(
        pending_count=2,
        attempted=True,
        ok=True,
        resolved_count=2,
        error=None,
        sync_result=SimpleNamespace(exported_count=5, skipped_count=1),
    )
    scheduler = SubscriptionMetaRetryScheduler.__new__(SubscriptionMetaRetryScheduler)
    scheduler.session_factory = FakeSessionFactory()

    await scheduler.run_once()

    messages = [record.getMessage() for record in caplog.records]
    assert any(
        "Subscription metadata retry succeeded: pending_count=2 resolved_count=2"
        in message
        for message in messages
    )


@pytest.mark.asyncio
async def test_retry_scheduler_logs_failed_retry(caplog):
    caplog.set_level(logging.WARNING)
    FakeSubscriptionMetaSyncService.result = SimpleNamespace(
        pending_count=1,
        attempted=True,
        ok=False,
        resolved_count=0,
        error="scp unavailable",
        sync_result=None,
    )
    scheduler = SubscriptionMetaRetryScheduler.__new__(SubscriptionMetaRetryScheduler)
    scheduler.session_factory = FakeSessionFactory()

    await scheduler.run_once()

    messages = [record.getMessage() for record in caplog.records]
    assert any(
        "Subscription metadata retry failed: pending_count=1 error=scp unavailable"
        in message
        for message in messages
    )
