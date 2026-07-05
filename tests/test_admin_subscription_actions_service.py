from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import app.services.admin_subscription_actions_service as actions_module
from app.payment_core.enums.subscription_status import SubscriptionStatus
from app.services.admin_subscription_actions_service import AdminSubscriptionActionsService


class FakeSession:
    def __init__(self) -> None:
        self.commit_count = 0
        self.rollback_count = 0
        self.refresh_calls: list[object] = []

    async def commit(self) -> None:
        self.commit_count += 1

    async def rollback(self) -> None:
        self.rollback_count += 1

    async def refresh(self, obj) -> None:
        self.refresh_calls.append(obj)


class FakeActionLogService:
    def __init__(
        self,
        *,
        status: str = "created",
        action_id: int | None = 501,
        message: str = "ok",
    ) -> None:
        self.status = status
        self.action_id = action_id
        self.message = message
        self.calls: list[dict] = []

    async def create_action_by_admin_telegram_id(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            status=self.status,
            action_id=self.action_id,
            admin_user_id=900,
            message=self.message,
        )


class FakeSubscriptionMetaSyncService:
    calls: list[dict] = []

    def __init__(self, session) -> None:
        self.session = session

    async def sync_safely(self, **kwargs):
        self.__class__.calls.append(kwargs)
        return SimpleNamespace(status="ok")


def make_subscription(
    *,
    subscription_id: int = 50,
    user_id: int = 7,
    order_id: int | None = 23,
    status: SubscriptionStatus = SubscriptionStatus.ACTIVE,
    uuid: str = "test-uuid",
    expires_at: datetime | None = None,
):
    return SimpleNamespace(
        id=subscription_id,
        user_id=user_id,
        order_id=order_id,
        status=status,
        uuid=uuid,
        expires_at=expires_at,
        updated_at=None,
        disabled_at=None,
        error_reason=None,
    )


def make_service(
    *,
    subscription=None,
    action_log_service: FakeActionLogService | None = None,
):
    service = AdminSubscriptionActionsService.__new__(AdminSubscriptionActionsService)
    service.session = FakeSession()
    service.action_log_service = action_log_service or FakeActionLogService()
    service._get_subscription = lambda subscription_id: _return_subscription(
        subscription,
        subscription_id,
    )
    return service


async def _return_subscription(subscription, subscription_id: int):
    if subscription is None:
        return None

    if subscription.id != subscription_id:
        return None

    return subscription


@pytest.fixture(autouse=True)
def patch_meta_sync(monkeypatch):
    FakeSubscriptionMetaSyncService.calls = []
    monkeypatch.setattr(
        actions_module,
        "SubscriptionMetaSyncService",
        FakeSubscriptionMetaSyncService,
    )


@pytest.mark.asyncio
async def test_extend_subscription_rejects_non_positive_days_without_db_changes():
    service = make_service(subscription=make_subscription())

    result = await service.extend_subscription(
        subscription_id=50,
        days=0,
        admin_telegram_id=123,
    )

    assert result.status == "invalid_days"
    assert result.subscription_id == 50
    assert result.days == 0
    assert result.message == "Days must be greater than zero."
    assert service.action_log_service.calls == []
    assert service.session.commit_count == 0
    assert service.session.rollback_count == 0
    assert FakeSubscriptionMetaSyncService.calls == []


@pytest.mark.asyncio
async def test_extend_subscription_returns_not_found_without_db_changes():
    service = make_service(subscription=None)

    result = await service.extend_subscription(
        subscription_id=404,
        days=7,
        admin_telegram_id=123,
    )

    assert result.status == "subscription_not_found"
    assert result.subscription_id == 404
    assert result.days == 7
    assert result.message == "Subscription not found."
    assert service.action_log_service.calls == []
    assert service.session.commit_count == 0
    assert service.session.rollback_count == 0
    assert FakeSubscriptionMetaSyncService.calls == []


