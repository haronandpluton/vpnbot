from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

import pytest
from sqlalchemy.dialects import postgresql

from app.common.enums import VPNNodeActualState, VPNNodeDesiredState
from app.database.models import SubscriptionNodeAccess
from app.database.repositories.subscription_node_access import (
    SubscriptionNodeAccessRepository,
)


class FakeScalarResult:
    def __init__(self, items) -> None:
        self.items = items

    def all(self):
        return self.items


class FakeExecuteResult:
    def __init__(self, *, scalar_value=None, items=None) -> None:
        self.scalar_value = scalar_value
        self.items = items or []

    def scalar_one_or_none(self):
        return self.scalar_value

    def scalars(self):
        return FakeScalarResult(self.items)


class FakeSession:
    def __init__(self, *, scalar_value=None, items=None) -> None:
        self.scalar_value = scalar_value
        self.items = items or []
        self.execute_calls = []
        self.add_calls = []
        self.flush_count = 0
        self.next_id = 900

    async def execute(self, statement):
        self.execute_calls.append(statement)
        return FakeExecuteResult(
            scalar_value=self.scalar_value,
            items=self.items,
        )

    def add(self, obj) -> None:
        self.add_calls.append(obj)

    async def flush(self) -> None:
        self.flush_count += 1
        for obj in self.add_calls:
            if getattr(obj, "id", None) is None:
                obj.id = self.next_id
                self.next_id += 1


def make_record(
    *,
    actual_state: VPNNodeActualState = VPNNodeActualState.PENDING,
    retry_count: int = 0,
) -> SubscriptionNodeAccess:
    record = SubscriptionNodeAccess(
        subscription_id=50,
        node_code="frankfurt",
        desired_state=VPNNodeDesiredState.ENABLED,
        actual_state=actual_state,
        retry_count=retry_count,
    )
    record.id = 700
    return record


