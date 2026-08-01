from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import app.services.admin_subscription_actions_service as actions_module
from app.payment_core.enums.subscription_status import SubscriptionStatus
from app.services.admin_subscription_actions_service import (
    AdminSubscriptionActionsService,
    VPN_DISABLE_SYNC_ERROR_TYPE,
)
from app.services.vpn_access_service import (
    VpnNodeFailure,
    VpnNodeOperationError,
    VpnNodeRenewalResult,
    VpnNodeStateChangeResult,
)


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


class FakeSystemErrorRepository:
    def __init__(self) -> None:
        self.pending = None
        self.lookup_calls: list[dict] = []
        self.create_calls: list[dict] = []
        self.update_calls: list[dict] = []
        self.resolve_calls: list[object] = []

    async def get_unresolved_by_entity_and_error_type(self, **kwargs):
        self.lookup_calls.append(kwargs)
        return self.pending

    async def create(self, **kwargs):
        self.create_calls.append(kwargs)
        self.pending = SimpleNamespace(
            id=701,
            retry_count=0,
            is_resolved=False,
            **kwargs,
        )
        return self.pending

    async def update_pending_failure(self, error, **kwargs):
        self.update_calls.append({"error": error, **kwargs})
        error.retry_count += 1
        error.entity_type = kwargs["entity_type"]
        error.entity_id = kwargs["entity_id"]
        error.error_message = kwargs["error_message"]
        error.payload = kwargs["payload"]
        return error

    async def mark_resolved(self, error):
        self.resolve_calls.append(error)
        error.is_resolved = True
        self.pending = None
        return error


class FakeVpnAccessService:
    def __init__(
        self,
        *,
        error: Exception | None = None,
        renewal_results=None,
        disable_results=None,
    ) -> None:
        self.error = error
        self.extend_calls: list[dict] = []
        self.extend_with_results_calls: list[dict] = []
        self.disable_calls: list[dict] = []
        self.renewal_results = renewal_results or (
            VpnNodeRenewalResult(
                node_name="admin-test-node",
                updated=True,
            ),
        )
        self.disable_results = (
            disable_results
            if disable_results is not None
            else (
                VpnNodeStateChangeResult(
                    node_name="admin-test-node",
                    succeeded=True,
                ),
            )
        )

    async def extend_access(self, **kwargs):
        self.extend_calls.append(kwargs)
        if self.error is not None:
            raise self.error

        return SimpleNamespace(uuid=kwargs["uuid"])

    async def extend_access_with_results(self, **kwargs):
        self.extend_with_results_calls.append(kwargs)
        if self.error is not None:
            raise self.error

        return tuple(self.renewal_results)

    async def disable_access_with_results(self, **kwargs):
        self.disable_calls.append(kwargs)
        if self.error is not None:
            raise self.error

        return tuple(self.disable_results)

    async def disable_access(self, **kwargs):
        self.disable_calls.append(kwargs)
        if self.error is not None:
            raise self.error

        return SimpleNamespace(uuid=kwargs["uuid"])


class FakeNodeAccessStateService:
    def __init__(self) -> None:
        self.record_successful_renewal_results_calls: list[dict] = []
        self.record_failed_renewal_results_calls: list[dict] = []
        self.record_successful_disable_results_calls: list[dict] = []
        self.record_failed_disable_results_calls: list[dict] = []

    async def record_successful_renewal_results(
        self,
        *,
        subscription_id,
        results,
    ):
        self.record_successful_renewal_results_calls.append(
            {
                "subscription_id": subscription_id,
                "results": tuple(results),
            }
        )
        return ()

    async def record_failed_renewal_results(
        self,
        *,
        subscription_id,
        results,
    ):
        self.record_failed_renewal_results_calls.append(
            {
                "subscription_id": subscription_id,
                "results": tuple(results),
            }
        )
        return ()

    async def record_successful_disable_results(
        self,
        *,
        subscription_id,
        results,
    ):
        self.record_successful_disable_results_calls.append(
            {
                "subscription_id": subscription_id,
                "results": tuple(results),
            }
        )
        return ()

    async def record_failed_disable_results(
        self,
        *,
        subscription_id,
        results,
    ):
        self.record_failed_disable_results_calls.append(
            {
                "subscription_id": subscription_id,
                "results": tuple(results),
            }
        )
        return ()


