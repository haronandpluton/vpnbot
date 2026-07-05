from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.common.enums import CurrencyCode, NetworkCode
from app.payment_core.enums.order_status import OrderStatus
from app.payment_core.enums.payment_status import PaymentStatus
from app.services.payment_event_service import PaymentEventService


class FakeSession:
    def __init__(self) -> None:
        self.commit_count = 0
        self.rollback_count = 0
        self.flush_count = 0

    async def commit(self) -> None:
        self.commit_count += 1

    async def rollback(self) -> None:
        self.rollback_count += 1

    async def flush(self) -> None:
        self.flush_count += 1


class FakeOrderRepository:
    def __init__(self, orders: dict[int, SimpleNamespace]) -> None:
        self.orders = orders
        self.requested_ids: list[int] = []

    async def get_by_id(self, order_id: int):
        self.requested_ids.append(order_id)
        return self.orders.get(order_id)


class FakePaymentRepository:
    def __init__(self, payments: dict[int, SimpleNamespace]) -> None:
        self.payments = payments
        self.requested_ids: list[int] = []

    async def get_by_id(self, payment_id: int):
        self.requested_ids.append(payment_id)
        return self.payments.get(payment_id)


class FakePaymentEventRepository:
    def __init__(
        self,
        *,
        events_by_external_id: dict[str, SimpleNamespace] | None = None,
        fail_on_create: bool = False,
    ) -> None:
        self.events_by_external_id = events_by_external_id or {}
        self.fail_on_create = fail_on_create
        self.created_events: list[SimpleNamespace] = []
        self.get_external_calls: list[str] = []
        self.attach_calls: list[tuple[int, int]] = []
        self.mark_processed_calls: list[tuple[int, str | None, str | None]] = []
        self.next_id = 100

    async def get_by_external_event_id(self, external_event_id: str):
        self.get_external_calls.append(external_event_id)
        return self.events_by_external_id.get(external_event_id)

    async def create(
        self,
        payment_id: int | None,
        order_id: int | None,
        event_type: str,
        provider: str,
        external_event_id: str | None = None,
        txid: str | None = None,
        payload: str | None = None,
    ):
        if self.fail_on_create:
            raise RuntimeError("event create failed")

        event = SimpleNamespace(
            id=self.next_id,
            payment_id=payment_id,
            order_id=order_id,
            event_type=event_type,
            provider=provider,
            external_event_id=external_event_id,
            txid=txid,
            payload=payload,
            processed=False,
            processing_status=None,
            error_message=None,
        )
        self.next_id += 1
        self.created_events.append(event)

        if external_event_id is not None:
            self.events_by_external_id[external_event_id] = event

        return event

    async def attach_payment(self, event, payment_id: int):
        event.payment_id = payment_id
        self.attach_calls.append((event.id, payment_id))
        return event

    async def mark_processed(
        self,
        event,
        processing_status: str | None = None,
        error_message: str | None = None,
    ):
        event.processed = True
        event.processing_status = processing_status
        event.error_message = error_message
        self.mark_processed_calls.append((event.id, processing_status, error_message))
        return event


