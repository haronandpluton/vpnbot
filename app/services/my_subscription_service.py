from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.datetime_utils import is_due_or_past, utc_now
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


@dataclass
class MySubscriptionsResult:
    status: str
    user_id: int | None = None
    subscriptions: tuple[MySubscriptionResult, ...] = ()
    message: str | None = None


class MySubscriptionService:
    """
    User-facing subscription service.

    Важно:
    - просмотр подписок не обновляет last_access_sent_at;
    - выдача доступа не создаёт новый UUID;
    - выдача доступа не продлевает expires_at;
    - доступ выдаётся только владельцу выбранной подписки;
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

    async def get_active_subscriptions_by_telegram_id(
        self,
        telegram_id: int,
    ) -> MySubscriptionsResult:
        """
        Return all subscriptions visible in the user account.

        ACTIVE subscriptions are shown with access controls.
        EXPIRED subscriptions are shown with renewal controls only.
        DISABLED and INACTIVE subscriptions are excluded.
        """
        user = await self.user_repository.get_by_telegram_id(telegram_id)

        if user is None:
            return MySubscriptionsResult(
                status="user_not_found",
                message="Пользователь не найден.",
            )

        subscriptions = (
            await self.subscription_repository.get_renewable_by_user(
                user.id
            )
        )

        if not subscriptions:
            return MySubscriptionsResult(
                status="subscription_not_found",
                user_id=user.id,
                message="Подписки не найдены.",
            )

        active_results: list[MySubscriptionResult] = []
        expired_results: list[MySubscriptionResult] = []

        for subscription in subscriptions:
            result = self._validate_subscription(
                subscription=subscription,
                user_id=user.id,
            )

            if result.status == "active":
                active_results.append(result)
            elif result.status == "subscription_expired":
                expired_results.append(result)

        active_results.sort(
            key=lambda item: (
                item.expires_at.timestamp()
                if item.expires_at is not None
                else float("-inf"),
                item.subscription_id or 0,
            )
        )
        expired_results.sort(
            key=lambda item: (
                item.expires_at.timestamp()
                if item.expires_at is not None
                else float("-inf"),
                item.subscription_id or 0,
            ),
            reverse=True,
        )

        visible_results = active_results + expired_results

        if not visible_results:
            return MySubscriptionsResult(
                status="subscription_not_found",
                user_id=user.id,
                message="Подписки не найдены.",
            )

        # Keep the existing aggregate status for handler compatibility.
        # Individual entries carry either active or subscription_expired.
        return MySubscriptionsResult(
            status="active",
            user_id=user.id,
            subscriptions=tuple(visible_results),
            message="Подписки найдены.",
        )

    async def get_access_by_subscription_id(
        self,
        telegram_id: int,
        subscription_id: int,
    ) -> MySubscriptionResult:
        """
        Возвращает доступ только для выбранной подписки пользователя.

        Защита:
        - чужая подписка не раскрывается;
        - неактивная или истёкшая подписка не выдаётся;
        - UUID и expires_at не изменяются.
        """
        user = await self.user_repository.get_by_telegram_id(telegram_id)

        if user is None:
            return MySubscriptionResult(
                status="user_not_found",
                message="Пользователь не найден.",
            )

        subscription = await self.subscription_repository.get_by_id(subscription_id)

        if subscription is None or subscription.user_id != user.id:
            return MySubscriptionResult(
                status="subscription_not_found",
                user_id=user.id,
                message="Активная подписка не найдена.",
            )

        subscription_result = self._validate_subscription(
            subscription=subscription,
            user_id=user.id,
        )

        if subscription_result.status != "active":
            return subscription_result

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

    async def get_active_subscription_by_telegram_id(
        self,
        telegram_id: int,
    ) -> MySubscriptionResult:
        """
        Legacy-просмотр одной подписки.

        Оставлен для совместимости со старым кодом и тестами.
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
        Legacy-выдача одной подписки.

        Новый пользовательский интерфейс должен вызывать
        get_access_by_subscription_id().
        """
        subscription_result = await self._get_valid_active_subscription_result(
            telegram_id=telegram_id,
        )

        if subscription_result.status != "active":
            return subscription_result

        if subscription_result.subscription_id is None:
            return MySubscriptionResult(
                status="subscription_not_found",
                user_id=subscription_result.user_id,
                message="Активная подписка не найдена.",
            )

        return await self.get_access_by_subscription_id(
            telegram_id=telegram_id,
            subscription_id=subscription_result.subscription_id,
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
        now = utc_now()

        if (
            subscription.status == SubscriptionStatus.EXPIRED
            or (
                subscription.status == SubscriptionStatus.ACTIVE
                and is_due_or_past(subscription.expires_at, now=now)
            )
        ):
            return MySubscriptionResult(
                status="subscription_expired",
                user_id=user_id,
                subscription_id=subscription.id,
                subscription_status=subscription.status.value,
                expires_at=subscription.expires_at,
                device_limit=subscription.device_limit,
                message="Срок подписки истек.",
            )

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

        return MySubscriptionResult(
            status="active",
            user_id=user_id,
            subscription_id=subscription.id,
            subscription_status=subscription.status.value,
            expires_at=subscription.expires_at,
            device_limit=subscription.device_limit,
            message="Активная подписка найдена.",
        )
