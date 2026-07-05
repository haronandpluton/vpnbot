from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.database.models import SystemErrorRecord
from app.database.repositories.system_errors import SystemErrorRecordRepository


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
    def __init__(self, *, items=None, fail_flush: bool = False) -> None:
        self.items = items or []
        self.fail_flush = fail_flush
        self.add_calls = []
        self.flush_count = 0
        self.execute_calls = []
        self.next_id = 900

    def add(self, obj) -> None:
        self.add_calls.append(obj)

    async def flush(self) -> None:
        self.flush_count += 1

        if self.fail_flush:
            raise RuntimeError("flush failed")

        for obj in self.add_calls:
            if getattr(obj, "id", None) is None:
                obj.id = self.next_id
                self.next_id += 1

    async def execute(self, stmt):
        self.execute_calls.append(stmt)
        return FakeExecuteResult(self.items)


def make_error_record(
    *,
    error_id: int = 1,
    entity_type: str = "subscription",
    entity_id: int | None = 50,
    error_type: str = "subscription_meta_sync_failed",
    error_message: str = "scp unavailable",
    payload: str | None = '{"reason":"test"}',
    is_resolved: bool = False,
    retry_count: int = 0,
    resolved_at=None,
):
    return SimpleNamespace(
        id=error_id,
        entity_type=entity_type,
        entity_id=entity_id,
        error_type=error_type,
        error_message=error_message,
        payload=payload,
        is_resolved=is_resolved,
        retry_count=retry_count,
        resolved_at=resolved_at,
    )


@pytest.mark.asyncio
async def test_create_adds_system_error_flushes_and_returns_record():
    session = FakeSession()
    repository = SystemErrorRecordRepository(session)

    error = await repository.create(
        entity_type="subscription",
        entity_id=50,
        error_type="subscription_meta_sync_failed",
        error_message="scp unavailable",
        payload='{"reason":"manual_disable_subscription"}',
    )

    assert isinstance(error, SystemErrorRecord)
    assert error.id == 900
    assert error.entity_type == "subscription"
    assert error.entity_id == 50
    assert error.error_type == "subscription_meta_sync_failed"
    assert error.error_message == "scp unavailable"
    assert error.payload == '{"reason":"manual_disable_subscription"}'
    assert session.add_calls == [error]
    assert session.flush_count == 1


@pytest.mark.asyncio
async def test_create_allows_missing_entity_id_and_payload():
    session = FakeSession()
    repository = SystemErrorRecordRepository(session)

    error = await repository.create(
        entity_type="subscription_expiration",
        entity_id=None,
        error_type="subscription_meta_sync_failed",
        error_message="sync failed",
        payload=None,
    )

    assert error.id == 900
    assert error.entity_type == "subscription_expiration"
    assert error.entity_id is None
    assert error.error_type == "subscription_meta_sync_failed"
    assert error.error_message == "sync failed"
    assert error.payload is None
    assert session.flush_count == 1


@pytest.mark.asyncio
async def test_create_propagates_flush_error_without_fake_success():
    session = FakeSession(fail_flush=True)
    repository = SystemErrorRecordRepository(session)

    with pytest.raises(RuntimeError, match="flush failed"):
        await repository.create(
            entity_type="payment_event",
            entity_id=70,
            error_type="activation_failed",
            error_message="vpn create failed",
            payload=None,
        )

    assert len(session.add_calls) == 1
    assert session.flush_count == 1


@pytest.mark.asyncio
async def test_get_unresolved_returns_scalar_records_from_query_result():
    first = make_error_record(error_id=1, is_resolved=False)
    second = make_error_record(error_id=2, is_resolved=False)
    session = FakeSession(items=[first, second])
    repository = SystemErrorRecordRepository(session)

    result = await repository.get_unresolved()

    assert result == [first, second]
    assert len(session.execute_calls) == 1


@pytest.mark.asyncio
async def test_mark_resolved_sets_flag_flushes_and_returns_same_record():
    error = make_error_record(error_id=1, is_resolved=False)
    session = FakeSession()
    repository = SystemErrorRecordRepository(session)

    result = await repository.mark_resolved(error)

    assert result is error
    assert error.is_resolved is True
    assert session.flush_count == 1


@pytest.mark.asyncio
async def test_mark_resolved_propagates_flush_error_but_keeps_attempted_state_change():
    error = make_error_record(error_id=1, is_resolved=False)
    session = FakeSession(fail_flush=True)
    repository = SystemErrorRecordRepository(session)

    with pytest.raises(RuntimeError, match="flush failed"):
        await repository.mark_resolved(error)

    assert error.is_resolved is True
    assert session.flush_count == 1


def test_system_error_record_repr_contains_core_diagnostics():
    error = SystemErrorRecord(
        entity_type="subscription",
        entity_id=50,
        error_type="subscription_meta_sync_failed",
        error_message="scp unavailable",
        payload=None,
    )
    error.id = 900
    error.is_resolved = False

    assert repr(error) == (
        "SystemErrorRecord(id=900, entity_type='subscription', "
        "error_type='subscription_meta_sync_failed', is_resolved=False)"
    )