from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.services.adsgram_recovery_service import (
    ADSGRAM_PURCHASE_ENQUEUE_ERROR_TYPE,
    ADSGRAM_START_ATTRIBUTION_ERROR_TYPE,
    AdsGramRecoveryService,
)


class FakeSession:
    def __init__(self) -> None:
        self.commit_count = 0
        self.rollback_count = 0

    async def commit(self) -> None:
        self.commit_count += 1

    async def rollback(self) -> None:
        self.rollback_count += 1


class FakeSystemErrorRepository:
    def __init__(
        self,
        *,
        pending=None,
        fail_create: bool = False,
        unresolved_by_type: dict | None = None,
    ) -> None:
        self.pending = pending
        self.fail_create = fail_create
        self.unresolved_by_type = (
            unresolved_by_type or {}
        )

        self.lookup_calls = []
        self.get_by_type_calls = []
        self.get_by_id_calls = []
        self.create_calls = []
        self.update_calls = []
        self.mark_resolved_calls = []

    async def get_unresolved_by_error_type(
        self,
        error_type: str,
    ):
        self.get_by_type_calls.append(error_type)

        return [
            error
            for error in self.unresolved_by_type.get(
                error_type,
                [],
            )
            if not getattr(
                error,
                "is_resolved",
                False,
            )
        ]

    async def get_by_id(
        self,
        error_id: int,
    ):
        self.get_by_id_calls.append(error_id)

        candidates = []

        if self.pending is not None:
            candidates.append(self.pending)

        for errors in self.unresolved_by_type.values():
            candidates.extend(errors)

        for error in candidates:
            if getattr(error, "id", None) == error_id:
                return error

        return None

    async def get_unresolved_by_entity_and_error_type(
        self,
        **kwargs,
    ):
        self.lookup_calls.append(kwargs)

        if self.pending is not None:
            return self.pending

        for errors in self.unresolved_by_type.values():
            for error in errors:
                if getattr(
                    error,
                    "is_resolved",
                    False,
                ):
                    continue

                if (
                    error.entity_type
                    == kwargs["entity_type"]
                    and error.entity_id
                    == kwargs["entity_id"]
                    and error.error_type
                    == kwargs["error_type"]
                ):
                    return error

        return None

    async def create(self, **kwargs):
        self.create_calls.append(kwargs)

        if self.fail_create:
            raise RuntimeError(
                "system_errors unavailable"
            )

        return SimpleNamespace(id=1, **kwargs)

    async def update_pending_failure(
        self,
        error,
        **kwargs,
    ):
        self.update_calls.append(
            {
                "error": error,
                **kwargs,
            }
        )

        error.retry_count = (
            getattr(error, "retry_count", 0) + 1
        )

        return error

    async def mark_resolved(self, error):
        self.mark_resolved_calls.append(error)

        error.is_resolved = True

        return error

def make_error_record(
    *,
    error_id: int,
    entity_type: str,
    entity_id: int,
    error_type: str,
    payload: dict,
):
    return SimpleNamespace(
        id=error_id,
        entity_type=entity_type,
        entity_id=entity_id,
        error_type=error_type,
        payload=json.dumps(payload),
        retry_count=0,
        is_resolved=False,
    )


class FakeTrackingService:
    def __init__(
        self,
        *,
        start_results=None,
        purchase_results=None,
        call_log=None,
    ) -> None:
        self.start_results = list(
            start_results or []
        )
        self.purchase_results = list(
            purchase_results or []
        )
        self.call_log = (
            call_log
            if call_log is not None
            else []
        )

        self.start_calls = []
        self.purchase_calls = []

    async def capture_start_attribution(
        self,
        **kwargs,
    ):
        self.start_calls.append(kwargs)
        self.call_log.append("start")

        if not self.start_results:
            raise AssertionError(
                "Unexpected start replay."
            )

        result = self.start_results.pop(0)

        if isinstance(result, BaseException):
            raise result

        return result

    async def enqueue_purchase_conversion(
        self,
        **kwargs,
    ):
        self.purchase_calls.append(kwargs)
        self.call_log.append("purchase")

        if not self.purchase_results:
            raise AssertionError(
                "Unexpected purchase replay."
            )

        result = self.purchase_results.pop(0)

        if isinstance(result, BaseException):
            raise result

        return result


