from __future__ import annotations

from types import SimpleNamespace

import pytest

import app.services.order_expiration_scheduler as order_scheduler_module
import app.services.subscription_expiration_scheduler as subscription_scheduler_module
from app.services.order_expiration_scheduler import OrderExpirationScheduler
from app.services.subscription_expiration_scheduler import SubscriptionExpirationScheduler


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


class FakeOrderExpirationService:
    instances: list["FakeOrderExpirationService"] = []
    result = SimpleNamespace(expired_count=0, expired_items=[])

    def __init__(self, session) -> None:
        self.session = session
        self.expire_due_orders_count = 0
        self.__class__.instances.append(self)

    async def expire_due_orders(self):
        self.expire_due_orders_count += 1
        return self.__class__.result


class FakeSubscriptionExpirationService:
    instances: list["FakeSubscriptionExpirationService"] = []
    result = SimpleNamespace(
        expired_count=0,
        expired_items=[],
        sync_status=None,
        sync_error=None,
    )

    def __init__(self, session) -> None:
        self.session = session
        self.expire_due_subscriptions_calls: list[dict] = []
        self.__class__.instances.append(self)

    async def expire_due_subscriptions(self, **kwargs):
        self.expire_due_subscriptions_calls.append(kwargs)
        return self.__class__.result


@pytest.fixture(autouse=True)
def reset_fakes(monkeypatch):
    FakeOrderExpirationService.instances = []
    FakeOrderExpirationService.result = SimpleNamespace(expired_count=0, expired_items=[])
    FakeSubscriptionExpirationService.instances = []
    FakeSubscriptionExpirationService.result = SimpleNamespace(
        expired_count=0,
        expired_items=[],
        sync_status=None,
        sync_error=None,
    )
    monkeypatch.setattr(
        order_scheduler_module,
        "OrderExpirationService",
        FakeOrderExpirationService,
    )
    monkeypatch.setattr(
        subscription_scheduler_module,
        "SubscriptionExpirationService",
        FakeSubscriptionExpirationService,
    )


@pytest.mark.asyncio
async def test_order_scheduler_run_forever_returns_immediately_when_disabled(monkeypatch):
    monkeypatch.setattr(
        order_scheduler_module,
        "get_settings",
        lambda: SimpleNamespace(order_expiration_scheduler_enabled=False),
    )
    session_factory = FakeSessionFactory()
    scheduler = OrderExpirationScheduler(session_factory)

    await scheduler.run_forever()

    assert session_factory.contexts == []
    assert FakeOrderExpirationService.instances == []


@pytest.mark.asyncio
async def test_order_scheduler_run_once_uses_session_factory_and_expiration_service():
    session_factory = FakeSessionFactory(session="order-session")
    scheduler = OrderExpirationScheduler.__new__(OrderExpirationScheduler)
    scheduler.session_factory = session_factory

    await scheduler.run_once()

    assert len(session_factory.contexts) == 1
    assert session_factory.contexts[0].enter_count == 1
    assert session_factory.contexts[0].exit_count == 1
    assert len(FakeOrderExpirationService.instances) == 1
    assert FakeOrderExpirationService.instances[0].session == "order-session"
    assert FakeOrderExpirationService.instances[0].expire_due_orders_count == 1


@pytest.mark.asyncio
async def test_order_scheduler_run_once_logs_each_expired_order(caplog):
    item = SimpleNamespace(
        order_id=23,
        user_id=7,
        old_status="waiting_payment",
        new_status="expired",
        expires_at="2026-07-05T12:00:00Z",
    )
    FakeOrderExpirationService.result = SimpleNamespace(
        expired_count=1,
        expired_items=[item],
    )
    session_factory = FakeSessionFactory(session="order-session")
    scheduler = OrderExpirationScheduler.__new__(OrderExpirationScheduler)
    scheduler.session_factory = session_factory

    await scheduler.run_once()

    messages = [record.getMessage() for record in caplog.records]
    assert any("Expired unpaid orders processed: count=1" in msg for msg in messages)
    assert any(
        "Order expired automatically: order_id=23 user_id=7" in msg
        for msg in messages
    )


@pytest.mark.asyncio
async def test_subscription_scheduler_run_forever_returns_immediately_when_disabled(
    monkeypatch,
):
    monkeypatch.setattr(
        subscription_scheduler_module,
        "get_settings",
        lambda: SimpleNamespace(subscription_expiration_scheduler_enabled=False),
    )
    session_factory = FakeSessionFactory()
    scheduler = SubscriptionExpirationScheduler(session_factory)

    await scheduler.run_forever()

    assert session_factory.contexts == []
    assert FakeSubscriptionExpirationService.instances == []


@pytest.mark.asyncio
async def test_subscription_scheduler_run_once_uses_session_factory_service_and_metadata_sync_flag():
    session_factory = FakeSessionFactory(session="subscription-session")
    scheduler = SubscriptionExpirationScheduler.__new__(SubscriptionExpirationScheduler)
    scheduler.session_factory = session_factory

    await scheduler.run_once()

    assert len(session_factory.contexts) == 1
    assert session_factory.contexts[0].enter_count == 1
    assert session_factory.contexts[0].exit_count == 1
    assert len(FakeSubscriptionExpirationService.instances) == 1
    service = FakeSubscriptionExpirationService.instances[0]
    assert service.session == "subscription-session"
    assert service.expire_due_subscriptions_calls == [{"sync_metadata": True}]


@pytest.mark.asyncio
async def test_subscription_scheduler_run_once_logs_expired_subscription_and_sync_status(
    caplog,
):
    item = SimpleNamespace(
        subscription_id=50,
        user_id=7,
        uuid="uuid-1",
        expires_at="2026-07-05T12:00:00Z",
    )
    FakeSubscriptionExpirationService.result = SimpleNamespace(
        expired_count=1,
        expired_items=[item],
        sync_status="sync_failed",
        sync_error="scp unavailable",
    )
    session_factory = FakeSessionFactory(session="subscription-session")
    scheduler = SubscriptionExpirationScheduler.__new__(SubscriptionExpirationScheduler)
    scheduler.session_factory = session_factory

    await scheduler.run_once()

    messages = [record.getMessage() for record in caplog.records]
    assert any(
        "Expired subscriptions processed: count=1, "
        "sync_status=sync_failed, sync_error=scp unavailable" in msg
        for msg in messages
    )
    assert any(
        "Subscription expired automatically: subscription_id=50 user_id=7 uuid=uuid-1"
        in msg
        for msg in messages
    )