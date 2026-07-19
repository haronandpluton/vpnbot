from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.services.cryptobot_payment_notification_service import (
    CRYPTOBOT_NOTIFICATION_ERROR_TYPE,
    CRYPTOBOT_PAYMENT_CONFIRMED_TEXT,
    CryptoBotPaymentNotificationService,
)


class FakeSession:
    def __init__(self) -> None:
        self.commit_count = 0
        self.rollback_count = 0

    async def commit(self) -> None:
        self.commit_count += 1

    async def rollback(self) -> None:
        self.rollback_count += 1


class FakePaymentEventRepository:
    def __init__(
        self,
        *,
        claim_result: bool = True,
        mark_result: bool = True,
        release_result: bool = True,
        mark_error: Exception | None = None,
    ) -> None:
        self.claim_result = claim_result
        self.mark_result = mark_result
        self.release_result = release_result
        self.mark_error = mark_error

        self.claim_calls: list[dict] = []
        self.mark_calls: list[dict] = []
        self.release_calls: list[dict] = []

    async def claim_notification(self, event_id: int, **kwargs) -> bool:
        self.claim_calls.append({"event_id": event_id, **kwargs})
        return self.claim_result

    async def mark_notification_sent(self, event_id: int, **kwargs) -> bool:
        self.mark_calls.append({"event_id": event_id, **kwargs})

        if self.mark_error is not None:
            raise self.mark_error

        return self.mark_result

    async def release_notification_claim(self, event_id: int, **kwargs) -> bool:
        self.release_calls.append({"event_id": event_id, **kwargs})
        return self.release_result


class FakeSystemErrorRepository:
    def __init__(self, *, pending=None) -> None:
        self.pending = pending
        self.lookup_calls: list[dict] = []
        self.create_calls: list[dict] = []
        self.update_calls: list[dict] = []
        self.resolve_calls: list[object] = []

    async def get_unresolved_by_entity_and_error_type(self, **kwargs):
        self.lookup_calls.append(kwargs)
        return self.pending

    async def create(self, **kwargs):
        self.create_calls.append(kwargs)
        return SimpleNamespace(id=900, **kwargs)

    async def update_pending_failure(self, error, **kwargs):
        self.update_calls.append({"error": error, **kwargs})
        return error

    async def mark_resolved(self, error):
        self.resolve_calls.append(error)
        return error


def make_service(
    *,
    session=None,
    payment_event_repository=None,
    system_error_repository=None,
):
    session = session or FakeSession()
    payment_event_repository = (
        payment_event_repository or FakePaymentEventRepository()
    )
    system_error_repository = (
        system_error_repository or FakeSystemErrorRepository()
    )

    service = CryptoBotPaymentNotificationService(
        session,
        payment_event_repository=payment_event_repository,
        system_error_repository=system_error_repository,
        settings=SimpleNamespace(
            cryptobot_notification_claim_ttl_seconds=300,
        ),
    )

    return (
        service,
        session,
        payment_event_repository,
        system_error_repository,
    )


@pytest.mark.asyncio
async def test_successful_notification_is_claimed_sent_and_persisted():
    service, session, event_repository, error_repository = make_service()
    sent_messages: list[str] = []

    async def send_message(text: str) -> None:
        sent_messages.append(text)

    result = await service.deliver(
        event_id=70,
        order_id=23,
        telegram_id=123456789,
        send_message=send_message,
    )

    assert result.attempted is True
    assert result.delivered is True
    assert result.persisted is True
    assert result.reason is None

    assert sent_messages == [CRYPTOBOT_PAYMENT_CONFIRMED_TEXT]
    assert len(event_repository.claim_calls) == 1
    assert len(event_repository.mark_calls) == 1
    assert event_repository.release_calls == []

    assert session.commit_count == 3
    assert session.rollback_count == 0

    assert error_repository.lookup_calls == [
        {
            "entity_type": "payment_event",
            "entity_id": 70,
            "error_type": CRYPTOBOT_NOTIFICATION_ERROR_TYPE,
        }
    ]
    assert error_repository.create_calls == []


