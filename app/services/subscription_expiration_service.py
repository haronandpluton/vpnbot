from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models.subscription import Subscription
from app.payment_core.enums.subscription_status import SubscriptionStatus


@dataclass
class ExpiredSubscriptionItem:
    subscription_id: int
    user_id: int
    order_id: int | None
    uuid: str
    old_status: str
    new_status: str
    expires_at: datetime


@dataclass
class ExpireSubscriptionsResult:
    status: str
    checked_at: datetime
    expired_count: int = 0
    expired_items: list[ExpiredSubscriptionItem] = field(default_factory=list)
    sync_status: str | None = None
    sync_error: str | None = None
    message: str | None = None


class SubscriptionExpirationService:
    """
    Переводит просроченные active-подписки в expired.

    Правило:
    status = active AND expires_at <= now
    ->
    status = expired

    После изменения статусов пытается синхронизировать metadata на VPS.
    Ошибка sync не откатывает истечение подписок.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def expire_due_subscriptions(
        self,
        now: datetime | None = None,
        sync_metadata: bool = True,
    ) -> ExpireSubscriptionsResult:
        checked_at = now or datetime.now(timezone.utc)

        stmt = (
            select(Subscription)
            .where(
                Subscription.status == SubscriptionStatus.ACTIVE,
                Subscription.expires_at <= checked_at,
            )
            .order_by(Subscription.expires_at.asc())
        )

        result = await self.session.execute(stmt)
        subscriptions = list(result.scalars().all())

        if not subscriptions:
            return ExpireSubscriptionsResult(
                status="no_expired_subscriptions",
                checked_at=checked_at,
                expired_count=0,
                message="No active subscriptions are expired.",
            )

        expired_items: list[ExpiredSubscriptionItem] = []

        for subscription in subscriptions:
            old_status = self._enum_to_str(subscription.status)

            subscription.status = SubscriptionStatus.EXPIRED
            subscription.error_reason = None
            subscription.updated_at = checked_at

            expired_items.append(
                ExpiredSubscriptionItem(
                    subscription_id=subscription.id,
                    user_id=subscription.user_id,
                    order_id=subscription.order_id,
                    uuid=subscription.uuid,
                    old_status=old_status,
                    new_status=SubscriptionStatus.EXPIRED.value,
                    expires_at=subscription.expires_at,
                )
            )

        await self.session.commit()

        sync_status: str | None = None
        sync_error: str | None = None

        if sync_metadata:
            try:
                sync_result = await self._sync_metadata_safely()
                sync_status = self._sync_result_to_text(sync_result)
            except Exception as exc:
                sync_status = "sync_failed"
                sync_error = str(exc)

        return ExpireSubscriptionsResult(
            status="expired",
            checked_at=checked_at,
            expired_count=len(expired_items),
            expired_items=expired_items,
            sync_status=sync_status,
            sync_error=sync_error,
            message="Expired subscriptions processed.",
        )

    async def _sync_metadata_safely(self) -> Any:
        """
        Вызывает уже существующий metadata sync.

        В проекте уже есть SubscriptionMetaSyncService и sync_safely().
        Импорт держим внутри метода, чтобы сервис истечения не ломал импорт проекта,
        если sync-модуль временно меняется.
        """
        from app.services.subscription_meta_sync_service import SubscriptionMetaSyncService

        sync_service = SubscriptionMetaSyncService(self.session)

        if hasattr(sync_service, "sync_safely"):
            return await sync_service.sync_safely(
                entity_type="subscription_expiration",
                entity_id=0,
                reason="expire_due_subscriptions",
            )

        if hasattr(sync_service, "sync"):
            return await sync_service.sync()

        if hasattr(sync_service, "sync_all"):
            return await sync_service.sync_all()

        raise RuntimeError(
            "SubscriptionMetaSyncService has no sync_safely(), sync() or sync_all() method."
        )

    @staticmethod
    def _enum_to_str(value: Any) -> str:
        if hasattr(value, "value"):
            return str(value.value)
        return str(value)

    @staticmethod
    def _sync_result_to_text(sync_result: Any) -> str:
        if sync_result is None:
            return "sync_ok"

        status = getattr(sync_result, "status", None)
        exported = getattr(sync_result, "exported", None)
        skipped = getattr(sync_result, "skipped", None)

        parts = []

        if status is not None:
            parts.append(f"status={status}")

        if exported is not None:
            parts.append(f"exported={exported}")

        if skipped is not None:
            parts.append(f"skipped={skipped}")

        if parts:
            return "; ".join(parts)

        return str(sync_result)
