from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.payment_core.enums.subscription_status import SubscriptionStatus
from app.services.subscription_expiration_service import (
    SubscriptionExpirationService,
)
from app.services.vpn_access_service import VpnNodeStateChangeResult


class FakeScalarResult:
    def __init__(self, subscriptions) -> None:
        self.subscriptions = subscriptions

    def scalars(self):
        return self

    def all(self):
        return self.subscriptions


class FakeSession:
    def __init__(self, subscriptions) -> None:
        self.subscriptions = subscriptions
        self.commit_count = 0
        self.rollback_count = 0

    async def execute(self, statement):
        return FakeScalarResult(self.subscriptions)

    async def commit(self) -> None:
        self.commit_count += 1

    async def rollback(self) -> None:
        self.rollback_count += 1


class FakeVpnAccessService:
    def __init__(self, *, results=(), error: Exception | None = None) -> None:
        self.results = tuple(results)
        self.error = error
        self.calls: list[str] = []

    async def disable_access_with_results(self, uuid: str):
        self.calls.append(uuid)
        if self.error is not None:
            raise self.error
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


def make_subscription(subscription_id: int = 41):
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        id=subscription_id,
        user_id=7,
        order_id=15,
        uuid=f"uuid-{subscription_id}",
        status=SubscriptionStatus.ACTIVE,
        expires_at=now - timedelta(minutes=1),
        error_reason="old error",
        updated_at=None,
    )


@pytest.mark.asyncio
async def test_expiration_disables_nodes_and_records_partial_results():
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
    session = FakeSession([subscription])
    vpn_access = FakeVpnAccessService(results=results)
    node_state = FakeNodeAccessStateService()
    service = SubscriptionExpirationService(
        session,
        vpn_access_service=vpn_access,
        node_access_state_service=node_state,
    )

    result = await service.expire_due_subscriptions(
        sync_metadata=False,
    )

    assert subscription.status == SubscriptionStatus.EXPIRED
    assert vpn_access.calls == [subscription.uuid]
    assert node_state.success_calls == [
        {
            "subscription_id": subscription.id,
            "results": results,
        }
    ]
    assert node_state.failure_calls == [
        {
            "subscription_id": subscription.id,
            "results": results,
        }
    ]
    assert result.vpn_sync_status == "sync_failed"
    assert "node=netherlands: panel unavailable" in result.vpn_sync_error
    assert session.commit_count == 2
    assert session.rollback_count == 0


@pytest.mark.asyncio
async def test_expiration_stays_committed_when_vpn_disable_raises():
    subscription = make_subscription()
    session = FakeSession([subscription])
    vpn_access = FakeVpnAccessService(
        error=RuntimeError("vpn node unavailable"),
    )
    node_state = FakeNodeAccessStateService()
    service = SubscriptionExpirationService(
        session,
        vpn_access_service=vpn_access,
        node_access_state_service=node_state,
    )

    result = await service.expire_due_subscriptions(
        sync_metadata=False,
    )

    assert subscription.status == SubscriptionStatus.EXPIRED
    assert result.status == "expired"
    assert result.vpn_sync_status == "sync_failed"
    assert result.vpn_sync_error == (
        f"subscription_id={subscription.id}: vpn node unavailable"
    )
    assert node_state.success_calls == []
    assert node_state.failure_calls == []
    assert session.commit_count == 1
    assert session.rollback_count == 1
