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
    ) -> None:
        self.pending = pending
        self.fail_create = fail_create
        self.lookup_calls = []
        self.create_calls = []
        self.update_calls = []

    async def get_unresolved_by_entity_and_error_type(
        self,
        **kwargs,
    ):
        self.lookup_calls.append(kwargs)
        return self.pending

    async def create(self, **kwargs):
        self.create_calls.append(kwargs)

        if self.fail_create:
            raise RuntimeError("system_errors unavailable")

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
        return error


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