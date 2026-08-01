from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.common.enums import VPNNodeActualState, VPNNodeDesiredState
from app.services.subscription_node_access_reconciliation_service import (
    SubscriptionNodeAccessReconciliationService,
)
from app.services.vpn_access_service import VpnNodeStateChangeResult


class FakeSession:
    def __init__(self) -> None:
        self.commit_count = 0
        self.rollback_count = 0

    async def commit(self) -> None:
        self.commit_count += 1

    async def rollback(self) -> None:
        self.rollback_count += 1


class FakeRepository:
    def __init__(self, candidates) -> None:
        self.candidates = list(candidates)
        self.calls: list[dict] = []

    async def list_reconciliation_candidates(self, **kwargs):
        self.calls.append(kwargs)
        return list(self.candidates)


class FakeVpnAccessService:
    def __init__(self, outcomes) -> None:
        self.outcomes = dict(outcomes)
        self.calls: list[dict] = []

    async def set_access_state_on_node(
        self,
        uuid,
        node_name,
        *,
        enabled,
    ):
        self.calls.append(
            {
                "uuid": uuid,
                "node_name": node_name,
                "enabled": enabled,
            }
        )
        outcome = self.outcomes[node_name]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class FakeStateService:
    def __init__(self) -> None:
        self.successful_enable_calls: list[dict] = []
        self.failed_enable_calls: list[dict] = []
        self.successful_disable_calls: list[dict] = []
        self.failed_disable_calls: list[dict] = []

    async def record_successful_enable_results(self, **kwargs):
        self.successful_enable_calls.append(kwargs)
        return ()

    async def record_failed_enable_results(self, **kwargs):
        self.failed_enable_calls.append(kwargs)
        return ()

    async def record_successful_disable_results(self, **kwargs):
        self.successful_disable_calls.append(kwargs)
        return ()

    async def record_failed_disable_results(self, **kwargs):
        self.failed_disable_calls.append(kwargs)
        return ()


def make_candidate(
    *,
    subscription_id: int,
    uuid: str,
    node_code: str,
    desired_state: VPNNodeDesiredState,
):
    return SimpleNamespace(
        subscription_id=subscription_id,
        subscription=SimpleNamespace(uuid=uuid),
        node_code=node_code,
        desired_state=desired_state,
        actual_state=VPNNodeActualState.ERROR,
    )


@pytest.mark.asyncio
async def test_reconcile_processes_enabled_and_disabled_candidates_independently():
    enabled_candidate = make_candidate(
        subscription_id=41,
        uuid="enabled-uuid",
        node_code="frankfurt",
        desired_state=VPNNodeDesiredState.ENABLED,
    )
    disabled_candidate = make_candidate(
        subscription_id=42,
        uuid="disabled-uuid",
        node_code="netherlands",
        desired_state=VPNNodeDesiredState.DISABLED,
    )
    repository = FakeRepository([enabled_candidate, disabled_candidate])
    vpn_access = FakeVpnAccessService(
        {
            "frankfurt": VpnNodeStateChangeResult(
                node_name="frankfurt",
                succeeded=True,
            ),
            "netherlands": VpnNodeStateChangeResult(
                node_name="netherlands",
                succeeded=False,
                error="panel unavailable",
            ),
        }
    )
    state_service = FakeStateService()
    session = FakeSession()
    service = SubscriptionNodeAccessReconciliationService(
        session,
        repository=repository,
        vpn_access_service=vpn_access,
        state_service=state_service,
    )

    result = await service.reconcile(limit=20)

    assert repository.calls == [{"limit": 20}]
    assert vpn_access.calls == [
        {
            "uuid": "enabled-uuid",
            "node_name": "frankfurt",
            "enabled": True,
        },
        {
            "uuid": "disabled-uuid",
            "node_name": "netherlands",
            "enabled": False,
        },
    ]
    assert result.checked_count == 2
    assert result.succeeded_count == 1
    assert result.failed_count == 1
    assert result.errors == (
        "subscription_id=42 node=netherlands: panel unavailable",
    )
    assert session.commit_count == 2
    assert session.rollback_count == 0
    assert state_service.successful_enable_calls == [
        {
            "subscription_id": 41,
            "results": (
                VpnNodeStateChangeResult(
                    node_name="frankfurt",
                    succeeded=True,
                ),
            ),
        }
    ]
    assert state_service.failed_enable_calls == (
        state_service.successful_enable_calls
    )
    assert state_service.successful_disable_calls == [
        {
            "subscription_id": 42,
            "results": (
                VpnNodeStateChangeResult(
                    node_name="netherlands",
                    succeeded=False,
                    error="panel unavailable",
                ),
            ),
        }
    ]
    assert state_service.failed_disable_calls == (
        state_service.successful_disable_calls
    )


@pytest.mark.asyncio
async def test_reconcile_rolls_back_one_candidate_and_continues():
    first = make_candidate(
        subscription_id=41,
        uuid="first-uuid",
        node_code="frankfurt",
        desired_state=VPNNodeDesiredState.ENABLED,
    )
    second = make_candidate(
        subscription_id=42,
        uuid="second-uuid",
        node_code="netherlands",
        desired_state=VPNNodeDesiredState.DISABLED,
    )
    repository = FakeRepository([first, second])
    vpn_access = FakeVpnAccessService(
        {
            "frankfurt": RuntimeError("temporary failure"),
            "netherlands": VpnNodeStateChangeResult(
                node_name="netherlands",
                succeeded=True,
            ),
        }
    )
    session = FakeSession()
    service = SubscriptionNodeAccessReconciliationService(
        session,
        repository=repository,
        vpn_access_service=vpn_access,
        state_service=FakeStateService(),
    )

    result = await service.reconcile()

    assert result.checked_count == 2
    assert result.succeeded_count == 1
    assert result.failed_count == 1
    assert result.errors == (
        "subscription_id=41 node=frankfurt: temporary failure",
    )
    assert session.commit_count == 1
    assert session.rollback_count == 1
    assert len(vpn_access.calls) == 2


@pytest.mark.asyncio
async def test_reconcile_rejects_invalid_limit():
    service = SubscriptionNodeAccessReconciliationService.__new__(
        SubscriptionNodeAccessReconciliationService
    )

    with pytest.raises(ValueError, match="limit must be positive"):
        await service.reconcile(limit=0)