def make_subscription(
    *,
    subscription_id: int = 50,
    user_id: int = 7,
    order_id: int | None = 23,
    status: SubscriptionStatus = SubscriptionStatus.ACTIVE,
    uuid: str = "test-uuid",
    device_limit: int = 1,
    expires_at: datetime | None = None,
):
    return SimpleNamespace(
        id=subscription_id,
        user_id=user_id,
        order_id=order_id,
        status=status,
        uuid=uuid,
        device_limit=device_limit,
        expires_at=expires_at,
        updated_at=None,
        disabled_at=None,
        error_reason=None,
    )


def make_service(
    *,
    subscription=None,
    action_log_service: FakeActionLogService | None = None,
    vpn_access_service: FakeVpnAccessService | None = None,
    system_error_repository: FakeSystemErrorRepository | None = None,
    node_access_state_service: FakeNodeAccessStateService | None = None,
):
    service = AdminSubscriptionActionsService.__new__(AdminSubscriptionActionsService)
    service.session = FakeSession()
    service.action_log_service = action_log_service or FakeActionLogService()
    service.vpn_access_service = vpn_access_service or FakeVpnAccessService()
    service.system_error_repository = (
        system_error_repository or FakeSystemErrorRepository()
    )
    service.node_access_state_service = (
        node_access_state_service or FakeNodeAccessStateService()
    )
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
        device_limit=3,
        expires_at=old_expires_at,
    )
    action_log = FakeActionLogService(action_id=777)
    vpn_access = FakeVpnAccessService()
    service = make_service(
        subscription=subscription,
        action_log_service=action_log,
        vpn_access_service=vpn_access,
    )

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
    assert result.vpn_sync_ok is True
    assert result.vpn_sync_error is None
    assert result.message == "Subscription extended."
    assert subscription.expires_at == old_expires_at + timedelta(days=5)
    assert subscription.updated_at is not None
    assert service.session.commit_count == 2
    assert service.session.rollback_count == 0
    assert service.session.refresh_calls == [subscription]
    assert vpn_access.extend_calls == []
    assert vpn_access.extend_with_results_calls == [
        {
            "uuid": "future-uuid",
            "device_limit": 3,
            "expires_at": old_expires_at + timedelta(days=5),
        }
    ]
    successful_calls = (
        service.node_access_state_service.
        record_successful_renewal_results_calls
    )
    assert successful_calls == [
        {
            "subscription_id": 50,
            "results": vpn_access.renewal_results,
        }
    ]
    assert service.node_access_state_service.record_failed_renewal_results_calls == [
        {
            "subscription_id": 50,
            "results": vpn_access.renewal_results,
        }
    ]

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
    assert service.session.commit_count == 2
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
    vpn_access = FakeVpnAccessService()
    service = make_service(
        subscription=subscription,
        action_log_service=action_log,
        vpn_access_service=vpn_access,
    )

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
    assert vpn_access.extend_calls == []
    assert vpn_access.extend_with_results_calls == []
    assert FakeSubscriptionMetaSyncService.calls == []


@pytest.mark.asyncio
async def test_extend_subscription_keeps_committed_db_state_when_vpn_sync_fails():
    old_expires_at = datetime.now(timezone.utc) + timedelta(days=2)
    subscription = make_subscription(
        subscription_id=53,
        user_id=8,
        order_id=24,
        uuid="vpn-failure-uuid",
        device_limit=2,
        expires_at=old_expires_at,
    )
    vpn_access = FakeVpnAccessService(error=RuntimeError("netherlands unavailable"))
    service = make_service(
        subscription=subscription,
        vpn_access_service=vpn_access,
    )

    result = await service.extend_subscription(
        subscription_id=53,
        days=7,
        admin_telegram_id=123,
    )

    expected_expiry = old_expires_at + timedelta(days=7)
    assert result.status == "extended"
    assert result.new_expires_at == expected_expiry
    assert result.vpn_sync_ok is False
    assert result.vpn_sync_error == "netherlands unavailable"
    assert result.message == "Subscription extended; VPN synchronization failed."
    assert subscription.expires_at == expected_expiry
    assert service.session.commit_count == 1
    assert service.session.rollback_count == 0
    assert vpn_access.extend_calls == []
    assert vpn_access.extend_with_results_calls == [
        {
            "uuid": "vpn-failure-uuid",
            "device_limit": 2,
            "expires_at": expected_expiry,
        }
    ]
    successful_calls = (
        service.node_access_state_service.
        record_successful_renewal_results_calls
    )
    assert successful_calls == []
    assert service.node_access_state_service.record_failed_renewal_results_calls == []
    assert FakeSubscriptionMetaSyncService.calls[0]["reason"] == (
        "manual_extend_subscription"
    )


