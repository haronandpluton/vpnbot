from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.common.enums import CurrencyCode, NetworkCode, TariffCode
from app.database.models import Order, Payment, PaymentEvent
from app.database.repositories.orders import OrderRepository
from app.database.repositories.payment_events import PaymentEventRepository
from app.database.repositories.payments import PaymentRepository
from app.payment_core.enums.order_status import OrderStatus
from app.payment_core.enums.payment_method import PaymentMethod
from app.payment_core.enums.payment_status import PaymentStatus


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
    def __init__(self, *, scalar_value=None, items=None, fail_flush: bool = False) -> None:
        self.scalar_value = scalar_value
        self.items = items or []
        self.fail_flush = fail_flush
        self.execute_calls = []
        self.add_calls = []
        self.flush_count = 0
        self.next_id = 900

    async def execute(self, stmt):
        self.execute_calls.append(stmt)
        return FakeExecuteResult(scalar_value=self.scalar_value, items=self.items)

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


def make_order(*, order_id: int = 23, status: OrderStatus = OrderStatus.WAITING_PAYMENT):
    return SimpleNamespace(
        id=order_id,
        user_id=7,
        status=status,
        paid_at=None,
        activated_at=None,
        failure_reason=None,
    )


def make_payment(*, payment_id: int = 50, status: PaymentStatus = PaymentStatus.NEW):
    return SimpleNamespace(
        id=payment_id,
        order_id=23,
        status=status,
        detected_at=None,
        confirmed_at=None,
    )


def make_event(*, event_id: int = 70):
    return SimpleNamespace(
        id=event_id,
        payment_id=None,
        order_id=23,
        processed=False,
        processing_status=None,
        error_message=None,
        processed_at=None,
    )


@pytest.mark.asyncio
async def test_order_repository_get_by_id_returns_scalar_order():
    order = make_order(order_id=23)
    session = FakeSession(scalar_value=order)
    repository = OrderRepository(session)

    result = await repository.get_by_id(23)

    assert result is order
    assert len(session.execute_calls) == 1


@pytest.mark.asyncio
async def test_order_repository_get_active_waiting_order_by_user_returns_scalar_order():
    order = make_order(order_id=23, status=OrderStatus.WAITING_PAYMENT)
    session = FakeSession(scalar_value=order)
    repository = OrderRepository(session)

    result = await repository.get_active_waiting_order_by_user(
        user_id=7,
        tariff_code=TariffCode.PERIOD_1_MONTH,
        payment_option_id=5,
    )

    assert result is order
    assert len(session.execute_calls) == 1


@pytest.mark.asyncio
async def test_order_repository_create_adds_waiting_payment_order_and_flushes():
    expires_at = datetime(2026, 7, 5, 12, 0, tzinfo=UTC)
    session = FakeSession()
    repository = OrderRepository(session)

    order = await repository.create(
        user_id=7,
        tariff_code=TariffCode.PERIOD_2_MONTHS,
        device_limit=1,
        duration_days=66,
        price_usd=Decimal("7.50"),
        payment_method=PaymentMethod.CRYPTO,
        payment_option_id=5,
        expected_amount=Decimal("7.50"),
        expected_currency=CurrencyCode.USDT,
        expected_network=NetworkCode.TRC20,
        destination_address="wallet-to",
        destination_memo_tag="memo-1",
        expires_at=expires_at,
        source="bot",
        comment="test order",
    )

    assert isinstance(order, Order)
    assert order.id == 900
    assert order.user_id == 7
    assert order.status == OrderStatus.WAITING_PAYMENT
    assert order.tariff_code == TariffCode.PERIOD_2_MONTHS
    assert order.device_limit == 1
    assert order.duration_days == 66
    assert order.price_usd == Decimal("7.50")
    assert order.payment_method == PaymentMethod.CRYPTO
    assert order.payment_option_id == 5
    assert order.expected_amount == Decimal("7.50")
    assert order.expected_currency == CurrencyCode.USDT
    assert order.expected_network == NetworkCode.TRC20
    assert order.destination_address == "wallet-to"
    assert order.destination_memo_tag == "memo-1"
    assert order.expires_at == expires_at
    assert order.source == "bot"
    assert order.comment == "test order"
    assert session.add_calls == [order]
    assert session.flush_count == 1