@pytest.mark.asyncio
async def test_get_by_subscription_and_node_returns_matching_record():
    record = make_record()
    session = FakeSession(scalar_value=record)
    repository = SubscriptionNodeAccessRepository(cast(Any, session))

    result = await repository.get_by_subscription_and_node(
        subscription_id=50,
        node_code="frankfurt",
    )

    assert result is record
    assert len(session.execute_calls) == 1

    compiled = str(
        session.execute_calls[0].compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert "subscription_node_access.subscription_id = 50" in compiled
    assert "subscription_node_access.node_code = 'frankfurt'" in compiled


@pytest.mark.asyncio
async def test_get_for_update_locks_single_subscription_node_row():
    record = make_record()
    session = FakeSession(scalar_value=record)
    repository = SubscriptionNodeAccessRepository(cast(Any, session))

    result = await repository.get_by_subscription_and_node_for_update(
        subscription_id=50,
        node_code="frankfurt",
    )

    assert result is record
    compiled = str(
        session.execute_calls[0].compile(
            dialect=postgresql.dialect(),
        )
    )
    assert "FOR UPDATE" in compiled


@pytest.mark.asyncio
async def test_list_by_subscription_orders_node_codes_stably():
    first = make_record()
    second = make_record()
    second.id = 701
    second.node_code = "netherlands"
    session = FakeSession(items=[first, second])
    repository = SubscriptionNodeAccessRepository(cast(Any, session))

    result = await repository.list_by_subscription(50)

    assert result == [first, second]
    compiled = str(
        session.execute_calls[0].compile(
            dialect=postgresql.dialect(),
        )
    )
    assert "ORDER BY subscription_node_access.node_code ASC" in compiled


@pytest.mark.asyncio
async def test_create_adds_pending_enabled_record_and_flushes():
    session = FakeSession()
    repository = SubscriptionNodeAccessRepository(cast(Any, session))

    record = await repository.create(
        subscription_id=50,
        node_code="frankfurt",
    )

    assert record.id == 900
    assert record.subscription_id == 50
    assert record.node_code == "frankfurt"
    assert record.desired_state == VPNNodeDesiredState.ENABLED
    assert record.actual_state == VPNNodeActualState.PENDING
    assert session.add_calls == [record]
    assert session.flush_count == 1


@pytest.mark.asyncio
async def test_set_desired_state_updates_only_target_and_flushes():
    record = make_record()
    session = FakeSession()
    repository = SubscriptionNodeAccessRepository(cast(Any, session))

    result = await repository.set_desired_state(
        record,
        VPNNodeDesiredState.DISABLED,
    )

    assert result is record
    assert record.desired_state == VPNNodeDesiredState.DISABLED
    assert record.actual_state == VPNNodeActualState.PENDING
    assert session.flush_count == 1


@pytest.mark.asyncio
async def test_mark_enabled_clears_failure_and_records_provisioning_time():
    occurred_at = datetime(2026, 8, 1, 4, 0, tzinfo=UTC)
    record = make_record(
        actual_state=VPNNodeActualState.ERROR,
        retry_count=3,
    )
    record.last_error = "panel unavailable"
    record.disabled_at = datetime(2026, 7, 31, 4, 0, tzinfo=UTC)
    session = FakeSession()
    repository = SubscriptionNodeAccessRepository(cast(Any, session))

    result = await repository.mark_enabled(
        record,
        occurred_at=occurred_at,
    )

    assert result is record
    assert record.actual_state == VPNNodeActualState.ENABLED
    assert record.provisioned_at == occurred_at
    assert record.disabled_at is None
    assert record.last_error is None
    assert record.retry_count == 0
    assert session.flush_count == 1


@pytest.mark.asyncio
async def test_mark_disabled_records_time_and_clears_failure():
    occurred_at = datetime(2026, 8, 1, 4, 30, tzinfo=UTC)
    record = make_record(
        actual_state=VPNNodeActualState.ERROR,
        retry_count=2,
    )
    record.last_error = "timeout"
    session = FakeSession()
    repository = SubscriptionNodeAccessRepository(cast(Any, session))

    result = await repository.mark_disabled(
        record,
        occurred_at=occurred_at,
    )

    assert result is record
    assert record.actual_state == VPNNodeActualState.DISABLED
    assert record.disabled_at == occurred_at
    assert record.last_error is None
    assert record.retry_count == 0
    assert session.flush_count == 1


@pytest.mark.asyncio
async def test_mark_error_persists_message_and_increments_retry_count():
    record = make_record(retry_count=2)
    session = FakeSession()
    repository = SubscriptionNodeAccessRepository(cast(Any, session))

    result = await repository.mark_error(
        record,
        error_message="netherlands: connection refused",
    )

    assert result is record
    assert record.actual_state == VPNNodeActualState.ERROR
    assert record.last_error == "netherlands: connection refused"
    assert record.retry_count == 3
    assert session.flush_count == 1

@pytest.mark.asyncio
async def test_list_reconciliation_candidates_filters_mismatched_states():
    record = make_record(actual_state=VPNNodeActualState.ERROR, retry_count=2)
    session = FakeSession(items=[record])
    repository = SubscriptionNodeAccessRepository(cast(Any, session))

    result = await repository.list_reconciliation_candidates(limit=25)

    assert result == [record]
    compiled = str(
        session.execute_calls[0].compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert "JOIN subscriptions" in compiled
    assert "subscription_node_access.desired_state" in compiled
    assert "subscription_node_access.actual_state" in compiled
    assert "subscriptions.status" in compiled
    assert "subscription_node_access.retry_count ASC" in compiled
    assert "subscription_node_access.id ASC" in compiled
    assert "LIMIT 25" in compiled


@pytest.mark.asyncio
async def test_list_reconciliation_candidates_rejects_invalid_limit():
    repository = SubscriptionNodeAccessRepository(cast(Any, FakeSession()))

    with pytest.raises(ValueError, match="limit must be positive"):
        await repository.list_reconciliation_candidates(limit=0)
