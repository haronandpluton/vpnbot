from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Subscription
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
    """
    User-facing subscription service.

    Важно:
    - просмотр подписки не должен обновлять last_access_sent_at;
    - выдача / повторная выдача доступа не должна создавать новый UUID;
    - выдача / повторная выдача доступа не должна продлевать expires_at;
    - единственная мутация при выдаче доступа: last_access_sent_at.
    """

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
        """
        Только просмотр состояния подписки.

        Не генерирует config_uri.
        Не обновляет last_access_sent_at.
        Не делает commit.
        """
        subscription_result = await self._get_valid_active_subscription_result(
            telegram_id=telegram_id,
        )

        if subscription_result.status != "active":
            return subscription_result

        return subscription_result

    async def get_access_by_telegram_id(
        self,
        telegram_id: int,
    ) -> MySubscriptionResult:
        """
        Выдача или повторная выдача существующего доступа.

        Безопасно:
        - не создает новый VPN-доступ;
        - не создает новый UUID;
        - не продлевает подписку;
        - только возвращает существующий connect_url;
        - обновляет last_access_sent_at.
        """
        subscription_result = await self._get_valid_active_subscription_result(
            telegram_id=telegram_id,
        )

        if subscription_result.status != "active":
            return subscription_result

        subscription = await self.subscription_repository.get_by_id(
            subscription_result.subscription_id
        )

        if subscription is None:
            return MySubscriptionResult(
                status="subscription_not_found",
                user_id=subscription_result.user_id,
                message="Активная подписка не найдена.",
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
            user_id=subscription.user_id,
            subscription_id=subscription.id,
            subscription_status=subscription.status.value,
            expires_at=subscription.expires_at,
            device_limit=subscription.device_limit,
            config_uri=config_uri,
            message="Доступ отправлен повторно.",
        )

    async def _get_valid_active_subscription_result(
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

        return self._validate_subscription(
            subscription=subscription,
            user_id=user.id,
        )

    def _validate_subscription(
        self,
        subscription: Subscription,
        user_id: int,
    ) -> MySubscriptionResult:
        now = datetime.now(timezone.utc)

        if subscription.status != SubscriptionStatus.ACTIVE:
            return MySubscriptionResult(
                status="subscription_not_active",
                user_id=user_id,
                subscription_id=subscription.id,
                subscription_status=subscription.status.value,
                expires_at=subscription.expires_at,
                device_limit=subscription.device_limit,
                message="Подписка не активна.",
            )

        if subscription.expires_at <= now:
            return MySubscriptionResult(
                status="subscription_expired",
                user_id=user_id,
                subscription_id=subscription.id,
                subscription_status=subscription.status.value,
                expires_at=subscription.expires_at,
                device_limit=subscription.device_limit,
                message="Срок подписки истек.",
            )

        return MySubscriptionResult(
            status="active",
            user_id=user_id,
            subscription_id=subscription.id,
            subscription_status=subscription.status.value,
            expires_at=subscription.expires_at,
            device_limit=subscription.device_limit,
            message="Активная подписка найдена.",
        )