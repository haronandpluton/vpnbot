from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Order, Subscription, User
from app.payment_core.enums.subscription_status import SubscriptionStatus
from app.services.vpn_access_service import VpnAccessService


@dataclass
class AdminResendConfigResult:
    status: str
    order_id: int
    user_id: int | None = None
    telegram_id: int | None = None
    username: str | None = None
    subscription_id: int | None = None
    subscription_status: str | None = None
    expires_at: datetime | None = None
    config_uri: str | None = None
    message: str | None = None


class AdminRecoveryService:
    def __init__(
        self,
        session: AsyncSession,
        vpn_access_service: VpnAccessService | None = None,
    ) -> None:
        self.session = session
        self.vpn_access_service = vpn_access_service or VpnAccessService()

    async def prepare_resend_config(self, order_id: int) -> AdminResendConfigResult:
        order = await self._get_order(order_id)

        if order is None:
            return AdminResendConfigResult(
                status="order_not_found",
                order_id=order_id,
                message="Order not found.",
            )

        user = await self._get_user(order.user_id)

        if user is None:
            return AdminResendConfigResult(
                status="user_not_found",
                order_id=order.id,
                user_id=order.user_id,
                message="User not found.",
            )

        subscription = await self._get_latest_subscription_by_order_id(order.id)

        if subscription is None:
            return AdminResendConfigResult(
                status="subscription_not_found",
                order_id=order.id,
                user_id=user.id,
                telegram_id=user.telegram_id,
                username=user.username,
                message="Subscription not found.",
            )

        if subscription.status != SubscriptionStatus.ACTIVE:
            return AdminResendConfigResult(
                status="subscription_not_active",
                order_id=order.id,
                user_id=user.id,
                telegram_id=user.telegram_id,
                username=user.username,
                subscription_id=subscription.id,
                subscription_status=self._enum_to_str(subscription.status),
                expires_at=subscription.expires_at,
                message="Subscription is not active.",
            )

        now = datetime.now(timezone.utc)

        if subscription.expires_at is not None and subscription.expires_at <= now:
            return AdminResendConfigResult(
                status="subscription_expired",
                order_id=order.id,
                user_id=user.id,
                telegram_id=user.telegram_id,
                username=user.username,
                subscription_id=subscription.id,
                subscription_status=self._enum_to_str(subscription.status),
                expires_at=subscription.expires_at,
                message="Subscription expired.",
            )

        config_uri = await self.vpn_access_service.get_config(
            uuid=subscription.uuid,
            device_limit=subscription.device_limit,
        )

        subscription.last_access_sent_at = datetime.now(timezone.utc)
        await self.session.commit()

        return AdminResendConfigResult(
            status="ready",
            order_id=order.id,
            user_id=user.id,
            telegram_id=user.telegram_id,
            username=user.username,
            subscription_id=subscription.id,
            subscription_status=self._enum_to_str(subscription.status),
            expires_at=subscription.expires_at,
            config_uri=config_uri,
            message="Config prepared.",
        )

    async def _get_order(self, order_id: int) -> Order | None:
        result = await self.session.execute(
            select(Order).where(Order.id == order_id)
        )
        return result.scalar_one_or_none()

    async def _get_user(self, user_id: int) -> User | None:
        result = await self.session.execute(
            select(User).where(User.id == user_id)
        )
        return result.scalar_one_or_none()

    async def _get_latest_subscription_by_order_id(
        self,
        order_id: int,
    ) -> Subscription | None:
        result = await self.session.execute(
            select(Subscription)
            .where(Subscription.order_id == order_id)
            .order_by(Subscription.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    @staticmethod
    def _enum_to_str(value) -> str | None:
        if value is None:
            return None

        if hasattr(value, "value"):
            return str(value.value)

        return str(value)