class FakePaymentService:
    def __init__(
        self,
        *,
        order_repository: FakeOrderRepository,
        existing_payment_by_txid: dict[str, SimpleNamespace] | None = None,
    ) -> None:
        self.order_repository = order_repository
        self.existing_payment_by_txid = existing_payment_by_txid or {}
        self.create_calls: list[dict] = []
        self.created_payments: list[SimpleNamespace] = []
        self.mark_detected_calls: list[int] = []
        self.confirm_calls: list[int] = []
        self.next_id = 200

    async def _create_payment_for_order(
        self,
        order_id: int,
        amount: Decimal,
        txid: str | None = None,
        provider_payment_id: str | None = None,
        address_from: str | None = None,
        address_to: str | None = None,
        memo_tag: str | None = None,
        confirmations: int | None = None,
        raw_payload: str | None = None,
        initial_status: PaymentStatus = PaymentStatus.NEW,
    ):
        self.create_calls.append(
            {
                "order_id": order_id,
                "amount": amount,
                "txid": txid,
                "provider_payment_id": provider_payment_id,
                "address_from": address_from,
                "address_to": address_to,
                "memo_tag": memo_tag,
                "confirmations": confirmations,
                "raw_payload": raw_payload,
                "initial_status": initial_status,
            }
        )

        if txid is not None and txid in self.existing_payment_by_txid:
            return self.existing_payment_by_txid[txid]

        order = await self.order_repository.get_by_id(order_id)
        if order is None:
            raise ValueError(f"Order not found: {order_id}")

        payment = SimpleNamespace(
            id=self.next_id,
            order_id=order_id,
            user_id=order.user_id,
            status=initial_status,
            amount=amount,
            currency=order.expected_currency,
            network=order.expected_network,
            txid=txid,
            provider_payment_id=provider_payment_id,
            address_from=address_from,
            address_to=address_to,
            memo_tag=memo_tag,
            confirmations=confirmations,
            raw_payload=raw_payload,
            detected_at=None,
            confirmed_at=None,
        )
        self.next_id += 1
        self.created_payments.append(payment)
        return payment

    async def _mark_payment_detected(self, payment_id: int):
        self.mark_detected_calls.append(payment_id)
        payment = self._find_payment(payment_id)

        if payment.status not in {
            PaymentStatus.DETECTED,
            PaymentStatus.CONFIRMED,
            PaymentStatus.INVALID,
            PaymentStatus.DUPLICATE,
            PaymentStatus.EXPIRED,
        }:
            payment.status = PaymentStatus.DETECTED

        return payment

    async def _confirm_payment(self, payment_id: int):
        self.confirm_calls.append(payment_id)
        payment = self._find_payment(payment_id)
        order = await self.order_repository.get_by_id(payment.order_id)

        if payment.status not in {
            PaymentStatus.CONFIRMED,
            PaymentStatus.INVALID,
            PaymentStatus.DUPLICATE,
            PaymentStatus.EXPIRED,
        }:
            payment.status = PaymentStatus.CONFIRMED
            payment.confirmed_at = datetime.now(timezone.utc)

        if payment.status == PaymentStatus.CONFIRMED and order.status == OrderStatus.WAITING_PAYMENT:
            order.status = OrderStatus.PAID
            order.paid_at = payment.confirmed_at

        return payment, order

    def _find_payment(self, payment_id: int):
        for payment in self.created_payments:
            if payment.id == payment_id:
                return payment

        for payment in self.existing_payment_by_txid.values():
            if payment.id == payment_id:
                return payment

        raise ValueError(f"Payment not found: {payment_id}")


def make_order(
    *,
    order_id: int = 23,
    status: OrderStatus = OrderStatus.WAITING_PAYMENT,
    expires_at=None,
):
    return SimpleNamespace(
        id=order_id,
        user_id=7,
        status=status,
        expected_currency=CurrencyCode.USDT,
        expected_network=NetworkCode.TRC20,
        expires_at=expires_at or datetime.now(timezone.utc) + timedelta(minutes=15),
        paid_at=None,
    )


def make_service(
    *,
    order: SimpleNamespace | None = None,
    existing_events_by_external_id: dict[str, SimpleNamespace] | None = None,
    payments_by_id: dict[int, SimpleNamespace] | None = None,
    existing_payment_by_txid: dict[str, SimpleNamespace] | None = None,
    fail_on_event_create: bool = False,
):
    session = FakeSession()
    orders = {} if order is None else {order.id: order}
    order_repository = FakeOrderRepository(orders)
    payment_repository = FakePaymentRepository(payments_by_id or {})
    event_repository = FakePaymentEventRepository(
        events_by_external_id=existing_events_by_external_id,
        fail_on_create=fail_on_event_create,
    )
    payment_service = FakePaymentService(
        order_repository=order_repository,
        existing_payment_by_txid=existing_payment_by_txid,
    )

    service = PaymentEventService.__new__(PaymentEventService)
    service.session = session
    service.order_repository = order_repository
    service.payment_repository = payment_repository
    service.payment_event_repository = event_repository
    service.payment_service = payment_service
    return service


