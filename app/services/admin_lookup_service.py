from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Order, Payment, PaymentEvent, Subscription, User


@dataclass
class AdminOrderLookupResult:
    found: bool
    order: Order | None = None
    user: User | None = None
    payments: list[Payment] | None = None
    events: list[PaymentEvent] | None = None
    subscriptions: list[Subscription] | None = None


@dataclass
class AdminPaymentLookupResult:
    found: bool
    payment: Payment | None = None
    order: Order | None = None
    user: User | None = None
    events: list[PaymentEvent] | None = None
    subscriptions: list[Subscription] | None = None


class AdminLookupService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_order_card(self, order_id: int) -> AdminOrderLookupResult:
        order = await self._get_order(order_id)

        if order is None:
            return AdminOrderLookupResult(found=False)

        user = await self._get_user(order.user_id)

        payments = await self._get_payments_by_order_id(order.id)
        events = await self._get_events_by_order_id(order.id)
        subscriptions = await self._get_subscriptions_by_order_id(order.id)

        return AdminOrderLookupResult(
            found=True,
            order=order,
            user=user,
            payments=payments,
            events=events,
            subscriptions=subscriptions,
        )

    async def get_payment_card(self, payment_id: int) -> AdminPaymentLookupResult:
        payment = await self._get_payment(payment_id)

        if payment is None:
            return AdminPaymentLookupResult(found=False)

        order = None
        user = None
        events: list[PaymentEvent] = []
        subscriptions: list[Subscription] = []

        if payment.order_id is not None:
            order = await self._get_order(payment.order_id)
            events = await self._get_events_by_order_id(payment.order_id)
            subscriptions = await self._get_subscriptions_by_order_id(payment.order_id)

        if payment.user_id is not None:
            user = await self._get_user(payment.user_id)

        return AdminPaymentLookupResult(
            found=True,
            payment=payment,
            order=order,
            user=user,
            events=events,
            subscriptions=subscriptions,
        )

    async def _get_order(self, order_id: int) -> Order | None:
        result = await self.session.execute(
            select(Order).where(Order.id == order_id)
        )
        return result.scalar_one_or_none()

    async def _get_payment(self, payment_id: int) -> Payment | None:
        result = await self.session.execute(
            select(Payment).where(Payment.id == payment_id)
        )
        return result.scalar_one_or_none()

    async def _get_user(self, user_id: int) -> User | None:
        result = await self.session.execute(
            select(User).where(User.id == user_id)
        )
        return result.scalar_one_or_none()

    async def _get_payments_by_order_id(self, order_id: int) -> list[Payment]:
        result = await self.session.execute(
            select(Payment)
            .where(Payment.order_id == order_id)
            .order_by(Payment.created_at.desc())
        )
        return list(result.scalars().all())

    async def _get_events_by_order_id(self, order_id: int) -> list[PaymentEvent]:
        result = await self.session.execute(
            select(PaymentEvent)
            .where(PaymentEvent.order_id == order_id)
            .order_by(PaymentEvent.created_at.desc())
        )
        return list(result.scalars().all())

    async def _get_subscriptions_by_order_id(self, order_id: int) -> list[Subscription]:
        result = await self.session.execute(
            select(Subscription)
            .where(Subscription.order_id == order_id)
            .order_by(Subscription.created_at.desc())
        )
        return list(result.scalars().all())


def enum_to_str(value: Any) -> str:
    if value is None:
        return "—"

    if hasattr(value, "value"):
        return str(value.value)

    return str(value)


def decimal_to_str(value: Decimal | None) -> str:
    if value is None:
        return "—"

    normalized = value.quantize(Decimal("0.00000001"))
    text = f"{normalized:f}".rstrip("0").rstrip(".")

    return text or "0"


def datetime_to_str(value: datetime | None) -> str:
    if value is None:
        return "—"

    return value.strftime("%d.%m.%Y %H:%M:%S")


def clean(value: Any) -> str:
    if value is None or value == "":
        return "—"

    return str(value)