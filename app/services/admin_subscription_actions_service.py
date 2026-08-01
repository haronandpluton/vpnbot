import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Subscription
from app.payment_core.enums.subscription_status import SubscriptionStatus
from app.services.admin_action_log_service import AdminActionLogService
from app.services.subscription_meta_sync_service import SubscriptionMetaSyncService
from app.services.vpn_access_service import VpnAccessService


logger = logging.getLogger(__name__)


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
    admin_action_id: int | None = None
    vpn_sync_ok: bool | None = None
    vpn_sync_error: str | None = None
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
    admin_action_id: int | None = None
    vpn_sync_ok: bool | None = None
    vpn_sync_error: str | None = None
    message: str | None = None


class AdminSubscriptionActionsService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        vpn_access_service: VpnAccessService | None = None,
    ) -> None:
        self.session = session
        self.action_log_service = AdminActionLogService(session)
        self.vpn_access_service = vpn_access_service

    async def extend_subscription(
        self,
        subscription_id: int,
        days: int,
        admin_telegram_id: int,
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

        if old_expires_at is None or old_expires_at <= now:
            base_date = now
        else:
            base_date = old_expires_at

        new_expires_at = base_date + timedelta(days=days)

        subscription.expires_at = new_expires_at
        subscription.updated_at = now

        payload = (
            f"old_expires_at={old_expires_at}; "
            f"new_expires_at={new_expires_at}; "
            f"days={days}"
        )

        action_result = await self.action_log_service.create_action_by_admin_telegram_id(
            admin_telegram_id=admin_telegram_id,
            action_type="manual_extend_subscription",
            target_user_id=subscription.user_id,
            order_id=subscription.order_id,
            subscription_id=subscription.id,
            reason=f"extend_days:{days}",
            payload=payload,
            commit=False,
        )

        if action_result.status != "created":
            await self.session.rollback()
            return AdminExtendSubscriptionResult(
                status=action_result.status,
                subscription_id=subscription_id,
                days=days,
                old_expires_at=old_expires_at,
                new_expires_at=new_expires_at,
                user_id=subscription.user_id,
                order_id=subscription.order_id,
                uuid=subscription.uuid,
                message=action_result.message,
            )

        await self.session.commit()
        await self.session.refresh(subscription)

        vpn_sync_ok = True
        vpn_sync_error = None

        try:
            vpn_access_service = self.vpn_access_service or VpnAccessService()
            await vpn_access_service.extend_access(
                uuid=subscription.uuid,
                device_limit=subscription.device_limit,
                expires_at=subscription.expires_at,
            )
        except Exception as error:  # noqa: BLE001 - external VPN boundary
            vpn_sync_ok = False
            vpn_sync_error = str(error)
            logger.exception(
                "Manual subscription extension was committed, but VPN node "
                "synchronization failed: subscription_id=%s uuid=%s",
                subscription.id,
                subscription.uuid,
            )

        result = AdminExtendSubscriptionResult(
            status="extended",
            subscription_id=subscription.id,
            days=days,
            old_expires_at=old_expires_at,
            new_expires_at=subscription.expires_at,
            user_id=subscription.user_id,
            order_id=subscription.order_id,
            uuid=subscription.uuid,
            admin_action_id=action_result.action_id,
            vpn_sync_ok=vpn_sync_ok,
            vpn_sync_error=vpn_sync_error,
            message=(
                "Subscription extended."
                if vpn_sync_ok
                else "Subscription extended; VPN synchronization failed."
            ),
        )

        await SubscriptionMetaSyncService(self.session).sync_safely(
            entity_type="subscription",
            entity_id=subscription.id,
            reason="manual_extend_subscription",
            payload={
                "subscription_id": subscription.id,
                "user_id": subscription.user_id,
                "order_id": subscription.order_id,
                "uuid": subscription.uuid,
                "old_expires_at": None
                if old_expires_at is None
                else old_expires_at.isoformat(),
                "new_expires_at": None
                if result.new_expires_at is None
                else result.new_expires_at.isoformat(),
                "days": days,
                "admin_action_id": action_result.action_id,
            },
        )

        return result

    async def disable_subscription(
        self,
        subscription_id: int,
        reason: str,
        admin_telegram_id: int,
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
        already_disabled = old_status == SubscriptionStatus.DISABLED.value

        subscription.status = SubscriptionStatus.DISABLED
        if subscription.disabled_at is None:
            subscription.disabled_at = now
        if not already_disabled or not subscription.error_reason:
            subscription.error_reason = clean_reason
        subscription.updated_at = now

        payload = (
            f"old_status={old_status}; "
            f"new_status={SubscriptionStatus.DISABLED.value}; "
            f"disabled_at={subscription.disabled_at}; "
            f"already_disabled={already_disabled}"
        )

        action_result = await self.action_log_service.create_action_by_admin_telegram_id(
            admin_telegram_id=admin_telegram_id,
            action_type="manual_disable_subscription",
            target_user_id=subscription.user_id,
            order_id=subscription.order_id,
            subscription_id=subscription.id,
            reason=clean_reason,
            payload=payload,
            commit=False,
        )

        if action_result.status != "created":
            await self.session.rollback()
            return AdminDisableSubscriptionResult(
                status=action_result.status,
                subscription_id=subscription_id,
                old_status=old_status,
                new_status=SubscriptionStatus.DISABLED.value,
                user_id=subscription.user_id,
                order_id=subscription.order_id,
                uuid=subscription.uuid,
                disabled_at=now,
                reason=clean_reason,
                message=action_result.message,
            )

        await self.session.commit()
        await self.session.refresh(subscription)

        vpn_sync_ok = True
        vpn_sync_error = None

        try:
            vpn_access_service = self.vpn_access_service or VpnAccessService()
            await vpn_access_service.disable_access(uuid=subscription.uuid)
        except Exception as error:  # noqa: BLE001 - external VPN boundary
            vpn_sync_ok = False
            vpn_sync_error = str(error)
            logger.exception(
                "Manual subscription disable was committed, but VPN node "
                "synchronization failed: subscription_id=%s uuid=%s",
                subscription.id,
                subscription.uuid,
            )

        result = AdminDisableSubscriptionResult(
            status="disabled",
            subscription_id=subscription.id,
            old_status=old_status,
            new_status=self._enum_to_str(subscription.status),
            user_id=subscription.user_id,
            order_id=subscription.order_id,
            uuid=subscription.uuid,
            disabled_at=subscription.disabled_at,
            reason=subscription.error_reason,
            admin_action_id=action_result.action_id,
            vpn_sync_ok=vpn_sync_ok,
            vpn_sync_error=vpn_sync_error,
            message=(
                "Subscription disabled."
                if vpn_sync_ok
                else "Subscription disabled; VPN synchronization failed."
            ),
        )

        await SubscriptionMetaSyncService(self.session).sync_safely(
            entity_type="subscription",
            entity_id=subscription.id,
            reason="manual_disable_subscription",
            payload={
                "subscription_id": subscription.id,
                "user_id": subscription.user_id,
                "order_id": subscription.order_id,
                "uuid": subscription.uuid,
                "old_status": old_status,
                "new_status": result.new_status,
                "disabled_at": None
                if result.disabled_at is None
                else result.disabled_at.isoformat(),
                "reason": clean_reason,
                "admin_action_id": action_result.action_id,
            },
        )

        return result

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