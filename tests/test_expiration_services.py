from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import app.services.subscription_meta_sync_service as meta_sync_module
from app.common.enums import TariffCode
from app.payment_core.enums.order_status import OrderStatus
from app.payment_core.enums.payment_method import PaymentMethod
from app.payment_core.enums.subscription_status import SubscriptionStatus
from app.services.order_expiration_service import OrderExpirationService
from app.services.subscription_expiration_service import SubscriptionExpirationService


class FakeScalarResult:
    def __init__(self, items) -> None:
        self.items = items

    def all(self):
        return self.items


class FakeExecuteResult:
    def __init__(self, items) -> None:
        self.items = items

    def scalars(self):
        return FakeScalarResult(self.items)


class FakeSession:
    def __init__(self, items) -> None:
        self.items = items
        self.execute_calls = []
        self.commit_count = 0

    async def execute(self, stmt):
        self.execute_calls.append(stmt)
        return FakeExecuteResult(self.items)

    async def commit(self):
        self.commit_count += 1


def make_order(
    *,
    order_id: int = 23,
    user_id: int = 7,
    status: OrderStatus = OrderStatus.WAITING_PAYMENT,
    expires_at=None,
    tariff_code=TariffCode.DEVICES_1,
    payment_method=PaymentMethod.CRYPTO,
    payment_option_id: int | None = 5,
):
    return SimpleNamespace(
        id=order_id,
        user_id=user_id,
        status=status,
        expires_at=expires_at or datetime.now(timezone.utc) - timedelta(minutes=1),
        tariff_code=tariff_code,
        payment_method=payment_method,
        payment_option_id=payment_option_id,
        failure_reason=None,
        updated_at=None,
    )


def make_subscription(
    *,
    subscription_id: int = 50,
    user_id: int = 7,
    order_id: int | None = 23,
    status: SubscriptionStatus = SubscriptionStatus.ACTIVE,
    uuid: str = "sub-uuid",
    expires_at=None,
):
    return SimpleNamespace(
        id=subscription_id,
        user_id=user_id,
        order_id=order_id,
        status=status,
        uuid=uuid,
        expires_at=expires_at or datetime.now(timezone.utc) - timedelta(minutes=1),
        error_reason="old_error",
        updated_at=None,
    )


@pytest.mark.asyncio
async def test_expire_due_orders_returns_no_expired_orders_without_commit():
    now = datetime(2026, 7, 5, 12, 0, tzinfo=timezone.utc)
    session = FakeSession(items=[])
    service = OrderExpirationService(session)

    result = await service.expire_due_orders(now=now)

    assert result.status == "no_expired_orders"
    assert result.checked_at == now
    assert result.expired_count == 0
    assert result.expired_items == []
    assert result.message == "No unpaid orders are expired."
    assert len(session.execute_calls) == 1
    assert session.commit_count == 0


@pytest.mark.asyncio
async def test_expire_due_orders_marks_created_and_waiting_orders_expired_and_commits_once():
    now = datetime(2026, 7, 5, 12, 0, tzinfo=timezone.utc)
    created_order = make_order(
        order_id=1,
        user_id=10,
        status=OrderStatus.CREATED,
        expires_at=now - timedelta(minutes=10),
        tariff_code=TariffCode.DEVICES_1,
        payment_method=PaymentMethod.CRYPTO,
        payment_option_id=5,
    )
    waiting_order = make_order(
        order_id=2,
        user_id=20,
        status=OrderStatus.WAITING_PAYMENT,
        expires_at=now - timedelta(minutes=5),
        tariff_code=TariffCode.DEVICES_3,
        payment_method=PaymentMethod.TELEGRAM_STARS,
        payment_option_id=9,
    )
    session = FakeSession(items=[created_order, waiting_order])
    service = OrderExpirationService(session)

    result = await service.expire_due_orders(now=now)

    assert result.status == "expired"
    assert result.checked_at == now
    assert result.expired_count == 2
    assert result.message == "Expired unpaid orders processed."
    assert session.commit_count == 1

    assert created_order.status == OrderStatus.EXPIRED
    assert waiting_order.status == OrderStatus.EXPIRED
    assert created_order.failure_reason == "payment_timeout"
    assert waiting_order.failure_reason == "payment_timeout"
    assert created_order.updated_at == now
    assert waiting_order.updated_at == now

    assert [item.order_id for item in result.expired_items] == [1, 2]
    assert result.expired_items[0].old_status == "created"
    assert result.expired_items[0].new_status == "expired"
    assert result.expired_items[0].tariff_code == "devices_1"
    assert result.expired_items[0].payment_method == "crypto"
    assert result.expired_items[0].payment_option_id == 5
    assert result.expired_items[1].old_status == "waiting_payment"
    assert result.expired_items[1].tariff_code == "devices_3"
    assert result.expired_items[1].payment_method == "telegram_stars"
    assert result.expired_items[1].payment_option_id == 9


@pytest.mark.asyncio
async def test_expire_due_orders_does_not_filter_in_memory_and_only_changes_rows_returned_by_query():
    now = datetime(2026, 7, 5, 12, 0, tzinfo=timezone.utc)
    paid_order_returned_by_fake_db = make_order(
        order_id=3,
        status=OrderStatus.PAID,
        expires_at=now - timedelta(minutes=1),
    )
    session = FakeSession(items=[paid_order_returned_by_fake_db])
    service = OrderExpirationService(session)

    result = await service.expire_due_orders(now=now)

    assert result.status == "expired"
    assert paid_order_returned_by_fake_db.status == OrderStatus.EXPIRED
    assert paid_order_returned_by_fake_db.failure_reason == "payment_timeout"
    assert session.commit_count == 1


