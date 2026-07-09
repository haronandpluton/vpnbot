from datetime import datetime, timezone

from sqlalchemy import select

from app.database.models import Subscription
from app.database.repositories.base import BaseRepository
from app.payment_core.enums.subscription_status import SubscriptionStatus


class SubscriptionRepository(BaseRepository):
    async def get_by_id(self, subscription_id: int) -> Subscription | None:
        stmt = select(Subscription).where(Subscription.id == subscription_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id_for_update(
        self,
        subscription_id: int,
    ) -> Subscription | None:
        stmt = (
            select(Subscription)
            .where(Subscription.id == subscription_id)
            .with_for_update()
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_order_id(self, order_id: int) -> Subscription | None:
        stmt = (
            select(Subscription)
            .where(Subscription.order_id == order_id)
            .order_by(Subscription.created_at.desc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_active_by_user(self, user_id: int) -> list[Subscription]:
        stmt = select(Subscription).where(
            Subscription.user_id == user_id,
            Subscription.status == SubscriptionStatus.ACTIVE,
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_renewable_by_user(
        self,
        user_id: int,
    ) -> list[Subscription]:
        """Return subscriptions that the user may view and renew."""
        stmt = (
            select(Subscription)
            .where(
                Subscription.user_id == user_id,
                Subscription.status.in_(
                    (
                        SubscriptionStatus.ACTIVE,
                        SubscriptionStatus.EXPIRED,
                    )
                ),
            )
            .order_by(
                Subscription.expires_at.asc(),
                Subscription.id.asc(),
            )
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_active_subscription_by_user_id(
        self,
        user_id: int,
    ) -> Subscription | None:
        stmt = (
            select(Subscription)
            .where(
                Subscription.user_id == user_id,
                Subscription.status == SubscriptionStatus.ACTIVE,
            )
            .order_by(Subscription.expires_at.desc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

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
        subscription.error_reason = None
        await self.session.flush()
        return subscription

    async def renew(
        self,
        subscription: Subscription,
        expires_at: datetime,
        device_limit: int | None = None,
    ) -> Subscription:
        """
        Продлевает существующую подписку, сохраняя исходный order_id.

        История применения нового оплаченного заказа хранится в
        orders.activated_subscription_id, а не в subscriptions.order_id.
        """
        subscription.expires_at = expires_at

        if device_limit is not None:
            subscription.device_limit = device_limit

        subscription.status = SubscriptionStatus.ACTIVE
        subscription.error_reason = None
        subscription.disabled_at = None

        await self.session.flush()
        return subscription

    async def extend(
        self,
        subscription: Subscription,
        order_id: int | None,
        expires_at: datetime,
        device_limit: int | None = None,
    ) -> Subscription:
        """
        Legacy-метод, сохраняемый для совместимости со старым кодом.

        Не использовать для post-payment продления: он меняет order_id
        подписки и тем самым теряет связь с заказом её создания.
        """
        subscription.order_id = order_id
        subscription.expires_at = expires_at

        if device_limit is not None:
            subscription.device_limit = device_limit

        if subscription.status != SubscriptionStatus.ACTIVE:
            subscription.status = SubscriptionStatus.ACTIVE

        subscription.error_reason = None

        await self.session.flush()
        return subscription

    async def mark_access_sent(
        self,
        subscription: Subscription,
        sent_at: datetime | None = None,
    ) -> Subscription:
        subscription.last_access_sent_at = sent_at or datetime.now(timezone.utc)
        await self.session.flush()
        return subscription

    async def mark_expired(self, subscription: Subscription) -> Subscription:
        subscription.status = SubscriptionStatus.EXPIRED
        await self.session.flush()
        return subscription

    async def disable(
        self,
        subscription: Subscription,
        reason: str | None = None,
    ) -> Subscription:
        subscription.status = SubscriptionStatus.DISABLED
        subscription.error_reason = reason
        subscription.disabled_at = datetime.now(timezone.utc)
        await self.session.flush()
        return subscription