@pytest.mark.asyncio
async def test_start_attribution_failure_is_persisted():
    session = FakeSession()
    repository = FakeSystemErrorRepository()

    service = AdsGramRecoveryService(
        session,
        system_error_repository=repository,
    )

    await service.record_start_failure(
        user_id=7,
        telegram_id=123456789,
        campaign_id="campaign_42",
        enqueue_registration=True,
        error=RuntimeError("database locked"),
    )

    assert repository.lookup_calls == [
        {
            "entity_type": "user",
            "entity_id": 7,
            "error_type": (
                ADSGRAM_START_ATTRIBUTION_ERROR_TYPE
            ),
        }
    ]

    assert len(repository.create_calls) == 1

    created = repository.create_calls[0]

    assert created["entity_type"] == "user"
    assert created["entity_id"] == 7
    assert (
        created["error_type"]
        == ADSGRAM_START_ATTRIBUTION_ERROR_TYPE
    )
    assert (
        created["error_message"]
        == "RuntimeError: database locked"
    )

    payload = json.loads(created["payload"])

    assert payload["user_id"] == 7
    assert payload["telegram_id"] == 123456789
    assert payload["campaign_id"] == "campaign_42"
    assert payload["enqueue_registration"] is True
    assert payload["error_class"] == "RuntimeError"

    assert session.rollback_count == 1
    assert session.commit_count == 1


@pytest.mark.asyncio
async def test_purchase_enqueue_failure_is_persisted():
    session = FakeSession()
    repository = FakeSystemErrorRepository()

    service = AdsGramRecoveryService(
        session,
        system_error_repository=repository,
    )

    await service.record_purchase_failure(
        user_id=7,
        order_id=23,
        payment_id=55,
        error=RuntimeError("flush failed"),
    )

    assert len(repository.create_calls) == 1

    created = repository.create_calls[0]

    assert created["entity_type"] == "order"
    assert created["entity_id"] == 23
    assert (
        created["error_type"]
        == ADSGRAM_PURCHASE_ENQUEUE_ERROR_TYPE
    )

    payload = json.loads(created["payload"])

    assert payload["user_id"] == 7
    assert payload["order_id"] == 23
    assert payload["payment_id"] == 55


@pytest.mark.asyncio
async def test_repeated_failure_updates_existing_recovery_case():
    pending = SimpleNamespace(
        id=99,
        retry_count=2,
    )
    session = FakeSession()
    repository = FakeSystemErrorRepository(
        pending=pending,
    )

    service = AdsGramRecoveryService(
        session,
        system_error_repository=repository,
    )

    await service.record_purchase_failure(
        user_id=7,
        order_id=23,
        payment_id=55,
        error=RuntimeError("still unavailable"),
    )

    assert repository.create_calls == []
    assert len(repository.update_calls) == 1

    updated = repository.update_calls[0]

    assert updated["error"] is pending
    assert updated["entity_type"] == "order"
    assert updated["entity_id"] == 23
    assert (
        updated["error_type"]
        if "error_type" in updated
        else ADSGRAM_PURCHASE_ENQUEUE_ERROR_TYPE
    )

    assert session.commit_count == 1


@pytest.mark.asyncio
async def test_recovery_persistence_failure_is_best_effort():
    session = FakeSession()
    repository = FakeSystemErrorRepository(
        fail_create=True,
    )

    service = AdsGramRecoveryService(
        session,
        system_error_repository=repository,
    )

    await service.record_purchase_failure(
        user_id=7,
        order_id=23,
        payment_id=55,
        error=RuntimeError("tracking failed"),
    )

    assert session.commit_count == 0
    assert session.rollback_count == 2

