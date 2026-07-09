from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Order
from app.database.repositories.orders import OrderRepository
from app.database.repositories.subscriptions import SubscriptionRepository
from app.payment_core.enums.order_status import OrderStatus
from app.payment_core.enums.subscription_status import SubscriptionStatus
from app.services.subscription_meta_sync_service import SubscriptionMetaSyncService
from app.services.vpn_access_service import VpnAccessService


class SubscriptionService:
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
        Идемпотентный post-payment flow.

        paid order ->
        create new subscription OR renew selected subscription ->
        save activated_subscription_id ->
        order activated

        Защита:
        - один order применяется не более одного раза;
        - повторная обработка возвращает уже применённую подписку;
        - один order блокируется через SELECT FOR UPDATE;
        - целевая подписка при продлении тоже блокируется;
        - subscriptions.order_id при продлении не перезаписывается.
        """
        try:
            order = await self._get_order_for_activation(order_id)
            if order is None:
                raise ValueError(f"Order not found: {order_id}")

            activated_subscription_id = getattr(
                order,
                "activated_subscription_id",
                None,
            )
            target_subscription_id = getattr(
                order,
                "target_subscription_id",
                None,
            )

            if activated_subscription_id is not None:
                subscription = await self.subscription_repository.get_by_id(
                    activated_subscription_id
                )
                if subscription is None:
                    raise ValueError(
                        f"Order {order.id} references missing activated "
                        f"subscription {activated_subscription_id}"
                    )

                return await self._return_existing_subscription_for_order(
                    order=order,
                    subscription=subscription,
                    sync_reason="idempotent_order_activation_reuse",
                )

            # Совместимость со старыми заказами создания подписки.
            # Для renewal-заказов этот fallback намеренно не используется.
            if target_subscription_id is None:
                existing_subscription_for_order = (
                    await self.subscription_repository.get_by_order_id(order.id)
                )

                if existing_subscription_for_order is not None:
                    order.activated_subscription_id = (
                        existing_subscription_for_order.id
                    )
                    return await self._return_existing_subscription_for_order(
                        order=order,
                        subscription=existing_subscription_for_order,
                        sync_reason="idempotent_order_activation_reuse",
                    )

            if order.status == OrderStatus.ACTIVATED:
                raise ValueError(
                    f"Order {order.id} is activated, "
                    "but subscription linked to this order was not found"
                )

            if order.status != OrderStatus.PAID:
                raise ValueError(
                    "Order must be paid before subscription activation. "
                    f"order_id={order.id}, status={order.status}"
                )

            if target_subscription_id is None:
                subscription, config_uri = await self._create_new_subscription(
                    order
                )
                activation_mode = "created"
            else:
                target_subscription = (
                    await self.subscription_repository.get_by_id_for_update(
                        target_subscription_id
                    )
                )
                self._validate_renewal_target(
                    order=order,
                    subscription=target_subscription,
                )
                subscription, config_uri = (
                    await self._renew_existing_subscription(
                        subscription=target_subscription,
                        order=order,
                    )
                )
                activation_mode = "renewed"

            order.activated_subscription_id = subscription.id
            order.status = OrderStatus.ACTIVATED
            order.activated_at = datetime.now(timezone.utc)

            await self.session.flush()
            await self.session.commit()

            await self._sync_order_activation(
                order=order,
                subscription=subscription,
                activation_mode=activation_mode,
                reason="post_payment_subscription_change",
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
        Идемпотентный возврат результата уже применённого заказа.

        Не создаёт UUID и не изменяет expires_at.
        """
        if order.status == OrderStatus.PAID:
            order.status = OrderStatus.ACTIVATED
            order.activated_at = order.activated_at or datetime.now(timezone.utc)
        elif order.status != OrderStatus.ACTIVATED:
            raise ValueError(
                "Order with activated subscription must be paid or activated. "
                f"order_id={order.id}, status={order.status}"
            )

        order.activated_subscription_id = subscription.id
        await self.session.flush()

        config_uri = await self.vpn_access_service.get_config(
            uuid=subscription.uuid,
            device_limit=subscription.device_limit,
        )

        await self.session.commit()

        await self._sync_order_activation(
            order=order,
            subscription=subscription,
            activation_mode="reused",
            reason=sync_reason,
        )

        await self.session.refresh(subscription)

        return subscription, config_uri

    async def resend_access(self, user_id: int):
        """
        Legacy-повторная выдача доступа по пользователю.

        Пользовательский интерфейс нескольких подписок использует
        MySubscriptionService и конкретный subscription_id.
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
        self._validate_order_duration(order)

        expires_at = now + timedelta(days=order.duration_days)

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
        subscription = await self.subscription_repository.mark_access_sent(
            subscription
        )

        return subscription, access.config_uri

    async def _renew_existing_subscription(
        self,
        subscription,
        order,
    ):
        now = datetime.now(timezone.utc)
        self._validate_order_duration(order)

        base_time = max(subscription.expires_at, now)
        new_expires_at = base_time + timedelta(days=order.duration_days)

        access = await self.vpn_access_service.extend_access(
            uuid=subscription.uuid,
            device_limit=subscription.device_limit,
        )

        subscription = await self.subscription_repository.renew(
            subscription=subscription,
            expires_at=new_expires_at,
            device_limit=subscription.device_limit,
        )

        subscription = await self.subscription_repository.mark_access_sent(
            subscription
        )

        return subscription, access.config_uri

    def _validate_renewal_target(
        self,
        *,
        order,
        subscription,
    ) -> None:
        target_subscription_id = order.target_subscription_id

        if subscription is None:
            raise ValueError(
                f"Target subscription not found: {target_subscription_id}"
            )

        if subscription.user_id != order.user_id:
            raise ValueError(
                f"Target subscription not found: {target_subscription_id}"
            )

        if subscription.status not in {
            SubscriptionStatus.ACTIVE,
            SubscriptionStatus.EXPIRED,
        }:
            raise ValueError(
                "Target subscription is not renewable. "
                f"subscription_id={subscription.id}, "
                f"status={subscription.status.value}"
            )

        if subscription.device_limit != order.device_limit:
            raise ValueError(
                "Target subscription device limit does not match order. "
                f"subscription_id={subscription.id}, "
                f"subscription_device_limit={subscription.device_limit}, "
                f"order_device_limit={order.device_limit}"
            )

    @staticmethod
    def _validate_order_duration(order) -> None:
        if order.duration_days <= 0:
            raise ValueError(
                "Invalid order duration: "
                f"order_id={order.id}, duration_days={order.duration_days}"
            )

    async def _sync_order_activation(
        self,
        *,
        order,
        subscription,
        activation_mode: str,
        reason: str,
    ) -> None:
        await SubscriptionMetaSyncService(self.session).sync_safely(
            entity_type="order",
            entity_id=order.id,
            reason=reason,
            payload={
                "order_id": order.id,
                "user_id": subscription.user_id,
                "target_subscription_id": getattr(
                    order,
                    "target_subscription_id",
                    None,
                ),
                "activated_subscription_id": subscription.id,
                "subscription_id": subscription.id,
                "activation_mode": activation_mode,
                "uuid": subscription.uuid,
                "expires_at": None
                if subscription.expires_at is None
                else subscription.expires_at.isoformat(),
                "status": str(subscription.status.value),
            },
        )