@pytest.mark.asyncio
async def test_unavailable_claim_does_not_send_notification():
    event_repository = FakePaymentEventRepository(claim_result=False)
    service, session, _, error_repository = make_service(
        payment_event_repository=event_repository,
    )
    sent_messages: list[str] = []

    async def send_message(text: str) -> None:
        sent_messages.append(text)

    result = await service.deliver(
        event_id=70,
        order_id=23,
        telegram_id=123456789,
        send_message=send_message,
    )

    assert result.attempted is False
    assert result.delivered is False
    assert result.persisted is False
    assert result.reason == "not_claimed"

    assert sent_messages == []
    assert event_repository.mark_calls == []
    assert event_repository.release_calls == []
    assert error_repository.lookup_calls == []
    assert session.commit_count == 1


@pytest.mark.asyncio
async def test_telegram_failure_releases_claim_and_records_system_error():
    event_repository = FakePaymentEventRepository()
    service, session, _, error_repository = make_service(
        payment_event_repository=event_repository,
    )

    async def send_message(text: str) -> None:
        raise RuntimeError("telegram unavailable")

    result = await service.deliver(
        event_id=70,
        order_id=23,
        telegram_id=123456789,
        send_message=send_message,
    )

    assert result.attempted is True
    assert result.delivered is False
    assert result.persisted is False
    assert result.reason == "send_failed"

    assert len(event_repository.release_calls) == 1
    assert event_repository.mark_calls == []

    assert len(error_repository.create_calls) == 1
    created = error_repository.create_calls[0]
    assert created["entity_type"] == "payment_event"
    assert created["entity_id"] == 70
    assert created["error_type"] == CRYPTOBOT_NOTIFICATION_ERROR_TYPE
    assert "RuntimeError: telegram unavailable" in created["error_message"]
    assert '"phase": "send"' in created["payload"]

    assert session.commit_count == 3
    assert session.rollback_count == 0


@pytest.mark.asyncio
async def test_finalize_failure_keeps_delivery_success_and_records_error():
    event_repository = FakePaymentEventRepository(
        mark_error=RuntimeError("database unavailable"),
    )
    service, session, _, error_repository = make_service(
        payment_event_repository=event_repository,
    )
    sent_messages: list[str] = []

    async def send_message(text: str) -> None:
        sent_messages.append(text)

    result = await service.deliver(
        event_id=70,
        order_id=23,
        telegram_id=123456789,
        send_message=send_message,
    )

    assert result.attempted is True
    assert result.delivered is True
    assert result.persisted is False
    assert result.reason == "finalize_failed"

    assert sent_messages == [CRYPTOBOT_PAYMENT_CONFIRMED_TEXT]
    assert event_repository.release_calls == []

    assert len(error_repository.create_calls) == 1
    created = error_repository.create_calls[0]
    assert '"phase": "finalize"' in created["payload"]

    assert session.commit_count == 2
    assert session.rollback_count == 1


@pytest.mark.asyncio
async def test_successful_retry_resolves_existing_system_error():
    pending_error = SimpleNamespace(id=500)
    error_repository = FakeSystemErrorRepository(
        pending=pending_error,
    )
    service, session, _, _ = make_service(
        system_error_repository=error_repository,
    )

    async def send_message(text: str) -> None:
        return None

    result = await service.deliver(
        event_id=70,
        order_id=23,
        telegram_id=123456789,
        send_message=send_message,
    )

    assert result.persisted is True
    assert error_repository.resolve_calls == [pending_error]
    assert error_repository.create_calls == []
    assert error_repository.update_calls == []
    assert session.commit_count == 3


@pytest.mark.asyncio
async def test_cancellation_during_send_keeps_claim_until_ttl():
    event_repository = FakePaymentEventRepository()
    service, session, _, error_repository = make_service(
        payment_event_repository=event_repository,
    )

    async def send_message(text: str) -> None:
        raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await service.deliver(
            event_id=70,
            order_id=23,
            telegram_id=123456789,
            send_message=send_message,
        )

    assert len(event_repository.claim_calls) == 1
    assert event_repository.mark_calls == []
    assert event_repository.release_calls == []

    assert error_repository.lookup_calls == []
    assert error_repository.create_calls == []
    assert error_repository.update_calls == []
    assert error_repository.resolve_calls == []

    # Only the durable claim was committed. No release or finalization
    # transaction was attempted after cancellation.
    assert session.commit_count == 1
    assert session.rollback_count == 0