@pytest.mark.asyncio
async def test_expire_due_subscriptions_returns_no_expired_without_commit_and_without_sync():
    now = datetime(2026, 7, 5, 12, 0, tzinfo=timezone.utc)
    session = FakeSession(items=[])
    service = SubscriptionExpirationService(session)

    result = await service.expire_due_subscriptions(now=now, sync_metadata=True)

    assert result.status == "no_expired_subscriptions"
    assert result.checked_at == now
    assert result.expired_count == 0
    assert result.expired_items == []
    assert result.sync_status is None
    assert result.sync_error is None
    assert result.message == "No active subscriptions are expired."
    assert len(session.execute_calls) == 1
    assert session.commit_count == 0


@pytest.mark.asyncio
async def test_expire_due_subscriptions_marks_active_subscriptions_expired_and_commits_once_without_sync():
    now = datetime(2026, 7, 5, 12, 0, tzinfo=timezone.utc)
    first = make_subscription(
        subscription_id=1,
        user_id=10,
        order_id=100,
        uuid="uuid-1",
        status=SubscriptionStatus.ACTIVE,
        expires_at=now - timedelta(hours=2),
    )
    second = make_subscription(
        subscription_id=2,
        user_id=20,
        order_id=None,
        uuid="uuid-2",
        status=SubscriptionStatus.ACTIVE,
        expires_at=now - timedelta(hours=1),
    )
    session = FakeSession(items=[first, second])
    service = SubscriptionExpirationService(session)

    result = await service.expire_due_subscriptions(now=now, sync_metadata=False)

    assert result.status == "expired"
    assert result.checked_at == now
    assert result.expired_count == 2
    assert result.sync_status is None
    assert result.sync_error is None
    assert result.message == "Expired subscriptions processed."
    assert session.commit_count == 1

    assert first.status == SubscriptionStatus.EXPIRED
    assert second.status == SubscriptionStatus.EXPIRED
    assert first.error_reason is None
    assert second.error_reason is None
    assert first.updated_at == now
    assert second.updated_at == now

    assert [item.subscription_id for item in result.expired_items] == [1, 2]
    assert result.expired_items[0].user_id == 10
    assert result.expired_items[0].order_id == 100
    assert result.expired_items[0].uuid == "uuid-1"
    assert result.expired_items[0].old_status == "active"
    assert result.expired_items[0].new_status == "expired"
    assert result.expired_items[0].expires_at == first.expires_at
    assert result.expired_items[1].order_id is None


@pytest.mark.asyncio
async def test_expire_due_subscriptions_runs_metadata_sync_after_commit(monkeypatch):
    now = datetime(2026, 7, 5, 12, 0, tzinfo=timezone.utc)
    subscription = make_subscription(
        subscription_id=1,
        expires_at=now - timedelta(minutes=1),
    )
    session = FakeSession(items=[subscription])
    calls = []

    class FakeSubscriptionMetaSyncService:
        def __init__(self, session_arg) -> None:
            self.session = session_arg

        async def sync_safely(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(status="ok", exported=2, skipped=1)

    monkeypatch.setattr(
        meta_sync_module,
        "SubscriptionMetaSyncService",
        FakeSubscriptionMetaSyncService,
    )

    service = SubscriptionExpirationService(session)

    result = await service.expire_due_subscriptions(now=now, sync_metadata=True)

    assert session.commit_count == 1
    assert result.status == "expired"
    assert result.sync_status == "status=ok; exported=2; skipped=1"
    assert result.sync_error is None
    assert calls == [
        {
            "entity_type": "subscription_expiration",
            "entity_id": 0,
            "reason": "expire_due_subscriptions",
        }
    ]


@pytest.mark.asyncio
async def test_expire_due_subscriptions_sync_failure_does_not_rollback_expiration(monkeypatch):
    now = datetime(2026, 7, 5, 12, 0, tzinfo=timezone.utc)
    subscription = make_subscription(
        subscription_id=1,
        expires_at=now - timedelta(minutes=1),
    )
    session = FakeSession(items=[subscription])

    class FailingSubscriptionMetaSyncService:
        def __init__(self, session_arg) -> None:
            self.session = session_arg

        async def sync_safely(self, **kwargs):
            raise RuntimeError("metadata sync failed")

    monkeypatch.setattr(
        meta_sync_module,
        "SubscriptionMetaSyncService",
        FailingSubscriptionMetaSyncService,
    )

    service = SubscriptionExpirationService(session)

    result = await service.expire_due_subscriptions(now=now, sync_metadata=True)

    assert subscription.status == SubscriptionStatus.EXPIRED
    assert subscription.error_reason is None
    assert subscription.updated_at == now
    assert session.commit_count == 1
    assert result.status == "expired"
    assert result.expired_count == 1
    assert result.sync_status == "sync_failed"
    assert result.sync_error == "metadata sync failed"


def test_order_expiration_enum_to_str_supports_enum_and_plain_values():
    assert OrderExpirationService._enum_to_str(OrderStatus.WAITING_PAYMENT) == "waiting_payment"
    assert OrderExpirationService._enum_to_str("custom") == "custom"


def test_subscription_expiration_sync_result_to_text_supports_none_structured_and_plain_values():
    assert SubscriptionExpirationService._sync_result_to_text(None) == "sync_ok"
    assert (
        SubscriptionExpirationService._sync_result_to_text(
            SimpleNamespace(status="ok", exported=3, skipped=0)
        )
        == "status=ok; exported=3; skipped=0"
    )
    assert SubscriptionExpirationService._sync_result_to_text("done") == "done"