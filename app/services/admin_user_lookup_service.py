from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Order, Payment, Subscription, User
from app.payment_core.enums.payment_status import PaymentStatus


@dataclass
class AdminUserLookupResult:
    found: bool
    user: User | None = None
    orders: list[Order] | None = None
    payments: list[Payment] | None = None
    subscriptions: list[Subscription] | None = None
    invalid_payments_count: int = 0


class AdminUserLookupService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_user_card_by_user_id(
        self,
        user_id: int,
    ) -> AdminUserLookupResult:
        user = await self._get_user_by_id(user_id)

        if user is None:
            return AdminUserLookupResult(found=False)

        return await self._build_result(user)

    async def get_user_card_by_telegram_id(
        self,
        telegram_id: int,
    ) -> AdminUserLookupResult:
        user = await self._get_user_by_telegram_id(telegram_id)

        if user is None:
            return AdminUserLookupResult(found=False)

        return await self._build_result(user)

    async def _build_result(self, user: User) -> AdminUserLookupResult:
        orders = await self._get_last_orders(user.id)
        payments = await self._get_last_payments(user.id)
        subscriptions = await self._get_last_subscriptions(user.id)
        invalid_payments_count = await self._count_invalid_payments(user.id)

        return AdminUserLookupResult(
            found=True,
            user=user,
            orders=orders,
            payments=payments,
            subscriptions=subscriptions,
            invalid_payments_count=invalid_payments_count,
        )

    async def _get_user_by_id(self, user_id: int) -> User | None:
        result = await self.session.execute(
            select(User).where(User.id == user_id)
        )
        return result.scalar_one_or_none()

    async def _get_user_by_telegram_id(self, telegram_id: int) -> User | None:
        result = await self.session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        return result.scalar_one_or_none()

    async def _get_last_orders(self, user_id: int, limit: int = 5) -> list[Order]:
        result = await self.session.execute(
            select(Order)
            .where(Order.user_id == user_id)
            .order_by(Order.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def _get_last_payments(self, user_id: int, limit: int = 5) -> list[Payment]:
        result = await self.session.execute(
            select(Payment)
            .where(Payment.user_id == user_id)
            .order_by(Payment.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def _get_last_subscriptions(
        self,
        user_id: int,
        limit: int = 5,
    ) -> list[Subscription]:
        result = await self.session.execute(
            select(Subscription)
            .where(Subscription.user_id == user_id)
            .order_by(Subscription.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def _count_invalid_payments(self, user_id: int) -> int:
        result = await self.session.execute(
            select(func.count(Payment.id)).where(
                Payment.user_id == user_id,
                Payment.status == PaymentStatus.INVALID,
            )
        )
        return int(result.scalar_one() or 0)