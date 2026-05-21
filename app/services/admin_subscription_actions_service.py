from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Subscription
from app.payment_core.enums.subscription_status import SubscriptionStatus


@dataclass
class AdminExtendSubscriptionResult:
    status: str
    subscription_id: int
    days: int
    old_expires_at: datetime | None = None
    new_expires_at: datetime | None = None
    user_id: int | None = None
    order_id: int | None = None
    uuid: str | None = None
    message: str | None = None


@dataclass
class AdminDisableSubscriptionResult:
    status: str
    subscription_id: int
    old_status: str | None = None
    new_status: str | None = None
    user_id: int | None = None
    order_id: int | None = None
    uuid: str | None = None
    disabled_at: datetime | None = None
    reason: str | None = None
    message: str | None = None


class AdminSubscriptionActionsService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def extend_subscription(
        self,
        subscription_id: int,
        days: int,
    ) -> AdminExtendSubscriptionResult:
        if days <= 0:
            return AdminExtendSubscriptionResult(
                status="invalid_days",
                subscription_id=subscription_id,
                days=days,
                message="Days must be greater than zero.",
            )

        subscription = await self._get_subscription(subscription_id)

        if subscription is None:
            return AdminExtendSubscriptionResult(
                status="subscription_not_found",
                subscription_id=subscription_id,
                days=days,
                message="Subscription not found.",
            )

        old_expires_at = subscription.expires_at
        now = datetime.now(timezone.utc)

        if old_expires_at is None:
            base_date = now
        elif old_expires_at <= now:
            base_date = now
        else:
            base_date = old_expires_at

        new_expires_at = base_date + timedelta(days=days)

        subscription.expires_at = new_expires_at
        subscription.updated_at = now

        await self.session.commit()
        await self.session.refresh(subscription)

        return AdminExtendSubscriptionResult(
            status="extended",
            subscription_id=subscription.id,
            days=days,
            old_expires_at=old_expires_at,
            new_expires_at=subscription.expires_at,
            user_id=subscription.user_id,
            order_id=subscription.order_id,
            uuid=subscription.uuid,
            message="Subscription extended.",
        )

    async def disable_subscription(
        self,
        subscription_id: int,
        reason: str,
    ) -> AdminDisableSubscriptionResult:
        clean_reason = reason.strip()

        if not clean_reason:
            return AdminDisableSubscriptionResult(
                status="invalid_reason",
                subscription_id=subscription_id,
                message="Reason is required.",
            )

        subscription = await self._get_subscription(subscription_id)

        if subscription is None:
            return AdminDisableSubscriptionResult(
                status="subscription_not_found",
                subscription_id=subscription_id,
                reason=clean_reason,
                message="Subscription not found.",
            )

        old_status = self._enum_to_str(subscription.status)
        now = datetime.now(timezone.utc)

        subscription.status = SubscriptionStatus.DISABLED
        subscription.disabled_at = now
        subscription.error_reason = clean_reason
        subscription.updated_at = now

        await self.session.commit()
        await self.session.refresh(subscription)

        return AdminDisableSubscriptionResult(
            status="disabled",
            subscription_id=subscription.id,
            old_status=old_status,
            new_status=self._enum_to_str(subscription.status),
            user_id=subscription.user_id,
            order_id=subscription.order_id,
            uuid=subscription.uuid,
            disabled_at=subscription.disabled_at,
            reason=subscription.error_reason,
            message="Subscription disabled.",
        )

    async def _get_subscription(self, subscription_id: int) -> Subscription | None:
        result = await self.session.execute(
            select(Subscription).where(Subscription.id == subscription_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    def _enum_to_str(value) -> str | None:
        if value is None:
            return None

        if hasattr(value, "value"):
            return str(value.value)

        return str(value)