@pytest.mark.asyncio
async def test_extend_subscription_records_partial_results_per_vpn_node():
    old_expires_at = datetime.now(timezone.utc) + timedelta(days=2)
    subscription = make_subscription(
        subscription_id=54,
        user_id=8,
        order_id=24,
        uuid="partial-renewal-uuid",
        device_limit=2,
        expires_at=old_expires_at,
    )
    renewal_results = (
        VpnNodeRenewalResult(node_name="frankfurt", updated=True),
        VpnNodeRenewalResult(
            node_name="netherlands",
            updated=False,
            error="temporary panel outage",
        ),
    )
    vpn_access = FakeVpnAccessService(renewal_results=renewal_results)
    node_state = FakeNodeAccessStateService()
    service = make_service(
        subscription=subscription,
        vpn_access_service=vpn_access,
        node_access_state_service=node_state,
    )

    result = await service.extend_subscription(
        subscription_id=54,
        days=7,
        admin_telegram_id=123,
    )

    assert result.status == "extended"
    assert result.vpn_sync_ok is False
    assert result.vpn_sync_error == (
        "netherlands: temporary panel outage"
    )
    assert result.message == "Subscription extended; VPN synchronization failed."
    assert service.session.commit_count == 2
    assert node_state.record_successful_renewal_results_calls == [
        {
            "subscription_id": 54,
            "results": renewal_results,
        }
    ]
    assert node_state.record_failed_renewal_results_calls == [
        {
            "subscription_id": 54,
            "results": renewal_results,
        }
    ]


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
    vpn_access = FakeVpnAccessService()
    service = make_service(
        subscription=subscription,
        action_log_service=action_log,
        vpn_access_service=vpn_access,
    )

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
    assert result.vpn_sync_ok is True
    assert result.vpn_sync_error is None
    assert result.message == "Subscription disabled."
    assert result.disabled_at >= before_call
    assert result.disabled_at <= after_call

    assert subscription.status == SubscriptionStatus.DISABLED
    assert subscription.disabled_at == result.disabled_at
    assert subscription.error_reason == "user requested disable"
    assert subscription.updated_at is not None
    assert service.session.commit_count == 2
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
    assert "already_disabled=False" in action_log.calls[0]["payload"]
    assert vpn_access.disable_calls == [{"uuid": "disable-uuid"}]

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
async def test_disable_subscription_is_idempotent_and_reconciles_vpn_nodes():
    original_disabled_at = datetime(2026, 7, 1, 8, 0, tzinfo=timezone.utc)
    subscription = make_subscription(
        subscription_id=62,
        status=SubscriptionStatus.DISABLED,
        uuid="already-disabled-uuid",
    )
    subscription.disabled_at = original_disabled_at
    subscription.error_reason = "original reason"
    vpn_access = FakeVpnAccessService()
    action_log = FakeActionLogService(action_id=889)
    service = make_service(
        subscription=subscription,
        action_log_service=action_log,
        vpn_access_service=vpn_access,
    )

    result = await service.disable_subscription(
        subscription_id=62,
        reason="retry disable",
        admin_telegram_id=123,
    )

    assert result.status == "disabled"
    assert result.old_status == "disabled"
    assert result.new_status == "disabled"
    assert result.disabled_at == original_disabled_at
    assert result.reason == "original reason"
    assert result.vpn_sync_ok is True
    assert subscription.disabled_at == original_disabled_at
    assert subscription.error_reason == "original reason"
    assert vpn_access.disable_calls == [{"uuid": "already-disabled-uuid"}]
    assert "already_disabled=True" in action_log.calls[0]["payload"]
    assert service.session.commit_count == 2
    assert service.session.rollback_count == 0


