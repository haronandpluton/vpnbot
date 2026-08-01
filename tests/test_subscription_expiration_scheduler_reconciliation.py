from __future__ import annotations

from types import SimpleNamespace

import pytest

import app.services.subscription_expiration_scheduler as scheduler_module
from app.services.subscription_expiration_scheduler import (
    SubscriptionExpirationScheduler,
)


class FakeSessionContext:
    async def __aenter__(self):
        return "subscription-session"

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakeSessionFactory:
    def __call__(self):
        return FakeSessionContext()


class FakeExpirationService:
    def __init__(self, session) -> None:
        self.session = session

    async def expire_due_subscriptions(self, **kwargs):
        return SimpleNamespace(
            expired_count=0,
            expired_items=[],
            sync_status=None,
            sync_error=None,
        )


class FakeReconciliationService:
    instances: list["FakeReconciliationService"] = []
    result = SimpleNamespace(
        checked_count=0,
        succeeded_count=0,
        failed_count=0,
        errors=(),
    )

    def __init__(self, session) -> None:
        self.session = session
        self.reconcile_count = 0
        self.__class__.instances.append(self)

    async def reconcile(self):
        self.reconcile_count += 1
        return self.__class__.result


@pytest.fixture(autouse=True)
def patch_services(monkeypatch):
    FakeReconciliationService.instances = []
    FakeReconciliationService.result = SimpleNamespace(
        checked_count=0,
        succeeded_count=0,
        failed_count=0,
        errors=(),
    )
    monkeypatch.setattr(
        scheduler_module,
        "SubscriptionExpirationService",
        FakeExpirationService,
    )
    monkeypatch.setattr(
        scheduler_module,
        "SubscriptionNodeAccessReconciliationService",
        FakeReconciliationService,
    )


@pytest.mark.asyncio
async def test_scheduler_runs_reconciliation_with_same_session():
    scheduler = SubscriptionExpirationScheduler.__new__(
        SubscriptionExpirationScheduler
    )
    scheduler.session_factory = FakeSessionFactory()

    await scheduler.run_once()

    assert len(FakeReconciliationService.instances) == 1
    service = FakeReconciliationService.instances[0]
    assert service.session == "subscription-session"
    assert service.reconcile_count == 1


@pytest.mark.asyncio
async def test_scheduler_logs_reconciliation_failures(caplog):
    FakeReconciliationService.result = SimpleNamespace(
        checked_count=2,
        succeeded_count=1,
        failed_count=1,
        errors=("subscription_id=50 node=frankfurt: panel unavailable",),
    )
    scheduler = SubscriptionExpirationScheduler.__new__(
        SubscriptionExpirationScheduler
    )
    scheduler.session_factory = FakeSessionFactory()

    await scheduler.run_once()

    messages = [record.getMessage() for record in caplog.records]
    assert any(
        (
            "VPN node access reconciliation completed: checked=2, "
            "succeeded=1, failed=1, "
            "errors=subscription_id=50 node=frankfurt: panel unavailable"
        )
        in message
        for message in messages
    )
