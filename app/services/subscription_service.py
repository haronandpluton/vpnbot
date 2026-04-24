from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.repositories.orders import OrderRepository
from app.database.repositories.subscriptions import SubscriptionRepository
from app.payment_core.enums.order_status import OrderStatus
from app.payment_core.enums.subscription_status import SubscriptionStatus
from app.services.vpn_access_service import VpnAccessService


class SubscriptionService:
    SUBSCRIPTION_DAYS = 30

    def __init__(
        self,
        session: AsyncSession,
        vpn_access_service: VpnAccessService | None = None,
    ) -> None:
        self.session = session
        self.order_repository = OrderRepository(session)
        self.subscription_repository = SubscriptionRepository(session)
        self.vpn_access_service = vpn_access_service or VpnAccessService()

    async def activate_or_extend_by_order(self, order_id: int):
        """
        Основной post-payment flow:

        paid order ->
        create new subscription OR extend existing subscription ->
        order activated
        """
        try:
            order = await self.order_repository.get_by_id(order_id)
            if order is None:
                raise ValueError(f"Order not found: {order_id}")

            if order.status == OrderStatus.ACTIVATED:
                active_subscription = (
                    await self.subscription_repository.get_active_subscription_by_user_id(
                        order.user_id
                    )
                )
                if active_subscription is None:
                    raise ValueError(
                        f"Order {order.id} is activated, but active subscription not found"
                    )

                config_uri = await self.vpn_access_service.get_config(
                    uuid=active_subscription.uuid,
                    device_limit=active_subscription.device_limit,
                )

                await self.session.commit()
                return active_subscription, config_uri

            if order.status != OrderStatus.PAID:
                raise ValueError(
                    f"Order must be paid before subscription activation. "
                    f"order_id={order.id}, status={order.status}"
                )

            active_subscription = (
                await self.subscription_repository.get_active_subscription_by_user_id(
                    order.user_id
                )
            )

            if active_subscription is None:
                subscription, config_uri = await self._create_new_subscription(order)
            else:
                subscription, config_uri = await self._extend_existing_subscription(
                    active_subscription=active_subscription,
                    order=order,
                )

            order.status = OrderStatus.ACTIVATED
            order.activated_at = datetime.now(timezone.utc)

            await self.session.flush()
            await self.session.commit()

            return subscription, config_uri

        except Exception:
            await self.session.rollback()
            raise

    async def resend_access(self, user_id: int):
        """
        Повторная выдача доступа.

        Не создает новый UUID.
        Не продлевает срок.
        Не создает новую подписку.
        """
        try:
            subscription = (
                await self.subscription_repository.get_active_subscription_by_user_id(
                    user_id
                )
            )

            if subscription is None:
                raise ValueError(f"Active subscription not found for user_id={user_id}")

            config_uri = await self.vpn_access_service.get_config(
                uuid=subscription.uuid,
                device_limit=subscription.device_limit,
            )

            subscription = await self.subscription_repository.mark_access_sent(
                subscription
            )

            await self.session.commit()
            return subscription, config_uri

        except Exception:
            await self.session.rollback()
            raise

    async def _create_new_subscription(self, order):
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(days=self.SUBSCRIPTION_DAYS)

        access = await self.vpn_access_service.create_access(
            user_id=order.user_id,
            device_limit=order.device_limit,
        )

        subscription = await self.subscription_repository.create(
            user_id=order.user_id,
            order_id=order.id,
            vpn_server_id=access.vpn_server_id,
            uuid=access.uuid,
            device_limit=order.device_limit,
            starts_at=now,
            expires_at=expires_at,
        )

        subscription = await self.subscription_repository.activate(subscription)
        subscription = await self.subscription_repository.mark_access_sent(subscription)

        return subscription, access.config_uri

    async def _extend_existing_subscription(
        self,
        active_subscription,
        order,
    ):
        now = datetime.now(timezone.utc)

        base_time = max(active_subscription.expires_at, now)
        new_expires_at = base_time + timedelta(days=self.SUBSCRIPTION_DAYS)

        access = await self.vpn_access_service.extend_access(
            uuid=active_subscription.uuid,
            device_limit=order.device_limit,
        )

        subscription = await self.subscription_repository.extend(
            subscription=active_subscription,
            order_id=order.id,
            expires_at=new_expires_at,
            device_limit=order.device_limit,
        )

        subscription = await self.subscription_repository.mark_access_sent(subscription)

        return subscription, access.config_uri