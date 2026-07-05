from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.subscription_meta_sync_service import SubscriptionMetaSyncService
from app.database.repositories.orders import OrderRepository
from app.database.repositories.subscriptions import SubscriptionRepository
from app.payment_core.enums.order_status import OrderStatus
from app.services.vpn_access_service import VpnAccessService
from sqlalchemy import select
from app.database.models import Order


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
        Идемпотентный post-payment flow:

        paid order ->
        create new subscription OR extend existing subscription ->
        order activated

        Защита:
        - повторная обработка того же order не создает новый UUID;
        - повторная обработка того же order не продлевает подписку второй раз;
        - concurrent activation одного order сериализуется через SELECT FOR UPDATE.
        """
        try:
            order = await self._get_order_for_activation(order_id)
            if order is None:
                raise ValueError(f"Order not found: {order_id}")

            existing_subscription_for_order = (
                await self.subscription_repository.get_by_order_id(order.id)
            )

            if existing_subscription_for_order is not None:
                return await self._return_existing_subscription_for_order(
                    order=order,
                    subscription=existing_subscription_for_order,
                    sync_reason="idempotent_order_activation_reuse",
                )

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

                return await self._return_existing_subscription_for_order(
                    order=order,
                    subscription=active_subscription,
                    sync_reason="activated_order_resync",
                )

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

            await SubscriptionMetaSyncService(self.session).sync_safely(
                entity_type="order",
                entity_id=order.id,
                reason="post_payment_subscription_change",
                payload={
                    "order_id": order.id,
                    "user_id": subscription.user_id,
                    "subscription_id": subscription.id,
                    "uuid": subscription.uuid,
                    "expires_at": None
                    if subscription.expires_at is None
                    else subscription.expires_at.isoformat(),
                    "status": str(subscription.status.value),
                },
            )

            await self.session.refresh(subscription)

            return subscription, config_uri

        except Exception:
            await self.session.rollback()
            raise

    async def _get_order_for_activation(self, order_id: int) -> Order | None:
        stmt = (
            select(Order)
            .where(Order.id == order_id)
            .with_for_update()
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def _return_existing_subscription_for_order(
        self,
        order: Order,
        subscription,
        sync_reason: str,
    ):
        """
        Идемпотентный возврат уже созданного доступа.

        Не создает новый UUID.
        Не продлевает expires_at.
        Не вызывает create_access / extend_access.
        """
        if order.status == OrderStatus.PAID:
            order.status = OrderStatus.ACTIVATED
            order.activated_at = order.activated_at or datetime.now(timezone.utc)
            await self.session.flush()

        config_uri = await self.vpn_access_service.get_config(
            uuid=subscription.uuid,
            device_limit=subscription.device_limit,
        )

        await self.session.commit()

        await SubscriptionMetaSyncService(self.session).sync_safely(
            entity_type="order",
            entity_id=order.id,
            reason=sync_reason,
            payload={
                "order_id": order.id,
                "user_id": subscription.user_id,
                "subscription_id": subscription.id,
                "uuid": subscription.uuid,
                "expires_at": None
                if subscription.expires_at is None
                else subscription.expires_at.isoformat(),
                "status": str(subscription.status.value),
            },
        )

        await self.session.refresh(subscription)

        return subscription, config_uri

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