@pytest.mark.asyncio
async def test_disable_subscription_keeps_db_disabled_when_vpn_sync_fails():
    subscription = make_subscription(
        subscription_id=63,
        status=SubscriptionStatus.ACTIVE,
        uuid="disable-failure-uuid",
    )
    vpn_access = FakeVpnAccessService(error=RuntimeError("netherlands unavailable"))
    service = make_service(
        subscription=subscription,
        vpn_access_service=vpn_access,
    )

    result = await service.disable_subscription(
        subscription_id=63,
        reason="manual block",
        admin_telegram_id=123,
    )

    assert result.status == "disabled"
    assert result.new_status == "disabled"
    assert result.vpn_sync_ok is False
    assert result.vpn_sync_error == "netherlands unavailable"
    assert result.message == "Subscription disabled; VPN synchronization failed."
    assert subscription.status == SubscriptionStatus.DISABLED
    assert service.session.commit_count == 2
    assert service.session.rollback_count == 0
    assert vpn_access.disable_calls == [{"uuid": "disable-failure-uuid"}]
    assert FakeSubscriptionMetaSyncService.calls[0]["reason"] == (
        "manual_disable_subscription"
    )


@pytest.mark.asyncio
async def test_disable_failure_is_upserted_without_duplicate_system_errors():
    subscription = make_subscription(
        subscription_id=64,
        status=SubscriptionStatus.ACTIVE,
        uuid="partial-disable-uuid",
    )
    vpn_error = VpnNodeOperationError(
        operation="disable",
        uuid=subscription.uuid,
        failures=[
            VpnNodeFailure(
                node_name="netherlands",
                error="connection refused",
            )
        ],
    )
    vpn_access = FakeVpnAccessService(error=vpn_error)
    error_repository = FakeSystemErrorRepository()
    service = make_service(
        subscription=subscription,
        vpn_access_service=vpn_access,
        system_error_repository=error_repository,
    )

    first = await service.disable_subscription(
        subscription_id=64,
        reason="manual block",
        admin_telegram_id=123,
    )
    second = await service.disable_subscription(
        subscription_id=64,
        reason="retry disable",
        admin_telegram_id=123,
    )

    assert first.vpn_sync_ok is False
    assert second.vpn_sync_ok is False
    assert subscription.status == SubscriptionStatus.DISABLED
    assert len(error_repository.create_calls) == 1
    assert len(error_repository.update_calls) == 1
    assert error_repository.pending.retry_count == 1
    assert error_repository.create_calls[0]["entity_type"] == "subscription"
    assert error_repository.create_calls[0]["entity_id"] == 64
    assert (
        error_repository.create_calls[0]["error_type"]
        == VPN_DISABLE_SYNC_ERROR_TYPE
    )
    payload = error_repository.update_calls[0]["payload"]
    assert '"operation": "disable"' in payload
    assert '"node": "netherlands"' in payload
    assert '"error": "connection refused"' in payload
    assert service.session.commit_count == 4


@pytest.mark.asyncio
async def test_successful_disable_retry_resolves_pending_system_error():
    original_disabled_at = datetime(2026, 7, 1, 8, 0, tzinfo=timezone.utc)
    subscription = make_subscription(
        subscription_id=65,
        status=SubscriptionStatus.DISABLED,
        uuid="retry-success-uuid",
    )
    subscription.disabled_at = original_disabled_at
    subscription.error_reason = "manual block"
    pending = SimpleNamespace(
        id=702,
        retry_count=1,
        is_resolved=False,
    )
    error_repository = FakeSystemErrorRepository()
    error_repository.pending = pending
    service = make_service(
        subscription=subscription,
        vpn_access_service=FakeVpnAccessService(),
        system_error_repository=error_repository,
    )

    result = await service.disable_subscription(
        subscription_id=65,
        reason="retry disable",
        admin_telegram_id=123,
    )

    assert result.vpn_sync_ok is True
    assert result.disabled_at == original_disabled_at
    assert error_repository.create_calls == []
    assert error_repository.update_calls == []
    assert error_repository.resolve_calls == [pending]
    assert pending.is_resolved is True
    assert error_repository.pending is None
    assert service.session.commit_count == 3


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