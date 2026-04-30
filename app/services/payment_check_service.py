from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Order, Payment, PaymentEvent, Subscription
from app.payment_core.enums.order_status import OrderStatus
from app.payment_core.enums.payment_status import PaymentStatus


@dataclass
class PaymentCheckResult:
    status: str
    order_id: int
    payment_id: int | None = None
    payment_status: str | None = None
    event_id: int | None = None
    event_status: str | None = None
    error_message: str | None = None
    subscription_id: int | None = None
    message: str | None = None


class PaymentCheckService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def check_order_payment(self, order_id: int) -> PaymentCheckResult:
        order = await self._get_order(order_id)

        if order is None:
            raise ValueError(f"Order not found: {order_id}")

        payment = await self._get_latest_payment(order_id)
        event = await self._get_latest_event(order_id)
        subscription = await self._get_subscription(order_id)

        if order.status == OrderStatus.ACTIVATED:
            return PaymentCheckResult(
                status="activated",
                order_id=order.id,
                payment_id=None if payment is None else payment.id,
                payment_status=None if payment is None else payment.status.value,
                event_id=None if event is None else event.id,
                event_status=None if event is None else event.processing_status,
                subscription_id=None if subscription is None else subscription.id,
                message="Payment confirmed and subscription activated.",
            )

        if order.status == OrderStatus.PAID:
            return PaymentCheckResult(
                status="paid_waiting_activation",
                order_id=order.id,
                payment_id=None if payment is None else payment.id,
                payment_status=None if payment is None else payment.status.value,
                event_id=None if event is None else event.id,
                event_status=None if event is None else event.processing_status,
                subscription_id=None if subscription is None else subscription.id,
                message="Payment confirmed, activation is still pending.",
            )

        if order.status == OrderStatus.FAILED:
            return PaymentCheckResult(
                status="activation_failed",
                order_id=order.id,
                payment_id=None if payment is None else payment.id,
                payment_status=None if payment is None else payment.status.value,
                event_id=None if event is None else event.id,
                event_status=None if event is None else event.processing_status,
                error_message=order.failure_reason,
                subscription_id=None if subscription is None else subscription.id,
                message="Payment or activation requires manual recovery.",
            )

        if order.status == OrderStatus.EXPIRED:
            return PaymentCheckResult(
                status="expired",
                order_id=order.id,
                payment_id=None if payment is None else payment.id,
                payment_status=None if payment is None else payment.status.value,
                event_id=None if event is None else event.id,
                event_status=None if event is None else event.processing_status,
                error_message=None if event is None else event.error_message,
                subscription_id=None if subscription is None else subscription.id,
                message="Order expired.",
            )

        if payment is not None:
            if payment.status == PaymentStatus.INVALID:
                return PaymentCheckResult(
                    status="invalid_payment",
                    order_id=order.id,
                    payment_id=payment.id,
                    payment_status=payment.status.value,
                    event_id=None if event is None else event.id,
                    event_status=None if event is None else event.processing_status,
                    error_message=None if event is None else event.error_message,
                    subscription_id=None if subscription is None else subscription.id,
                    message="Payment was detected but marked as invalid.",
                )

            if payment.status == PaymentStatus.DUPLICATE:
                return PaymentCheckResult(
                    status="duplicate_payment",
                    order_id=order.id,
                    payment_id=payment.id,
                    payment_status=payment.status.value,
                    event_id=None if event is None else event.id,
                    event_status=None if event is None else event.processing_status,
                    error_message=None if event is None else event.error_message,
                    subscription_id=None if subscription is None else subscription.id,
                    message="Duplicate payment event detected.",
                )

            if payment.status == PaymentStatus.EXPIRED:
                return PaymentCheckResult(
                    status="late_payment",
                    order_id=order.id,
                    payment_id=payment.id,
                    payment_status=payment.status.value,
                    event_id=None if event is None else event.id,
                    event_status=None if event is None else event.processing_status,
                    error_message=None if event is None else event.error_message,
                    subscription_id=None if subscription is None else subscription.id,
                    message="Payment arrived after order expiration.",
                )

            if payment.status == PaymentStatus.CONFIRMED:
                return PaymentCheckResult(
                    status="payment_confirmed",
                    order_id=order.id,
                    payment_id=payment.id,
                    payment_status=payment.status.value,
                    event_id=None if event is None else event.id,
                    event_status=None if event is None else event.processing_status,
                    subscription_id=None if subscription is None else subscription.id,
                    message="Payment confirmed.",
                )

        if order.status == OrderStatus.WAITING_PAYMENT:
            if order.expires_at is not None and order.expires_at <= datetime.now(timezone.utc):
                return PaymentCheckResult(
                    status="expired",
                    order_id=order.id,
                    message="Order expired.",
                )

            return PaymentCheckResult(
                status="waiting_payment",
                order_id=order.id,
                message="Payment has not been detected yet.",
            )

        return PaymentCheckResult(
            status="unknown",
            order_id=order.id,
            payment_id=None if payment is None else payment.id,
            payment_status=None if payment is None else payment.status.value,
            event_id=None if event is None else event.id,
            event_status=None if event is None else event.processing_status,
            error_message=None if event is None else event.error_message,
            subscription_id=None if subscription is None else subscription.id,
            message="Unknown payment state.",
        )

    async def _get_order(self, order_id: int) -> Order | None:
        result = await self.session.execute(
            select(Order).where(Order.id == order_id)
        )
        return result.scalar_one_or_none()

    async def _get_latest_payment(self, order_id: int) -> Payment | None:
        result = await self.session.execute(
            select(Payment)
            .where(Payment.order_id == order_id)
            .order_by(Payment.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def _get_latest_event(self, order_id: int) -> PaymentEvent | None:
        result = await self.session.execute(
            select(PaymentEvent)
            .where(PaymentEvent.order_id == order_id)
            .order_by(PaymentEvent.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def _get_subscription(self, order_id: int) -> Subscription | None:
        result = await self.session.execute(
            select(Subscription)
            .where(Subscription.order_id == order_id)
            .order_by(Subscription.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()