from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.payment_core.enums.order_status import OrderStatus
from app.payment_core.enums.payment_status import PaymentStatus
from app.services.payment_check_service import PaymentCheckService


def make_order(
    *,
    order_id: int = 23,
    status: OrderStatus = OrderStatus.WAITING_PAYMENT,
    expires_at=None,
    failure_reason: str | None = None,
):
    return SimpleNamespace(
        id=order_id,
        status=status,
        expires_at=expires_at
        if expires_at is not None
        else datetime.now(timezone.utc) + timedelta(minutes=15),
        failure_reason=failure_reason,
    )


def make_payment(
    *,
    payment_id: int = 50,
    status: PaymentStatus = PaymentStatus.CONFIRMED,
):
    return SimpleNamespace(
        id=payment_id,
        status=status,
    )


def make_event(
    *,
    event_id: int = 70,
    processing_status: str | None = "confirmed",
    error_message: str | None = None,
):
    return SimpleNamespace(
        id=event_id,
        processing_status=processing_status,
        error_message=error_message,
    )


def make_subscription(*, subscription_id: int = 90):
    return SimpleNamespace(id=subscription_id)


def make_service(
    *,
    order,
    payment=None,
    event=None,
    subscription=None,
):
    service = PaymentCheckService.__new__(PaymentCheckService)
    service.session = SimpleNamespace()
    service._get_order = lambda order_id: _return_by_order_id(order, order_id)
    service._get_latest_payment = lambda order_id: _return_by_order_id(payment, order_id)
    service._get_latest_event = lambda order_id: _return_by_order_id(event, order_id)
    service._get_subscription = lambda order_id: _return_by_order_id(subscription, order_id)
    return service


async def _return_by_order_id(obj, order_id: int):
    return obj


@pytest.mark.asyncio
async def test_missing_order_raises_value_error():
    service = make_service(order=None)

    with pytest.raises(ValueError, match="Order not found: 404"):
        await service.check_order_payment(404)


@pytest.mark.asyncio
async def test_activated_order_returns_activated_with_related_context():
    order = make_order(order_id=23, status=OrderStatus.ACTIVATED)
    payment = make_payment(payment_id=51, status=PaymentStatus.CONFIRMED)
    event = make_event(event_id=71, processing_status="confirmed")
    subscription = make_subscription(subscription_id=91)
    service = make_service(
        order=order,
        payment=payment,
        event=event,
        subscription=subscription,
    )

    result = await service.check_order_payment(23)

    assert result.status == "activated"
    assert result.order_id == 23
    assert result.payment_id == 51
    assert result.payment_status == "confirmed"
    assert result.event_id == 71
    assert result.event_status == "confirmed"
    assert result.subscription_id == 91
    assert result.error_message is None
    assert result.message == "Payment confirmed and subscription activated."


@pytest.mark.asyncio
async def test_paid_order_returns_paid_waiting_activation():
    order = make_order(order_id=23, status=OrderStatus.PAID)
    payment = make_payment(payment_id=52, status=PaymentStatus.CONFIRMED)
    event = make_event(event_id=72, processing_status="confirmed")
    service = make_service(
        order=order,
        payment=payment,
        event=event,
        subscription=None,
    )

    result = await service.check_order_payment(23)

    assert result.status == "paid_waiting_activation"
    assert result.order_id == 23
    assert result.payment_id == 52
    assert result.payment_status == "confirmed"
    assert result.event_id == 72
    assert result.event_status == "confirmed"
    assert result.subscription_id is None
    assert result.message == "Payment confirmed, activation is still pending."


@pytest.mark.asyncio
async def test_failed_order_returns_activation_failed_with_failure_reason():
    order = make_order(
        order_id=23,
        status=OrderStatus.FAILED,
        failure_reason="vpn_create_failed",
    )
    payment = make_payment(payment_id=53, status=PaymentStatus.CONFIRMED)
    event = make_event(event_id=73, processing_status="error")
    subscription = make_subscription(subscription_id=93)
    service = make_service(
        order=order,
        payment=payment,
        event=event,
        subscription=subscription,
    )

    result = await service.check_order_payment(23)

    assert result.status == "activation_failed"
    assert result.order_id == 23
    assert result.payment_id == 53
    assert result.payment_status == "confirmed"
    assert result.event_id == 73
    assert result.event_status == "error"
    assert result.error_message == "vpn_create_failed"
    assert result.subscription_id == 93
    assert result.message == "Payment or activation requires manual recovery."


@pytest.mark.asyncio
async def test_expired_order_returns_expired_with_event_error_message():
    order = make_order(order_id=23, status=OrderStatus.EXPIRED)
    payment = make_payment(payment_id=54, status=PaymentStatus.EXPIRED)
    event = make_event(
        event_id=74,
        processing_status="expired",
        error_message="Late payment for expired order",
    )
    service = make_service(
        order=order,
        payment=payment,
        event=event,
    )

    result = await service.check_order_payment(23)

    assert result.status == "expired"
    assert result.order_id == 23
    assert result.payment_id == 54
    assert result.payment_status == "expired"
    assert result.event_id == 74
    assert result.event_status == "expired"
    assert result.error_message == "Late payment for expired order"
    assert result.subscription_id is None
    assert result.message == "Order expired."


