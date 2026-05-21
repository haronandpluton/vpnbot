from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Order, Payment, PaymentEvent, Subscription, User


@dataclass
class AdminSubscriptionLookupResult:
    found: bool
    subscription: Subscription | None = None
    user: User | None = None
    order: Order | None = None
    payments: list[Payment] | None = None
    events: list[PaymentEvent] | None = None


class AdminSubscriptionLookupService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_subscription_card(
        self,
        subscription_id: int,
    ) -> AdminSubscriptionLookupResult:
        subscription = await self._get_subscription(subscription_id)

        if subscription is None:
            return AdminSubscriptionLookupResult(found=False)

        user = await self._get_user(subscription.user_id)
        order = await self._get_order(subscription.order_id)

        payments = []
        events = []

        if subscription.order_id is not None:
            payments = await self._get_payments_by_order_id(subscription.order_id)
            events = await self._get_events_by_order_id(subscription.order_id)

        return AdminSubscriptionLookupResult(
            found=True,
            subscription=subscription,
            user=user,
            order=order,
            payments=payments,
            events=events,
        )

    async def _get_subscription(self, subscription_id: int) -> Subscription | None:
        result = await self.session.execute(
            select(Subscription).where(Subscription.id == subscription_id)
        )
        return result.scalar_one_or_none()

    async def _get_user(self, user_id: int) -> User | None:
        result = await self.session.execute(
            select(User).where(User.id == user_id)
        )
        return result.scalar_one_or_none()

    async def _get_order(self, order_id: int) -> Order | None:
        result = await self.session.execute(
            select(Order).where(Order.id == order_id)
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