@pytest.mark.asyncio
async def test_process_confirmed_event_creates_event_confirms_payment_and_marks_order_paid():
    order = make_order(order_id=23, status=OrderStatus.WAITING_PAYMENT)
    service = make_service(order=order)

    event, payment, paid_order = await service.process_confirmed_event(
        order_id=23,
        amount=Decimal("4.00"),
        provider="cryptobot",
        event_type="invoice_paid",
        external_event_id="cryptobot:55822653",
        txid="tx-1",
        address_from="payer",
        address_to="merchant",
        memo_tag="memo",
        confirmations=3,
        raw_payload='{"status": "paid"}',
    )

    assert event.processed is True
    assert event.processing_status == "confirmed"
    assert event.payment_id == payment.id
    assert payment.status == PaymentStatus.CONFIRMED
    assert payment.txid == "tx-1"
    assert payment.provider_payment_id == "cryptobot:55822653"
    assert paid_order is order
    assert order.status == OrderStatus.PAID
    assert service.payment_event_repository.attach_calls == [(event.id, payment.id)]
    assert service.payment_event_repository.mark_processed_calls == [
        (event.id, "confirmed", None)
    ]
    assert service.session.commit_count == 1
    assert service.session.rollback_count == 0


@pytest.mark.asyncio
async def test_existing_external_event_returns_existing_context_without_creating_duplicate():
    existing_event = SimpleNamespace(
        id=10,
        payment_id=20,
        order_id=23,
    )
    existing_payment = SimpleNamespace(id=20, status=PaymentStatus.CONFIRMED)
    order = make_order(order_id=23, status=OrderStatus.PAID)
    service = make_service(
        order=order,
        existing_events_by_external_id={"cryptobot:55822653": existing_event},
        payments_by_id={20: existing_payment},
    )

    result = await service.process_confirmed_event(
        order_id=23,
        amount=Decimal("4.00"),
        provider="cryptobot",
        event_type="invoice_paid",
        external_event_id="cryptobot:55822653",
    )

    assert result == (existing_event, existing_payment, order)
    assert service.payment_event_repository.created_events == []
    assert service.payment_service.create_calls == []
    assert service.payment_service.confirm_calls == []
    assert service.session.commit_count == 1
    assert service.session.rollback_count == 0


@pytest.mark.asyncio
async def test_duplicate_txid_reuses_existing_payment_without_creating_new_payment():
    order = make_order(order_id=23, status=OrderStatus.WAITING_PAYMENT)
    existing_payment = SimpleNamespace(
        id=55,
        order_id=23,
        status=PaymentStatus.NEW,
        txid="same-tx",
        confirmed_at=None,
    )
    service = make_service(
        order=order,
        existing_payment_by_txid={"same-tx": existing_payment},
    )

    event, payment, paid_order = await service.process_confirmed_event(
        order_id=23,
        amount=Decimal("4.00"),
        provider="volet",
        event_type="tx_confirmed",
        external_event_id=None,
        txid="same-tx",
    )

    assert payment is existing_payment
    assert service.payment_service.created_payments == []
    assert event.payment_id == existing_payment.id
    assert payment.status == PaymentStatus.CONFIRMED
    assert paid_order.status == OrderStatus.PAID
    assert service.session.commit_count == 1


@pytest.mark.asyncio
async def test_process_detected_event_marks_payment_detected_but_does_not_mark_order_paid():
    order = make_order(order_id=23, status=OrderStatus.WAITING_PAYMENT)
    service = make_service(order=order)

    event, payment, result_order = await service.process_detected_event(
        order_id=23,
        amount=Decimal("4.00"),
        provider="volet",
        event_type="tx_detected",
        external_event_id="event-detected-1",
        txid="tx-detected-1",
    )

    assert event.processing_status == "detected"
    assert payment.status == PaymentStatus.DETECTED
    assert result_order is order
    assert order.status == OrderStatus.WAITING_PAYMENT
    assert service.payment_service.confirm_calls == []
    assert service.session.commit_count == 1


