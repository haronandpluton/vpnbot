from datetime import datetime

from sqlalchemy import select

from app.database.models import Subscription
from app.database.repositories.base import BaseRepository
from app.payment_core.enums.subscription_status import SubscriptionStatus


class SubscriptionRepository(BaseRepository):
    async def get_by_id(self, subscription_id: int) -> Subscription | None:
        stmt = select(Subscription).where(Subscription.id == subscription_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_active_by_user(self, user_id: int) -> list[Subscription]:
        stmt = select(Subscription).where(
            Subscription.user_id == user_id,
            Subscription.status == SubscriptionStatus.ACTIVE,
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create(
        self,
        user_id: int,
        order_id: int | None,
        vpn_server_id: int | None,
        uuid: str,
        device_limit: int,
        starts_at: datetime,
        expires_at: datetime,
    ) -> Subscription:
        subscription = Subscription(
            user_id=user_id,
            order_id=order_id,
            vpn_server_id=vpn_server_id,
            status=SubscriptionStatus.INACTIVE,
            uuid=uuid,
            device_limit=device_limit,
            starts_at=starts_at,
            expires_at=expires_at,
        )
        self.session.add(subscription)
        await self.session.flush()
        return subscription

    async def activate(self, subscription: Subscription) -> Subscription:
        subscription.status = SubscriptionStatus.ACTIVE
        await self.session.flush()
        return subscription

    async def mark_expired(self, subscription: Subscription) -> Subscription:
        subscription.status = SubscriptionStatus.EXPIRED
        await self.session.flush()
        return subscription

    async def disable(self, subscription: Subscription, reason: str | None = None) -> Subscription:
        subscription.status = SubscriptionStatus.DISABLED
        subscription.error_reason = reason
        subscription.disabled_at = datetime.utcnow()
        await self.session.flush()
        return subscription