@pytest.mark.asyncio
async def test_order_repository_create_propagates_flush_error_without_fake_success():
    session = FakeSession(fail_flush=True)
    repository = OrderRepository(session)

    with pytest.raises(RuntimeError, match="flush failed"):
        await repository.create(
            user_id=7,
            tariff_code=TariffCode.PERIOD_1_MONTH,
            device_limit=1,
            duration_days=33,
            price_usd=Decimal("4.00"),
            payment_method=PaymentMethod.CRYPTO,
            payment_option_id=5,
            expected_amount=None,
            expected_currency=CurrencyCode.USDT,
            expected_network=NetworkCode.TRC20,
            destination_address=None,
            destination_memo_tag=None,
            expires_at=datetime.now(UTC) + timedelta(minutes=15),
        )

    assert len(session.add_calls) == 1
    assert session.flush_count == 1


@pytest.mark.asyncio
async def test_order_repository_mark_paid_sets_status_paid_and_paid_at():
    order = make_order(status=OrderStatus.WAITING_PAYMENT)
    paid_at = datetime(2026, 7, 5, 12, 0, tzinfo=UTC)
    session = FakeSession()
    repository = OrderRepository(session)

    result = await repository.mark_paid(order, paid_at)

    assert result is order
    assert order.status == OrderStatus.PAID
    assert order.paid_at == paid_at
    assert session.flush_count == 1


@pytest.mark.asyncio
async def test_order_repository_mark_activated_sets_status_activated_and_activated_at():
    order = make_order(status=OrderStatus.PAID)
    activated_at = datetime(2026, 7, 5, 12, 30, tzinfo=UTC)
    session = FakeSession()
    repository = OrderRepository(session)

    result = await repository.mark_activated(order, activated_at)

    assert result is order
    assert order.status == OrderStatus.ACTIVATED
    assert order.activated_at == activated_at
    assert session.flush_count == 1


@pytest.mark.asyncio
async def test_order_repository_mark_expired_sets_status_expired():
    order = make_order(status=OrderStatus.WAITING_PAYMENT)
    session = FakeSession()
    repository = OrderRepository(session)

    result = await repository.mark_expired(order)

    assert result is order
    assert order.status == OrderStatus.EXPIRED
    assert session.flush_count == 1


@pytest.mark.asyncio
async def test_order_repository_mark_failed_sets_status_failed_and_reason():
    order = make_order(status=OrderStatus.PAID)
    session = FakeSession()
    repository = OrderRepository(session)

    result = await repository.mark_failed(order, failure_reason="vpn_create_failed")

    assert result is order
    assert order.status == OrderStatus.FAILED
    assert order.failure_reason == "vpn_create_failed"
    assert session.flush_count == 1


@pytest.mark.asyncio
async def test_order_repository_mark_cancelled_sets_status_cancelled_and_reason():
    order = make_order(status=OrderStatus.WAITING_PAYMENT)
    session = FakeSession()
    repository = OrderRepository(session)

    result = await repository.mark_cancelled(order, failure_reason="user_cancelled")

    assert result is order
    assert order.status == OrderStatus.CANCELLED
    assert order.failure_reason == "user_cancelled"
    assert session.flush_count == 1


@pytest.mark.asyncio
async def test_payment_repository_get_by_id_returns_scalar_payment():
    payment = make_payment(payment_id=50)
    session = FakeSession(scalar_value=payment)
    repository = PaymentRepository(session)

    result = await repository.get_by_id(50)

    assert result is payment
    assert len(session.execute_calls) == 1


@pytest.mark.asyncio
async def test_payment_repository_get_by_txid_returns_scalar_payment():
    payment = make_payment(payment_id=50)
    session = FakeSession(scalar_value=payment)
    repository = PaymentRepository(session)

    result = await repository.get_by_txid("tx-1")

    assert result is payment
    assert len(session.execute_calls) == 1


@pytest.mark.asyncio
async def test_payment_repository_get_by_provider_payment_id_returns_scalar_payment():
    payment = make_payment(payment_id=50)
    session = FakeSession(scalar_value=payment)
    repository = PaymentRepository(session)

    result = await repository.get_by_provider_payment_id("provider-1")

    assert result is payment
    assert len(session.execute_calls) == 1


@pytest.mark.asyncio
async def test_payment_repository_get_by_order_id_returns_scalar_list():
    payments = [make_payment(payment_id=1), make_payment(payment_id=2)]
    session = FakeSession(items=payments)
    repository = PaymentRepository(session)

    result = await repository.get_by_order_id(23)

    assert result == payments
    assert len(session.execute_calls) == 1


