from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Order, Payment, Subscription, User
from app.payment_core.enums.order_status import OrderStatus
from app.payment_core.enums.payment_status import PaymentStatus
from app.payment_core.enums.subscription_status import SubscriptionStatus


@dataclass
class AdminStatsResult:
    users_total: int

    orders_total: int
    orders_waiting_payment: int
    orders_paid: int
    orders_activated: int
    orders_expired: int
    orders_failed: int
    orders_cancelled: int

    payments_total: int
    payments_confirmed: int
    payments_invalid: int
    payments_duplicate: int
    payments_error: int

    subscriptions_total: int
    subscriptions_active: int
    subscriptions_expired: int
    subscriptions_disabled: int

    confirmed_revenue_total: Decimal


class AdminStatsService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_stats(self) -> AdminStatsResult:
        return AdminStatsResult(
            users_total=await self._count(User),

            orders_total=await self._count(Order),
            orders_waiting_payment=await self._count_orders_by_status(OrderStatus.WAITING_PAYMENT),
            orders_paid=await self._count_orders_by_status(OrderStatus.PAID),
            orders_activated=await self._count_orders_by_status(OrderStatus.ACTIVATED),
            orders_expired=await self._count_orders_by_status(OrderStatus.EXPIRED),
            orders_failed=await self._count_orders_by_status(OrderStatus.FAILED),
            orders_cancelled=await self._count_orders_by_status(OrderStatus.CANCELLED),

            payments_total=await self._count(Payment),
            payments_confirmed=await self._count_payments_by_status(PaymentStatus.CONFIRMED),
            payments_invalid=await self._count_payments_by_status(PaymentStatus.INVALID),
            payments_duplicate=await self._count_payments_by_status(PaymentStatus.DUPLICATE),
            payments_error=await self._count_payments_by_status(PaymentStatus.ERROR),

            subscriptions_total=await self._count(Subscription),
            subscriptions_active=await self._count_subscriptions_by_status(SubscriptionStatus.ACTIVE),
            subscriptions_expired=await self._count_subscriptions_by_status(SubscriptionStatus.EXPIRED),
            subscriptions_disabled=await self._count_subscriptions_by_status(SubscriptionStatus.DISABLED),

            confirmed_revenue_total=await self._confirmed_revenue_total(),
        )

    async def _count(self, model) -> int:
        stmt = select(func.count(model.id))
        result = await self.session.execute(stmt)
        return int(result.scalar_one() or 0)

    async def _count_orders_by_status(self, status: OrderStatus) -> int:
        stmt = select(func.count(Order.id)).where(Order.status == status)
        result = await self.session.execute(stmt)
        return int(result.scalar_one() or 0)

    async def _count_payments_by_status(self, status: PaymentStatus) -> int:
        stmt = select(func.count(Payment.id)).where(Payment.status == status)
        result = await self.session.execute(stmt)
        return int(result.scalar_one() or 0)

    async def _count_subscriptions_by_status(self, status: SubscriptionStatus) -> int:
        stmt = select(func.count(Subscription.id)).where(Subscription.status == status)
        result = await self.session.execute(stmt)
        return int(result.scalar_one() or 0)

    async def _confirmed_revenue_total(self) -> Decimal:
        stmt = select(func.coalesce(func.sum(Payment.amount), 0)).where(
            Payment.status == PaymentStatus.CONFIRMED,
        )
        result = await self.session.execute(stmt)
        value = result.scalar_one()

        if value is None:
            return Decimal("0")

        return Decimal(str(value))