@pytest.mark.asyncio
async def test_extend_subscription_with_future_expiry_extends_from_old_expiry_and_logs_action():
    old_expires_at = datetime.now(timezone.utc) + timedelta(days=10)
    subscription = make_subscription(
        subscription_id=50,
        user_id=7,
        order_id=23,
        uuid="future-uuid",
        expires_at=old_expires_at,
    )
    action_log = FakeActionLogService(action_id=777)
    service = make_service(subscription=subscription, action_log_service=action_log)

    result = await service.extend_subscription(
        subscription_id=50,
        days=5,
        admin_telegram_id=123456,
    )

    assert result.status == "extended"
    assert result.subscription_id == 50
    assert result.user_id == 7
    assert result.order_id == 23
    assert result.uuid == "future-uuid"
    assert result.days == 5
    assert result.old_expires_at == old_expires_at
    assert result.new_expires_at == old_expires_at + timedelta(days=5)
    assert result.admin_action_id == 777
    assert result.message == "Subscription extended."
    assert subscription.expires_at == old_expires_at + timedelta(days=5)
    assert subscription.updated_at is not None
    assert service.session.commit_count == 1
    assert service.session.rollback_count == 0
    assert service.session.refresh_calls == [subscription]

    assert action_log.calls == [
        {
            "admin_telegram_id": 123456,
            "action_type": "manual_extend_subscription",
            "target_user_id": 7,
            "order_id": 23,
            "subscription_id": 50,
            "reason": "extend_days:5",
            "payload": (
                f"old_expires_at={old_expires_at}; "
                f"new_expires_at={old_expires_at + timedelta(days=5)}; "
                "days=5"
            ),
            "commit": False,
        }
    ]
    assert FakeSubscriptionMetaSyncService.calls == [
        {
            "entity_type": "subscription",
            "entity_id": 50,
            "reason": "manual_extend_subscription",
            "payload": {
                "subscription_id": 50,
                "user_id": 7,
                "order_id": 23,
                "uuid": "future-uuid",
                "old_expires_at": old_expires_at.isoformat(),
                "new_expires_at": (
                    old_expires_at + timedelta(days=5)
                ).isoformat(),
                "days": 5,
                "admin_action_id": 777,
            },
        }
    ]


@pytest.mark.asyncio
async def test_extend_subscription_with_past_expiry_extends_from_now_not_old_expiry():
    old_expires_at = datetime.now(timezone.utc) - timedelta(days=3)
    before_call = datetime.now(timezone.utc)
    subscription = make_subscription(
        subscription_id=51,
        user_id=7,
        order_id=23,
        uuid="past-uuid",
        expires_at=old_expires_at,
    )
    service = make_service(subscription=subscription)

    result = await service.extend_subscription(
        subscription_id=51,
        days=10,
        admin_telegram_id=123,
    )

    after_call = datetime.now(timezone.utc)

    assert result.status == "extended"
    assert result.old_expires_at == old_expires_at
    assert result.new_expires_at >= before_call + timedelta(days=10)
    assert result.new_expires_at <= after_call + timedelta(days=10, seconds=1)
    assert subscription.expires_at == result.new_expires_at
    assert subscription.expires_at > old_expires_at + timedelta(days=10)
    assert service.session.commit_count == 1
    assert FakeSubscriptionMetaSyncService.calls[0]["reason"] == (
        "manual_extend_subscription"
    )


@pytest.mark.asyncio
async def test_extend_subscription_rolls_back_when_action_log_fails():
    old_expires_at = datetime.now(timezone.utc) + timedelta(days=2)
    subscription = make_subscription(
        subscription_id=52,
        user_id=7,
        order_id=23,
        uuid="rollback-uuid",
        expires_at=old_expires_at,
    )
    action_log = FakeActionLogService(
        status="admin_user_not_found",
        action_id=None,
        message="Admin user not found in users table.",
    )
    service = make_service(subscription=subscription, action_log_service=action_log)

    result = await service.extend_subscription(
        subscription_id=52,
        days=3,
        admin_telegram_id=999,
    )

    assert result.status == "admin_user_not_found"
    assert result.subscription_id == 52
    assert result.days == 3
    assert result.old_expires_at == old_expires_at
    assert result.new_expires_at == old_expires_at + timedelta(days=3)
    assert result.user_id == 7
    assert result.order_id == 23
    assert result.uuid == "rollback-uuid"
    assert result.message == "Admin user not found in users table."
    assert service.session.commit_count == 0
    assert service.session.rollback_count == 1
    assert service.session.refresh_calls == []
    assert FakeSubscriptionMetaSyncService.calls == []


@pytest.mark.asyncio
async def test_disable_subscription_rejects_blank_reason_without_db_changes():
    service = make_service(subscription=make_subscription())

    result = await service.disable_subscription(
        subscription_id=50,
        reason="   ",
        admin_telegram_id=123,
    )

    assert result.status == "invalid_reason"
    assert result.subscription_id == 50
    assert result.message == "Reason is required."
    assert service.action_log_service.calls == []
    assert service.session.commit_count == 0
    assert service.session.rollback_count == 0
    assert FakeSubscriptionMetaSyncService.calls == []