@pytest.mark.asyncio
async def test_payment_repository_create_adds_payment_and_flushes():
    detected_at = datetime(2026, 7, 5, 12, 0, tzinfo=UTC)
    session = FakeSession()
    repository = PaymentRepository(session)

    payment = await repository.create(
        order_id=23,
        user_id=7,
        payment_method=PaymentMethod.CRYPTO,
        payment_option_id=5,
        amount=Decimal("4.00"),
        currency=CurrencyCode.USDT,
        network=NetworkCode.TRC20,
        txid="tx-1",
        provider_payment_id="provider-1",
        address_from="wallet-from",
        address_to="wallet-to",
        memo_tag="memo-1",
        confirmations=12,
        detected_at=detected_at,
        raw_payload='{"raw":true}',
        status=PaymentStatus.DETECTED,
    )

    assert isinstance(payment, Payment)
    assert payment.id == 900
    assert payment.order_id == 23
    assert payment.user_id == 7
    assert payment.status == PaymentStatus.DETECTED
    assert payment.payment_method == PaymentMethod.CRYPTO
    assert payment.payment_option_id == 5
    assert payment.txid == "tx-1"
    assert payment.provider_payment_id == "provider-1"
    assert payment.amount == Decimal("4.00")
    assert payment.currency == CurrencyCode.USDT
    assert payment.network == NetworkCode.TRC20
    assert payment.address_from == "wallet-from"
    assert payment.address_to == "wallet-to"
    assert payment.memo_tag == "memo-1"
    assert payment.confirmations == 12
    assert payment.detected_at == detected_at
    assert payment.raw_payload == '{"raw":true}'
    assert session.add_calls == [payment]
    assert session.flush_count == 1


@pytest.mark.asyncio
async def test_payment_repository_create_propagates_flush_error_without_fake_success():
    session = FakeSession(fail_flush=True)
    repository = PaymentRepository(session)

    with pytest.raises(RuntimeError, match="flush failed"):
        await repository.create(
            order_id=23,
            user_id=7,
            payment_method=PaymentMethod.CRYPTO,
            amount=Decimal("4.00"),
        )

    assert len(session.add_calls) == 1
    assert session.flush_count == 1


@pytest.mark.asyncio
async def test_payment_repository_mark_detected_with_explicit_timestamp():
    payment = make_payment(status=PaymentStatus.NEW)
    detected_at = datetime(2026, 7, 5, 12, 0, tzinfo=UTC)
    session = FakeSession()
    repository = PaymentRepository(session)

    result = await repository.mark_detected(payment, detected_at=detected_at)

    assert result is payment
    assert payment.status == PaymentStatus.DETECTED
    assert payment.detected_at == detected_at
    assert session.flush_count == 1


@pytest.mark.asyncio
async def test_payment_repository_mark_detected_uses_current_utc_time_when_not_provided():
    payment = make_payment(status=PaymentStatus.NEW)
    session = FakeSession()
    repository = PaymentRepository(session)

    before_call = datetime.now(UTC)
    result = await repository.mark_detected(payment)
    after_call = datetime.now(UTC)

    assert result is payment
    assert payment.status == PaymentStatus.DETECTED
    assert payment.detected_at >= before_call
    assert payment.detected_at <= after_call
    assert session.flush_count == 1


@pytest.mark.asyncio
async def test_payment_repository_mark_confirmed_with_explicit_timestamp():
    payment = make_payment(status=PaymentStatus.DETECTED)
    confirmed_at = datetime(2026, 7, 5, 12, 30, tzinfo=UTC)
    session = FakeSession()
    repository = PaymentRepository(session)

    result = await repository.mark_confirmed(payment, confirmed_at=confirmed_at)

    assert result is payment
    assert payment.status == PaymentStatus.CONFIRMED
    assert payment.confirmed_at == confirmed_at
    assert session.flush_count == 1


@pytest.mark.asyncio
async def test_payment_repository_mark_confirmed_uses_current_utc_time_when_not_provided():
    payment = make_payment(status=PaymentStatus.DETECTED)
    session = FakeSession()
    repository = PaymentRepository(session)

    before_call = datetime.now(UTC)
    result = await repository.mark_confirmed(payment)
    after_call = datetime.now(UTC)

    assert result is payment
    assert payment.status == PaymentStatus.CONFIRMED
    assert payment.confirmed_at >= before_call
    assert payment.confirmed_at <= after_call
    assert session.flush_count == 1


@pytest.mark.asyncio
async def test_payment_repository_mark_invalid_sets_status_invalid():
    payment = make_payment(status=PaymentStatus.DETECTED)
    session = FakeSession()
    repository = PaymentRepository(session)

    result = await repository.mark_invalid(payment)

    assert result is payment
    assert payment.status == PaymentStatus.INVALID
    assert session.flush_count == 1