@pytest.mark.asyncio
async def test_process_invalid_event_creates_invalid_payment_and_keeps_order_waiting():
    order = make_order(order_id=23, status=OrderStatus.WAITING_PAYMENT)
    service = make_service(order=order)

    event, payment, result_order = await service.process_invalid_event(
        order_id=23,
        amount=Decimal("3.00"),
        currency="USDT",
        network="ERC20",
        provider="volet",
        event_type="payment_invalid",
        reason="wrong_network",
        external_event_id="invalid-event-1",
        txid="bad-tx-1",
        raw_payload='{"reason": "wrong_network"}',
    )

    assert event.processed is True
    assert event.processing_status == "invalid"
    assert event.error_message == "wrong_network"
    assert payment.status == PaymentStatus.INVALID
    assert payment.currency == "USDT"
    assert payment.network == "ERC20"
    assert result_order is order
    assert order.status == OrderStatus.WAITING_PAYMENT
    assert service.payment_service.mark_detected_calls == []
    assert service.payment_service.confirm_calls == []
    assert service.session.commit_count == 1


@pytest.mark.asyncio
async def test_confirmed_event_for_expired_order_is_saved_as_late_payment_without_activation_context():
    order = make_order(order_id=23, status=OrderStatus.WAITING_PAYMENT)
    order.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    service = make_service(order=order)

    event, payment, result_order = await service.process_confirmed_event(
        order_id=23,
        amount=Decimal("4.00"),
        provider="volet",
        event_type="tx_confirmed",
        external_event_id="late-event-1",
        txid="late-tx-1",
    )

    assert order.status == OrderStatus.EXPIRED
    assert payment.status == PaymentStatus.EXPIRED
    assert event.processed is True
    assert event.processing_status == "expired"
    assert event.error_message == "Late payment for expired order"
    assert result_order is None
    assert service.payment_service.mark_detected_calls == []
    assert service.payment_service.confirm_calls == []
    assert service.session.commit_count == 1


@pytest.mark.asyncio
async def test_confirmed_event_for_order_already_expired_status_is_saved_as_late_payment():
    order = make_order(order_id=23, status=OrderStatus.EXPIRED)
    service = make_service(order=order)

    event, payment, result_order = await service.process_confirmed_event(
        order_id=23,
        amount=Decimal("4.00"),
        provider="volet",
        event_type="tx_confirmed",
        external_event_id="late-event-2",
        txid="late-tx-2",
    )

    assert order.status == OrderStatus.EXPIRED
    assert payment.status == PaymentStatus.EXPIRED
    assert event.processing_status == "expired"
    assert result_order is None
    assert service.session.commit_count == 1


@pytest.mark.asyncio
async def test_detected_event_with_existing_external_id_returns_existing_context():
    existing_event = SimpleNamespace(
        id=11,
        payment_id=21,
        order_id=23,
    )
    existing_payment = SimpleNamespace(id=21, status=PaymentStatus.DETECTED)
    order = make_order(order_id=23, status=OrderStatus.WAITING_PAYMENT)
    service = make_service(
        order=order,
        existing_events_by_external_id={"event-detected-1": existing_event},
        payments_by_id={21: existing_payment},
    )

    result = await service.process_detected_event(
        order_id=23,
        amount=Decimal("4.00"),
        provider="volet",
        event_type="tx_detected",
        external_event_id="event-detected-1",
    )

    assert result == (existing_event, existing_payment, order)
    assert service.payment_event_repository.created_events == []
    assert service.payment_service.create_calls == []
    assert service.session.commit_count == 1


@pytest.mark.asyncio
async def test_missing_order_rolls_back_and_raises_value_error():
    service = make_service(order=None)

    with pytest.raises(ValueError, match="Order not found: 404"):
        await service.process_confirmed_event(
            order_id=404,
            amount=Decimal("4.00"),
            provider="volet",
            event_type="tx_confirmed",
            external_event_id="missing-order-event",
        )

    assert service.session.commit_count == 0
    assert service.session.rollback_count == 1


@pytest.mark.asyncio
async def test_event_create_failure_rolls_back_and_does_not_create_payment():
    order = make_order(order_id=23, status=OrderStatus.WAITING_PAYMENT)
    service = make_service(order=order, fail_on_event_create=True)

    with pytest.raises(RuntimeError, match="event create failed"):
        await service.process_confirmed_event(
            order_id=23,
            amount=Decimal("4.00"),
            provider="volet",
            event_type="tx_confirmed",
            external_event_id="event-fail",
        )

    assert service.payment_service.create_calls == []
    assert service.session.commit_count == 0
    assert service.session.rollback_count == 1