@pytest.mark.asyncio
async def test_disable_subscription_returns_not_found_without_db_changes():
    service = make_service(subscription=None)

    result = await service.disable_subscription(
        subscription_id=404,
        reason="manual abuse",
        admin_telegram_id=123,
    )

    assert result.status == "subscription_not_found"
    assert result.subscription_id == 404
    assert result.reason == "manual abuse"
    assert result.message == "Subscription not found."
    assert service.action_log_service.calls == []
    assert service.session.commit_count == 0
    assert service.session.rollback_count == 0
    assert FakeSubscriptionMetaSyncService.calls == []


@pytest.mark.asyncio
async def test_disable_subscription_sets_disabled_status_logs_action_and_syncs_metadata():
    subscription = make_subscription(
        subscription_id=60,
        user_id=8,
        order_id=24,
        status=SubscriptionStatus.ACTIVE,
        uuid="disable-uuid",
        expires_at=datetime.now(timezone.utc) + timedelta(days=10),
    )
    action_log = FakeActionLogService(action_id=888)
    service = make_service(subscription=subscription, action_log_service=action_log)

    before_call = datetime.now(timezone.utc)
    result = await service.disable_subscription(
        subscription_id=60,
        reason="  user requested disable  ",
        admin_telegram_id=123456,
    )
    after_call = datetime.now(timezone.utc)

    assert result.status == "disabled"
    assert result.subscription_id == 60
    assert result.old_status == "active"
    assert result.new_status == "disabled"
    assert result.user_id == 8
    assert result.order_id == 24
    assert result.uuid == "disable-uuid"
    assert result.reason == "user requested disable"
    assert result.admin_action_id == 888
    assert result.message == "Subscription disabled."
    assert result.disabled_at >= before_call
    assert result.disabled_at <= after_call

    assert subscription.status == SubscriptionStatus.DISABLED
    assert subscription.disabled_at == result.disabled_at
    assert subscription.error_reason == "user requested disable"
    assert subscription.updated_at is not None
    assert service.session.commit_count == 1
    assert service.session.rollback_count == 0
    assert service.session.refresh_calls == [subscription]

    assert action_log.calls[0]["admin_telegram_id"] == 123456
    assert action_log.calls[0]["action_type"] == "manual_disable_subscription"
    assert action_log.calls[0]["target_user_id"] == 8
    assert action_log.calls[0]["order_id"] == 24
    assert action_log.calls[0]["subscription_id"] == 60
    assert action_log.calls[0]["reason"] == "user requested disable"
    assert action_log.calls[0]["commit"] is False
    assert "old_status=active" in action_log.calls[0]["payload"]
    assert "new_status=disabled" in action_log.calls[0]["payload"]
    assert "disabled_at=" in action_log.calls[0]["payload"]

    assert FakeSubscriptionMetaSyncService.calls == [
        {
            "entity_type": "subscription",
            "entity_id": 60,
            "reason": "manual_disable_subscription",
            "payload": {
                "subscription_id": 60,
                "user_id": 8,
                "order_id": 24,
                "uuid": "disable-uuid",
                "old_status": "active",
                "new_status": "disabled",
                "disabled_at": result.disabled_at.isoformat(),
                "reason": "user requested disable",
                "admin_action_id": 888,
            },
        }
    ]


@pytest.mark.asyncio
async def test_disable_subscription_rolls_back_when_action_log_fails():
    subscription = make_subscription(
        subscription_id=61,
        user_id=8,
        order_id=24,
        status=SubscriptionStatus.ACTIVE,
        uuid="disable-rollback-uuid",
    )
    action_log = FakeActionLogService(
        status="admin_user_not_found",
        action_id=None,
        message="Admin user not found in users table.",
    )
    service = make_service(subscription=subscription, action_log_service=action_log)

    result = await service.disable_subscription(
        subscription_id=61,
        reason="manual block",
        admin_telegram_id=999,
    )

    assert result.status == "admin_user_not_found"
    assert result.subscription_id == 61
    assert result.old_status == "active"
    assert result.new_status == "disabled"
    assert result.user_id == 8
    assert result.order_id == 24
    assert result.uuid == "disable-rollback-uuid"
    assert result.reason == "manual block"
    assert result.message == "Admin user not found in users table."
    assert service.session.commit_count == 0
    assert service.session.rollback_count == 1
    assert service.session.refresh_calls == []
    assert FakeSubscriptionMetaSyncService.calls == []


def test_enum_to_str_handles_none_enum_and_plain_string():
    assert AdminSubscriptionActionsService._enum_to_str(None) is None
    assert AdminSubscriptionActionsService._enum_to_str(SubscriptionStatus.ACTIVE) == "active"
    assert AdminSubscriptionActionsService._enum_to_str("custom") == "custom"