@pytest.mark.asyncio
async def test_start_attribution_recovery_preserves_existing_user_flag():
    session = FakeSession()
    repository = FakeSystemErrorRepository()

    service = AdsGramRecoveryService(
        session,
        system_error_repository=repository,
    )

    await service.record_start_failure(
        user_id=7,
        telegram_id=123456789,
        campaign_id="campaign_42",
        enqueue_registration=False,
        error=RuntimeError("database locked"),
    )

    assert len(repository.create_calls) == 1

    created = repository.create_calls[0]

    assert (
        created["error_type"]
        == ADSGRAM_START_ATTRIBUTION_ERROR_TYPE
    )

    payload = json.loads(created["payload"])

    assert payload["user_id"] == 7
    assert payload["telegram_id"] == 123456789
    assert payload["campaign_id"] == "campaign_42"
    assert payload["enqueue_registration"] is False

@pytest.mark.asyncio
async def test_run_once_replays_start_before_purchase_and_resolves_both():
    start_error = make_error_record(
        error_id=1,
        entity_type="user",
        entity_id=7,
        error_type=ADSGRAM_START_ATTRIBUTION_ERROR_TYPE,
        payload={
            "user_id": 7,
            "telegram_id": 123456789,
            "campaign_id": "campaign_42",
            "enqueue_registration": True,
        },
    )
    purchase_error = make_error_record(
        error_id=2,
        entity_type="order",
        entity_id=23,
        error_type=ADSGRAM_PURCHASE_ENQUEUE_ERROR_TYPE,
        payload={
            "user_id": 7,
            "order_id": 23,
            "payment_id": 55,
        },
    )

    session = FakeSession()
    repository = FakeSystemErrorRepository(
        unresolved_by_type={
            ADSGRAM_START_ATTRIBUTION_ERROR_TYPE: [
                start_error
            ],
            ADSGRAM_PURCHASE_ENQUEUE_ERROR_TYPE: [
                purchase_error
            ],
        }
    )

    call_log = []

    tracking = FakeTrackingService(
        start_results=[
            SimpleNamespace(
                status="already_attributed",
                conversion_id=100,
            )
        ],
        purchase_results=[
            SimpleNamespace(
                status="queued",
                conversion_id=200,
            )
        ],
        call_log=call_log,
    )

    service = AdsGramRecoveryService(
        session,
        system_error_repository=repository,
        tracking_service_factory=lambda session_arg: tracking,
    )

    result = await service.run_once()

    assert call_log == [
        "start",
        "purchase",
    ]

    assert result.start_checked == 1
    assert result.purchase_checked == 1
    assert result.resolved == 2
    assert result.deferred == 0
    assert result.failed == 0

    assert repository.mark_resolved_calls == [
        start_error,
        purchase_error,
    ]

    assert start_error.is_resolved is True
    assert purchase_error.is_resolved is True

@pytest.mark.asyncio
async def test_purchase_replay_is_deferred_while_start_recovery_is_pending():
    start_error = make_error_record(
        error_id=1,
        entity_type="user",
        entity_id=7,
        error_type=ADSGRAM_START_ATTRIBUTION_ERROR_TYPE,
        payload={
            "user_id": 7,
            "telegram_id": 123456789,
            "campaign_id": "campaign_42",
            "enqueue_registration": True,
        },
    )
    purchase_error = make_error_record(
        error_id=2,
        entity_type="order",
        entity_id=23,
        error_type=ADSGRAM_PURCHASE_ENQUEUE_ERROR_TYPE,
        payload={
            "user_id": 7,
            "order_id": 23,
            "payment_id": 55,
        },
    )

    session = FakeSession()
    repository = FakeSystemErrorRepository(
        pending=start_error,
        unresolved_by_type={
            ADSGRAM_PURCHASE_ENQUEUE_ERROR_TYPE: [
                purchase_error
            ],
        },
    )

    tracking = FakeTrackingService(
        purchase_results=[
            SimpleNamespace(
                status="not_attributed",
                conversion_id=None,
            )
        ],
    )

    service = AdsGramRecoveryService(
        session,
        system_error_repository=repository,
        tracking_service_factory=lambda session_arg: tracking,
    )

    result = await service.run_once()

    assert result.purchase_checked == 1
    assert result.resolved == 0
    assert result.deferred == 1
    assert result.failed == 0

    assert repository.mark_resolved_calls == []
    assert repository.update_calls == []

    assert purchase_error.is_resolved is False

