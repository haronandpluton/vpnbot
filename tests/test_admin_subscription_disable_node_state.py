from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import app.services.admin_subscription_actions_service as service_module
from app.payment_core.enums.subscription_status import SubscriptionStatus
from app.services.admin_subscription_actions_service import (
    AdminSubscriptionActionsService,
)
from app.services.vpn_access_service import VpnNodeStateChangeResult


class FakeSession:
    def __init__(self) -> None:
        self.commit_count = 0
        self.rollback_count = 0
        self.refresh_calls: list[object] = []

    async def commit(self) -> None:
        self.commit_count += 1

    async def rollback(self) -> None:
        self.rollback_count += 1

    async def refresh(self, record) -> None:
        self.refresh_calls.append(record)


class FakeActionLogService:
    async def create_action_by_admin_telegram_id(self, **kwargs):
        return SimpleNamespace(
            status="created",
            action_id=901,
            message=None,
        )


class FakeVpnAccessService:
    def __init__(
        self,
        results: tuple[VpnNodeStateChangeResult, ...],
    ) -> None:
        self.results = results
        self.disable_calls: list[str] = []

    async def disable_access_with_results(
        self,
        uuid: str,
    ) -> tuple[VpnNodeStateChangeResult, ...]:
        self.disable_calls.append(uuid)
        return self.results


class FakeNodeAccessStateService:
    def __init__(self) -> None:
        self.success_calls: list[dict] = []
        self.failure_calls: list[dict] = []

    async def record_successful_disable_results(self, **kwargs):
        self.success_calls.append(kwargs)
        return ()

    async def record_failed_disable_results(self, **kwargs):
        self.failure_calls.append(kwargs)
        return ()


class FakeSystemErrorRepository:
    def __init__(self) -> None:
        self.created: list[dict] = []
        self.updated: list[dict] = []
        self.resolved: list[object] = []

    async def get_unresolved_by_entity_and_error_type(self, **kwargs):
        return None

    async def create(self, **kwargs):
        self.created.append(kwargs)
        return SimpleNamespace(**kwargs)

    async def update_pending_failure(self, pending, **kwargs):
        self.updated.append({"pending": pending, **kwargs})
        return pending

    async def mark_resolved(self, pending):
        self.resolved.append(pending)
        return pending


class FakeMetaSyncService:
    def __init__(self, session) -> None:
        self.session = session

    async def sync_safely(self, **kwargs):
        return SimpleNamespace(status="ok")


def make_subscription() -> SimpleNamespace:
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        id=41,
        user_id=7,
        order_id=15,
        uuid="12345678-1234-5678-1234-567812345678",
        status=SubscriptionStatus.ACTIVE,
        disabled_at=None,
        error_reason=None,
        updated_at=now - timedelta(days=1),
    )


def make_service(
    *,
    subscription,
    vpn_results: tuple[VpnNodeStateChangeResult, ...],
):
    session = FakeSession()
    vpn_access_service = FakeVpnAccessService(vpn_results)
    node_state_service = FakeNodeAccessStateService()
    system_error_repository = FakeSystemErrorRepository()

    service = AdminSubscriptionActionsService.__new__(
        AdminSubscriptionActionsService
    )
    service.session = session
    service.action_log_service = FakeActionLogService()
    service.vpn_access_service = vpn_access_service
    service.node_access_state_service = node_state_service
    service.system_error_repository = system_error_repository
    service._get_subscription = AsyncMock(return_value=subscription)

    return (
        service,
        session,
        vpn_access_service,
        node_state_service,
        system_error_repository,
    )


@pytest.mark.asyncio
async def test_disable_subscription_records_successful_and_failed_node_results(
    monkeypatch,
):
    monkeypatch.setattr(
        service_module,
        "SubscriptionMetaSyncService",
        FakeMetaSyncService,
    )
    subscription = make_subscription()
    results = (
        VpnNodeStateChangeResult(
            node_name="frankfurt",
            succeeded=True,
        ),
        VpnNodeStateChangeResult(
            node_name="netherlands",
            succeeded=False,
            error="panel unavailable",
        ),
    )
    (
        service,
        session,
        vpn_access_service,
        node_state_service,
        system_error_repository,
    ) = make_service(
        subscription=subscription,
        vpn_results=results,
    )

    result = await service.disable_subscription(
        subscription_id=subscription.id,
        reason="manual_test",
        admin_telegram_id=1001,
    )

    assert vpn_access_service.disable_calls == [subscription.uuid]
    assert node_state_service.success_calls == [
        {
            "subscription_id": subscription.id,
            "results": results,
        }
    ]
    assert node_state_service.failure_calls == [
        {
            "subscription_id": subscription.id,
            "results": results,
        }
    ]
    assert result.status == "disabled"
    assert result.vpn_sync_ok is False
    assert result.vpn_sync_error is not None
    assert "netherlands" in result.vpn_sync_error
    assert system_error_repository.created
    assert "netherlands" in system_error_repository.created[0]["payload"]
    assert subscription.status == SubscriptionStatus.DISABLED
    assert session.commit_count >= 3
    assert session.rollback_count == 0


@pytest.mark.asyncio
async def test_disable_subscription_records_all_successful_node_results(
    monkeypatch,
):
    monkeypatch.setattr(
        service_module,
        "SubscriptionMetaSyncService",
        FakeMetaSyncService,
    )
    subscription = make_subscription()
    results = (
        VpnNodeStateChangeResult(
            node_name="frankfurt",
            succeeded=True,
        ),
        VpnNodeStateChangeResult(
            node_name="netherlands",
            succeeded=True,
        ),
    )
    (
        service,
        session,
        vpn_access_service,
        node_state_service,
        system_error_repository,
    ) = make_service(
        subscription=subscription,
        vpn_results=results,
    )

    result = await service.disable_subscription(
        subscription_id=subscription.id,
        reason="manual_test",
        admin_telegram_id=1001,
    )

    assert vpn_access_service.disable_calls == [subscription.uuid]
    assert node_state_service.success_calls == [
        {
            "subscription_id": subscription.id,
            "results": results,
        }
    ]
    assert node_state_service.failure_calls == [
        {
            "subscription_id": subscription.id,
            "results": results,
        }
    ]
    assert result.status == "disabled"
    assert result.vpn_sync_ok is True
    assert result.vpn_sync_error is None
    assert system_error_repository.created == []
    assert subscription.status == SubscriptionStatus.DISABLED
    assert session.commit_count == 2
    assert session.rollback_count == 0