@pytest.mark.asyncio
async def test_payment_repository_mark_duplicate_sets_status_duplicate():
    payment = make_payment(status=PaymentStatus.DETECTED)
    session = FakeSession()
    repository = PaymentRepository(session)

    result = await repository.mark_duplicate(payment)

    assert result is payment
    assert payment.status == PaymentStatus.DUPLICATE
    assert session.flush_count == 1


@pytest.mark.asyncio
async def test_payment_repository_mark_expired_sets_status_expired():
    payment = make_payment(status=PaymentStatus.NEW)
    session = FakeSession()
    repository = PaymentRepository(session)

    result = await repository.mark_expired(payment)

    assert result is payment
    assert payment.status == PaymentStatus.EXPIRED
    assert session.flush_count == 1


@pytest.mark.asyncio
async def test_payment_repository_mark_error_sets_status_error():
    payment = make_payment(status=PaymentStatus.NEW)
    session = FakeSession()
    repository = PaymentRepository(session)

    result = await repository.mark_error(payment)

    assert result is payment
    assert payment.status == PaymentStatus.ERROR
    assert session.flush_count == 1


@pytest.mark.asyncio
async def test_payment_event_repository_get_by_id_returns_scalar_event():
    event = make_event(event_id=70)
    session = FakeSession(scalar_value=event)
    repository = PaymentEventRepository(session)

    result = await repository.get_by_id(70)

    assert result is event
    assert len(session.execute_calls) == 1


@pytest.mark.asyncio
async def test_payment_event_repository_get_by_external_event_id_returns_scalar_event():
    event = make_event(event_id=70)
    session = FakeSession(scalar_value=event)
    repository = PaymentEventRepository(session)

    result = await repository.get_by_external_event_id("external-1")

    assert result is event
    assert len(session.execute_calls) == 1

@pytest.mark.asyncio
async def test_payment_event_repository_get_by_provider_and_external_event_id():
    event = make_event(event_id=70)
    session = FakeSession(scalar_value=event)
    repository = PaymentEventRepository(session)

    result = await repository.get_by_provider_and_external_event_id(
        provider="telegram_stars",
        external_event_id="charge-123",
    )

    assert result is event
    assert len(session.execute_calls) == 1

@pytest.mark.asyncio
async def test_payment_event_repository_create_adds_event_and_flushes():
    session = FakeSession()
    repository = PaymentEventRepository(session)

    event = await repository.create(
        payment_id=50,
        order_id=23,
        event_type="payment_detected",
        provider="volet",
        external_event_id="external-1",
        txid="tx-1",
        payload='{"raw":true}',
    )

    assert isinstance(event, PaymentEvent)
    assert event.id == 900
    assert event.payment_id == 50
    assert event.order_id == 23
    assert event.event_type == "payment_detected"
    assert event.provider == "volet"
    assert event.external_event_id == "external-1"
    assert event.txid == "tx-1"
    assert event.payload == '{"raw":true}'
    assert session.add_calls == [event]
    assert session.flush_count == 1


@pytest.mark.asyncio
async def test_payment_event_repository_get_unprocessed_returns_scalar_list():
    events = [make_event(event_id=1), make_event(event_id=2)]
    session = FakeSession(items=events)
    repository = PaymentEventRepository(session)

    result = await repository.get_unprocessed()

    assert result == events
    assert len(session.execute_calls) == 1


@pytest.mark.asyncio
async def test_payment_event_repository_attach_payment_sets_payment_id_and_flushes():
    event = make_event(event_id=70)
    session = FakeSession()
    repository = PaymentEventRepository(session)

    result = await repository.attach_payment(event, payment_id=50)

    assert result is event
    assert event.payment_id == 50
    assert session.flush_count == 1


@pytest.mark.asyncio
async def test_payment_event_repository_mark_processed_sets_status_error_and_processed_timestamp():
    event = make_event(event_id=70)
    session = FakeSession()
    repository = PaymentEventRepository(session)

    before_call = datetime.now(UTC)
    result = await repository.mark_processed(
        event,
        processing_status="invalid",
        error_message="wrong_network",
    )
    after_call = datetime.now(UTC)

    assert result is event
    assert event.processed is True
    assert event.processing_status == "invalid"
    assert event.error_message == "wrong_network"
    assert event.processed_at >= before_call
    assert event.processed_at <= after_call
    assert session.flush_count == 1


@pytest.mark.asyncio
async def test_payment_event_repository_mark_processed_allows_empty_processing_status_and_error_message():
    event = make_event(event_id=70)
    session = FakeSession()
    repository = PaymentEventRepository(session)

    result = await repository.mark_processed(event)

    assert result is event
    assert event.processed is True
    assert event.processing_status is None
    assert event.error_message is None
    assert event.processed_at is not None
    assert session.flush_count == 1