@pytest.mark.asyncio
async def test_not_attributed_purchase_without_pending_start_is_resolved():
    purchase_error = make_error_record(
        error_id=2,
        entity_type="order",
        entity_id=23,
        error_type=ADSGRAM_PURCHASE_ENQUEUE_ERROR_TYPE,
        payload={
            "user_id": 7,
            "order_id": 23,
            "payment_id": 55,
        },
    )

    session = FakeSession()
    repository = FakeSystemErrorRepository(
        unresolved_by_type={
            ADSGRAM_PURCHASE_ENQUEUE_ERROR_TYPE: [
                purchase_error
            ],
        }
    )

    tracking = FakeTrackingService(
        purchase_results=[
            SimpleNamespace(
                status="not_attributed",
                conversion_id=None,
            )
        ],
    )

    service = AdsGramRecoveryService(
        session,
        system_error_repository=repository,
        tracking_service_factory=lambda session_arg: tracking,
    )

    result = await service.run_once()

    assert result.resolved == 1
    assert result.deferred == 0
    assert result.failed == 0

    assert repository.mark_resolved_calls == [
        purchase_error
    ]

@pytest.mark.asyncio
async def test_failed_purchase_replay_increments_retry_and_continues():
    first_error = make_error_record(
        error_id=1,
        entity_type="order",
        entity_id=23,
        error_type=ADSGRAM_PURCHASE_ENQUEUE_ERROR_TYPE,
        payload={
            "user_id": 7,
            "order_id": 23,
            "payment_id": 55,
        },
    )
    second_error = make_error_record(
        error_id=2,
        entity_type="order",
        entity_id=24,
        error_type=ADSGRAM_PURCHASE_ENQUEUE_ERROR_TYPE,
        payload={
            "user_id": 7,
            "order_id": 24,
            "payment_id": 56,
        },
    )

    session = FakeSession()
    repository = FakeSystemErrorRepository(
        unresolved_by_type={
            ADSGRAM_PURCHASE_ENQUEUE_ERROR_TYPE: [
                first_error,
                second_error,
            ],
        }
    )

    tracking = FakeTrackingService(
        purchase_results=[
            SimpleNamespace(
                status="confirmed_payment_not_found",
                conversion_id=None,
            ),
            SimpleNamespace(
                status="queued",
                conversion_id=200,
            ),
        ],
    )

    service = AdsGramRecoveryService(
        session,
        system_error_repository=repository,
        tracking_service_factory=lambda session_arg: tracking,
    )

    result = await service.run_once()

    assert result.purchase_checked == 2
    assert result.resolved == 1
    assert result.deferred == 0
    assert result.failed == 1

    assert first_error.retry_count == 1
    assert first_error.is_resolved is False

    assert second_error.is_resolved is True

    assert len(repository.update_calls) == 1
    assert repository.mark_resolved_calls == [
        second_error
    ]

@pytest.mark.asyncio
async def test_start_replay_requires_registration_conversion_id():
    start_error = make_error_record(
        error_id=1,
        entity_type="user",
        entity_id=7,
        error_type=ADSGRAM_START_ATTRIBUTION_ERROR_TYPE,
        payload={
            "user_id": 7,
            "telegram_id": 123456789,
            "campaign_id": "campaign_42",
            "enqueue_registration": True,
        },
    )

    session = FakeSession()
    repository = FakeSystemErrorRepository(
        unresolved_by_type={
            ADSGRAM_START_ATTRIBUTION_ERROR_TYPE: [
                start_error
            ],
        }
    )

    tracking = FakeTrackingService(
        start_results=[
            SimpleNamespace(
                status="already_attributed",
                conversion_id=None,
            )
        ],
    )

    service = AdsGramRecoveryService(
        session,
        system_error_repository=repository,
        tracking_service_factory=lambda session_arg: tracking,
    )

    result = await service.run_once()

    assert result.start_checked == 1
    assert result.resolved == 0
    assert result.failed == 1

    assert start_error.is_resolved is False
    assert start_error.retry_count == 1

    assert repository.mark_resolved_calls == []
    assert len(repository.update_calls) == 1

