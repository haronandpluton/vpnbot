from __future__ import annotations

import json
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast

import pytest
from sqlalchemy.dialects import postgresql

import app.services.payment_activation_service as activation_module
from app.database.repositories.system_errors import (
    SystemErrorRecordRepository,
)
from app.payment_core.enums.order_status import OrderStatus
from app.payment_core.enums.payment_status import PaymentStatus
from app.services.payment_activation_service import (
    SUBSCRIPTION_ACTIVATION_ERROR_TYPE,
    PaymentActivationService,
)


class FakeSession:
    def __init__(self) -> None:
        self.commit_count = 0
        self.rollback_count = 0
        self.execute_calls = []

    async def commit(self) -> None:
        self.commit_count += 1

    async def rollback(self) -> None:
        self.rollback_count += 1

    async def execute(self, statement):
        self.execute_calls.append(statement)
        return SimpleNamespace(scalar_one_or_none=lambda: None)


class FakePaymentEventService:
    def __init__(self, result) -> None:
        self.result = result

    async def process_confirmed_event(self, **kwargs):
        return self.result


class FailingSubscriptionService:
    def __init__(self, message: str = "vpn mutation failed") -> None:
        self.message = message
        self.calls = []

    async def activate_or_extend_by_order(self, order_id: int):
        self.calls.append(order_id)
        raise RuntimeError(self.message)


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

    async def get_unresolved_by_entity_and_error_type(self, **kwargs):
        self.lookup_calls.append(kwargs)
        return self.pending

    async def create(self, **kwargs):
        if self.fail_create:
            raise RuntimeError("system_errors unavailable")

        self.create_calls.append(kwargs)
        self.pending = SimpleNamespace(
            id=900,
            retry_count=0,
            **kwargs,
        )
        return self.pending

    async def update_pending_failure(self, error, **kwargs):
        self.update_calls.append(
            {
                "error": error,
                **kwargs,
            }
        )
        error.retry_count += 1
        error.entity_type = kwargs["entity_type"]
        error.entity_id = kwargs["entity_id"]
        error.error_message = kwargs["error_message"]
        error.payload = kwargs["payload"]
        return error


def make_context():
    event = SimpleNamespace(id=11)
    payment = SimpleNamespace(
        id=22,
        status=PaymentStatus.CONFIRMED,
    )
    order = SimpleNamespace(
        id=33,
        status=OrderStatus.PAID,
        target_subscription_id=50,
        activated_subscription_id=None,
    )
    return event, payment, order


def make_service(*, repository):
    event, payment, order = make_context()
    session = FakeSession()
    service = PaymentActivationService.__new__(
        PaymentActivationService
    )
    service.session = session
    service.payment_event_service = FakePaymentEventService(
        (event, payment, order)
    )
    service.subscription_service = FailingSubscriptionService()
    return service, session, event, payment, order


@pytest.mark.asyncio
async def test_activation_failure_is_persisted_with_payment_context(
    monkeypatch,
):
    repository = FakeSystemErrorRepository()
    service, session, event, payment, order = make_service(
        repository=repository
    )
    monkeypatch.setattr(
        activation_module,
        "SystemErrorRecordRepository",
        lambda session_arg: repository,
    )

    with pytest.raises(RuntimeError, match="vpn mutation failed"):
        await service.process_confirmed_payment_event_and_activate(
            order_id=order.id,
            amount=Decimal("7.50"),
            provider="cryptobot",
            event_type="invoice_paid",
            external_event_id="cryptobot:123",
            txid="tx-123",
            raw_payload='{"secret": "not persisted"}',
        )

    assert repository.lookup_calls == [
        {
            "entity_type": "payment_event",
            "entity_id": event.id,
            "error_type": SUBSCRIPTION_ACTIVATION_ERROR_TYPE,
        }
    ]
    assert len(repository.create_calls) == 1

    created = repository.create_calls[0]
    payload = json.loads(created["payload"])

    assert created["entity_type"] == "payment_event"
    assert created["entity_id"] == event.id
    assert created["error_type"] == (
        SUBSCRIPTION_ACTIVATION_ERROR_TYPE
    )
    assert created["error_message"] == (
        "RuntimeError: vpn mutation failed"
    )
    assert payload["order_id"] == order.id
    assert payload["payment_event_id"] == event.id
    assert payload["payment_id"] == payment.id
    assert payload["target_subscription_id"] == 50
    assert payload["activated_subscription_id"] is None
    assert payload["provider"] == "cryptobot"
    assert payload["external_event_id"] == "cryptobot:123"
    assert payload["txid"] == "tx-123"
    assert payload["amount"] == "7.50"
    assert payload["has_raw_payload"] is True
    assert "secret" not in created["payload"]
    assert session.rollback_count == 1
    assert session.commit_count == 1


@pytest.mark.asyncio
async def test_repeated_failure_updates_same_unresolved_error(
    monkeypatch,
):
    pending = SimpleNamespace(
        id=900,
        retry_count=0,
        entity_type="payment_event",
        entity_id=11,
        error_message="old",
        payload="{}",
    )
    repository = FakeSystemErrorRepository(pending=pending)
    service, session, _, _, order = make_service(
        repository=repository
    )
    monkeypatch.setattr(
        activation_module,
        "SystemErrorRecordRepository",
        lambda session_arg: repository,
    )

    for _ in range(2):
        with pytest.raises(RuntimeError, match="vpn mutation failed"):
            await service.process_confirmed_payment_event_and_activate(
                order_id=order.id,
                amount=Decimal("4.00"),
                provider="volet_sci",
                event_type="payment_confirmed",
                external_event_id="transfer-1",
            )

    assert repository.create_calls == []
    assert len(repository.update_calls) == 2
    assert pending.retry_count == 2
    assert session.rollback_count == 2
    assert session.commit_count == 2


@pytest.mark.asyncio
async def test_system_error_write_failure_does_not_mask_activation_error(
    monkeypatch,
):
    repository = FakeSystemErrorRepository(fail_create=True)
    service, session, _, _, order = make_service(
        repository=repository
    )
    monkeypatch.setattr(
        activation_module,
        "SystemErrorRecordRepository",
        lambda session_arg: repository,
    )

    with pytest.raises(RuntimeError, match="vpn mutation failed"):
        await service.process_confirmed_payment_event_and_activate(
            order_id=order.id,
            amount=Decimal("4.00"),
            provider="cryptobot",
            event_type="invoice_paid",
        )

    assert session.commit_count == 0
    assert session.rollback_count == 2


@pytest.mark.asyncio
async def test_repository_query_scopes_pending_error_to_entity():
    session = FakeSession()
    repository = SystemErrorRecordRepository(cast(Any, session))

    await repository.get_unresolved_by_entity_and_error_type(
        entity_type="payment_event",
        entity_id=11,
        error_type=SUBSCRIPTION_ACTIVATION_ERROR_TYPE,
    )

    compiled = session.execute_calls[0].compile(
        dialect=postgresql.dialect(),
    )
    sql = str(compiled)
    params = compiled.params

    assert "system_errors.is_resolved IS false" in sql
    assert "system_errors.entity_type =" in sql
    assert "system_errors.entity_id =" in sql
    assert "system_errors.error_type =" in sql
    assert "payment_event" in params.values()
    assert 11 in params.values()
    assert SUBSCRIPTION_ACTIVATION_ERROR_TYPE in params.values()