@pytest.mark.asyncio
async def test_waiting_order_with_invalid_payment_returns_invalid_payment():
    order = make_order(order_id=23, status=OrderStatus.WAITING_PAYMENT)
    payment = make_payment(payment_id=55, status=PaymentStatus.INVALID)
    event = make_event(
        event_id=75,
        processing_status="invalid",
        error_message="wrong_network",
    )
    service = make_service(
        order=order,
        payment=payment,
        event=event,
    )

    result = await service.check_order_payment(23)

    assert result.status == "invalid_payment"
    assert result.order_id == 23
    assert result.payment_id == 55
    assert result.payment_status == "invalid"
    assert result.event_id == 75
    assert result.event_status == "invalid"
    assert result.error_message == "wrong_network"
    assert result.message == "Payment was detected but marked as invalid."


@pytest.mark.asyncio
async def test_waiting_order_with_duplicate_payment_returns_duplicate_payment():
    order = make_order(order_id=23, status=OrderStatus.WAITING_PAYMENT)
    payment = make_payment(payment_id=56, status=PaymentStatus.DUPLICATE)
    event = make_event(
        event_id=76,
        processing_status="duplicate",
        error_message="duplicate txid",
    )
    service = make_service(
        order=order,
        payment=payment,
        event=event,
    )

    result = await service.check_order_payment(23)

    assert result.status == "duplicate_payment"
    assert result.order_id == 23
    assert result.payment_id == 56
    assert result.payment_status == "duplicate"
    assert result.event_id == 76
    assert result.event_status == "duplicate"
    assert result.error_message == "duplicate txid"
    assert result.message == "Duplicate payment event detected."


@pytest.mark.asyncio
async def test_waiting_order_with_expired_payment_returns_late_payment():
    order = make_order(order_id=23, status=OrderStatus.WAITING_PAYMENT)
    payment = make_payment(payment_id=57, status=PaymentStatus.EXPIRED)
    event = make_event(
        event_id=77,
        processing_status="expired",
        error_message="Late payment for expired order",
    )
    service = make_service(
        order=order,
        payment=payment,
        event=event,
    )

    result = await service.check_order_payment(23)

    assert result.status == "late_payment"
    assert result.order_id == 23
    assert result.payment_id == 57
    assert result.payment_status == "expired"
    assert result.event_id == 77
    assert result.event_status == "expired"
    assert result.error_message == "Late payment for expired order"
    assert result.message == "Payment arrived after order expiration."


@pytest.mark.asyncio
async def test_waiting_order_with_confirmed_payment_returns_payment_confirmed():
    order = make_order(order_id=23, status=OrderStatus.WAITING_PAYMENT)
    payment = make_payment(payment_id=58, status=PaymentStatus.CONFIRMED)
    event = make_event(event_id=78, processing_status="confirmed")
    subscription = make_subscription(subscription_id=98)
    service = make_service(
        order=order,
        payment=payment,
        event=event,
        subscription=subscription,
    )

    result = await service.check_order_payment(23)

    assert result.status == "payment_confirmed"
    assert result.order_id == 23
    assert result.payment_id == 58
    assert result.payment_status == "confirmed"
    assert result.event_id == 78
    assert result.event_status == "confirmed"
    assert result.subscription_id == 98
    assert result.message == "Payment confirmed."


@pytest.mark.asyncio
async def test_waiting_order_without_payment_returns_waiting_payment():
    order = make_order(
        order_id=23,
        status=OrderStatus.WAITING_PAYMENT,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
    )
    service = make_service(order=order)

    result = await service.check_order_payment(23)

    assert result.status == "waiting_payment"
    assert result.order_id == 23
    assert result.payment_id is None
    assert result.payment_status is None
    assert result.event_id is None
    assert result.event_status is None
    assert result.subscription_id is None
    assert result.error_message is None
    assert result.message == "Payment has not been detected yet."


@pytest.mark.asyncio
async def test_waiting_order_with_past_expires_at_returns_expired_without_mutating_order():
    order = make_order(
        order_id=23,
        status=OrderStatus.WAITING_PAYMENT,
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    )
    service = make_service(order=order)

    result = await service.check_order_payment(23)

    assert result.status == "expired"
    assert result.order_id == 23
    assert result.message == "Order expired."
    assert order.status == OrderStatus.WAITING_PAYMENT


@pytest.mark.asyncio
async def test_unhandled_order_state_returns_unknown_with_context():
    order = make_order(order_id=23, status=OrderStatus.CANCELLED)
    payment = make_payment(payment_id=59, status=PaymentStatus.ERROR)
    event = make_event(
        event_id=79,
        processing_status="error",
        error_message="provider error",
    )
    subscription = make_subscription(subscription_id=99)
    service = make_service(
        order=order,
        payment=payment,
        event=event,
        subscription=subscription,
    )

    result = await service.check_order_payment(23)

    assert result.status == "unknown"
    assert result.order_id == 23
    assert result.payment_id == 59
    assert result.payment_status == "error"
    assert result.event_id == 79
    assert result.event_status == "error"
    assert result.error_message == "provider error"
    assert result.subscription_id == 99
    assert result.message == "Unknown payment state."