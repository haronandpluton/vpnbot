from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.repositories.subscriptions import SubscriptionRepository
from app.database.repositories.users import UserRepository
from app.payment_core.enums.subscription_status import SubscriptionStatus
from app.services.vpn_access_service import VpnAccessService


@dataclass
class MySubscriptionResult:
    status: str
    user_id: int | None = None
    subscription_id: int | None = None
    subscription_status: str | None = None
    expires_at: datetime | None = None
    device_limit: int | None = None
    config_uri: str | None = None
    message: str | None = None


class MySubscriptionService:
    def __init__(
        self,
        session: AsyncSession,
        vpn_access_service: VpnAccessService | None = None,
    ) -> None:
        self.session = session
        self.user_repository = UserRepository(session)
        self.subscription_repository = SubscriptionRepository(session)
        self.vpn_access_service = vpn_access_service or VpnAccessService()

    async def get_active_subscription_by_telegram_id(
        self,
        telegram_id: int,
    ) -> MySubscriptionResult:
        user = await self.user_repository.get_by_telegram_id(telegram_id)

        if user is None:
            return MySubscriptionResult(
                status="user_not_found",
                message="Пользователь не найден.",
            )

        subscription = (
            await self.subscription_repository.get_active_subscription_by_user_id(
                user.id
            )
        )

        if subscription is None:
            return MySubscriptionResult(
                status="subscription_not_found",
                user_id=user.id,
                message="Активная подписка не найдена.",
            )

        now = datetime.now(timezone.utc)

        if subscription.status != SubscriptionStatus.ACTIVE:
            return MySubscriptionResult(
                status="subscription_not_active",
                user_id=user.id,
                subscription_id=subscription.id,
                subscription_status=subscription.status.value,
                expires_at=subscription.expires_at,
                device_limit=subscription.device_limit,
                message="Подписка не активна.",
            )

        if subscription.expires_at <= now:
            return MySubscriptionResult(
                status="subscription_expired",
                user_id=user.id,
                subscription_id=subscription.id,
                subscription_status=subscription.status.value,
                expires_at=subscription.expires_at,
                device_limit=subscription.device_limit,
                message="Срок подписки истек.",
            )

        config_uri = await self.vpn_access_service.get_config(
            uuid=subscription.uuid,
            device_limit=subscription.device_limit,
        )

        subscription = await self.subscription_repository.mark_access_sent(
            subscription
        )

        await self.session.commit()

        return MySubscriptionResult(
            status="active",
            user_id=user.id,
            subscription_id=subscription.id,
            subscription_status=subscription.status.value,
            expires_at=subscription.expires_at,
            device_limit=subscription.device_limit,
            config_uri=config_uri,
            message="Активная подписка найдена.",
        )