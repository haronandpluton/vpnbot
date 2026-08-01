from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.common.enums import VPNNodeActualState, VPNNodeDesiredState
from app.services.subscription_node_access_state_service import (
    SubscriptionNodeAccessStateService,
)


class FakeRepository:
    def __init__(self, existing: dict[tuple[int, str], object] | None = None) -> None:
        self.existing = existing or {}
        self.get_calls: list[tuple[int, str]] = []
        self.create_calls: list[dict] = []
        self.set_desired_calls: list[tuple[object, VPNNodeDesiredState]] = []

    async def get_by_subscription_and_node_for_update(
        self,
        subscription_id: int,
        node_code: str,
    ):
        self.get_calls.append((subscription_id, node_code))
        return self.existing.get((subscription_id, node_code))

    async def create(self, **kwargs):
        self.create_calls.append(kwargs)
        record = SimpleNamespace(**kwargs)
        self.existing[(kwargs["subscription_id"], kwargs["node_code"])] = record
        return record

    async def set_desired_state(self, record, desired_state):
        self.set_desired_calls.append((record, desired_state))
        record.desired_state = desired_state
        return record


def make_service(repository: FakeRepository) -> SubscriptionNodeAccessStateService:
    service = SubscriptionNodeAccessStateService.__new__(
        SubscriptionNodeAccessStateService
    )
    service.repository = repository
    return service


@pytest.mark.asyncio
async def test_initialize_pending_creates_one_row_for_each_configured_node():
    repository = FakeRepository()
    service = make_service(repository)

    records = await service.initialize_pending(
        subscription_id=41,
        node_codes=("frankfurt", "netherlands", "sweden"),
    )

    assert [record.node_code for record in records] == [
        "frankfurt",
        "netherlands",
        "sweden",
    ]
    assert repository.create_calls == [
        {
            "subscription_id": 41,
            "node_code": "frankfurt",
            "desired_state": VPNNodeDesiredState.ENABLED,
            "actual_state": VPNNodeActualState.PENDING,
        },
        {
            "subscription_id": 41,
            "node_code": "netherlands",
            "desired_state": VPNNodeDesiredState.ENABLED,
            "actual_state": VPNNodeActualState.PENDING,
        },
        {
            "subscription_id": 41,
            "node_code": "sweden",
            "desired_state": VPNNodeDesiredState.ENABLED,
            "actual_state": VPNNodeActualState.PENDING,
        },
    ]


@pytest.mark.asyncio
async def test_initialize_pending_is_idempotent_and_does_not_reset_actual_state():
    existing = SimpleNamespace(
        subscription_id=41,
        node_code="frankfurt",
        desired_state=VPNNodeDesiredState.DISABLED,
        actual_state=VPNNodeActualState.ERROR,
        last_error="temporary failure",
        retry_count=2,
    )
    repository = FakeRepository({(41, "frankfurt"): existing})
    service = make_service(repository)

    records = await service.initialize_pending(
        subscription_id=41,
        node_codes=("frankfurt", "frankfurt"),
    )

    assert records == (existing,)
    assert repository.create_calls == []
    assert repository.set_desired_calls == [
        (existing, VPNNodeDesiredState.ENABLED)
    ]
    assert existing.actual_state == VPNNodeActualState.ERROR
    assert existing.last_error == "temporary failure"
    assert existing.retry_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("subscription_id", "node_codes", "message"),
    [
        (0, ("frankfurt",), "subscription_id must be positive"),
        (41, (), "At least one VPN node is required"),
        (41, (" ",), "VPN node code must not be empty"),
    ],
)
async def test_initialize_pending_rejects_invalid_input(
    subscription_id,
    node_codes,
    message,
):
    service = make_service(FakeRepository())

    with pytest.raises(ValueError, match=message):
        await service.initialize_pending(
            subscription_id=subscription_id,
            node_codes=node_codes,
        )