@pytest.mark.asyncio
async def test_start_replay_rejects_entity_payload_mismatch():
    start_error = make_error_record(
        error_id=1,
        entity_type="user",
        entity_id=7,
        error_type=ADSGRAM_START_ATTRIBUTION_ERROR_TYPE,
        payload={
            "user_id": 99,
            "telegram_id": 123456789,
            "campaign_id": "campaign_42",
            "enqueue_registration": True,
        },
    )

    session = FakeSession()
    repository = FakeSystemErrorRepository(
        unresolved_by_type={
            ADSGRAM_START_ATTRIBUTION_ERROR_TYPE: [
                start_error
            ],
        }
    )

    tracking = FakeTrackingService()

    service = AdsGramRecoveryService(
        session,
        system_error_repository=repository,
        tracking_service_factory=lambda session_arg: tracking,
    )

    result = await service.run_once()

    assert result.start_checked == 1
    assert result.resolved == 0
    assert result.failed == 1

    assert tracking.start_calls == []

    assert start_error.is_resolved is False
    assert start_error.retry_count == 1

    assert repository.mark_resolved_calls == []
    assert len(repository.update_calls) == 1

@pytest.mark.asyncio
async def test_purchase_replay_rejects_entity_payload_mismatch():
    purchase_error = make_error_record(
        error_id=1,
        entity_type="order",
        entity_id=23,
        error_type=ADSGRAM_PURCHASE_ENQUEUE_ERROR_TYPE,
        payload={
            "user_id": 7,
            "order_id": 999,
            "payment_id": 55,
        },
    )

    session = FakeSession()
    repository = FakeSystemErrorRepository(
        unresolved_by_type={
            ADSGRAM_PURCHASE_ENQUEUE_ERROR_TYPE: [
                purchase_error
            ],
        }
    )

    tracking = FakeTrackingService()

    service = AdsGramRecoveryService(
        session,
        system_error_repository=repository,
        tracking_service_factory=lambda session_arg: tracking,
    )

    result = await service.run_once()

    assert result.purchase_checked == 1
    assert result.resolved == 0
    assert result.failed == 1

    assert tracking.purchase_calls == []

    assert purchase_error.is_resolved is False
    assert purchase_error.retry_count == 1

    assert repository.mark_resolved_calls == []
    assert len(repository.update_calls) == 1

@pytest.mark.asyncio
async def test_malformed_recovery_payload_stays_unresolved():
    broken_error = SimpleNamespace(
        id=1,
        entity_type="order",
        entity_id=23,
        error_type=ADSGRAM_PURCHASE_ENQUEUE_ERROR_TYPE,
        payload="{broken-json",
        retry_count=0,
        is_resolved=False,
    )

    session = FakeSession()
    repository = FakeSystemErrorRepository(
        unresolved_by_type={
            ADSGRAM_PURCHASE_ENQUEUE_ERROR_TYPE: [
                broken_error
            ],
        }
    )

    tracking = FakeTrackingService()

    service = AdsGramRecoveryService(
        session,
        system_error_repository=repository,
        tracking_service_factory=lambda session_arg: tracking,
    )

    result = await service.run_once()

    assert result.purchase_checked == 1
    assert result.resolved == 0
    assert result.failed == 1

    assert tracking.purchase_calls == []

    assert broken_error.is_resolved is False
    assert broken_error.retry_count == 1

    assert repository.mark_resolved_calls == []
    assert len(repository.update_calls) == 1

    assert (
        repository.update_calls[0]["payload"]
        == "{broken-json"
    )