from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass

from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import get_settings
from app.database.repositories.orders import OrderRepository
from app.database.repositories.payment_events import (
    PaymentEventRepository,
    PendingCryptoBotNotification,
)
from app.database.repositories.system_errors import SystemErrorRecordRepository
from app.services.cryptobot_payment_notification_service import (
    CryptoBotPaymentNotificationService,
)
from app.services.cryptobot_payment_service import CryptoBotPaymentService


logger = logging.getLogger(__name__)

CRYPTOBOT_INVOICE_SYNC_ERROR_TYPE = "cryptobot_invoice_sync_failed"


@dataclass(frozen=True, slots=True)
class CryptoBotBackgroundSyncRunResult:
    orders_selected: int
    orders_checked: int
    order_failures: int
    notifications_selected: int
    notifications_attempted: int
    notifications_delivered: int
    notifications_persisted: int
    notifications_skipped: int
    notification_failures: int


class CryptoBotBackgroundSyncScheduler:
    """
    Periodically synchronizes CryptoBot invoices and notifications.

    Phase 1:
    waiting_payment order -> CryptoBot invoice -> payment event
    -> payment -> subscription.

    Phase 2:
    activated payment event without notification_sent_at
    -> notification lease -> Telegram -> notification_sent_at.
    """

    def __init__(
        self,
        session_factory: Callable[[], AsyncSession],
        bot: Bot,
    ) -> None:
        self.session_factory = session_factory
        self.bot = bot
        self.settings = get_settings()

        self._order_cursor = 0
        self._notification_cursor = 0

    async def run_forever(self) -> None:
        if not self.settings.cryptobot_enabled:
            logger.info(
                "CryptoBot background sync disabled: "
                "CryptoBot integration is disabled."
            )
            return

        if not self.settings.cryptobot_background_sync_enabled:
            logger.info("CryptoBot background sync disabled.")
            return

        interval = (
            self.settings.cryptobot_background_sync_interval_seconds
        )
        initial_delay = (
            self.settings.cryptobot_background_sync_initial_delay_seconds
        )

        logger.info(
            "CryptoBot background sync started: "
            "interval=%s seconds initial_delay=%s seconds batch_size=%s",
            interval,
            initial_delay,
            self.settings.cryptobot_background_sync_batch_size,
        )

        try:
            if initial_delay > 0:
                await asyncio.sleep(initial_delay)

            while True:
                try:
                    await self.run_once()
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception(
                        "CryptoBot background sync iteration failed."
                    )

                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            logger.info("CryptoBot background sync cancelled.")
            raise

    async def run_once(self) -> CryptoBotBackgroundSyncRunResult:
        order_ids = await self._get_pending_order_batch()

        orders_checked = 0
        order_failures = 0

        for order_id in order_ids:
            try:
                async with self.session_factory() as session:
                    await CryptoBotPaymentService(
                        session
                    ).sync_paid_invoice_and_activate(order_id)

                    await self._resolve_order_sync_failure(
                        session=session,
                        order_id=order_id,
                    )

                orders_checked += 1
            except asyncio.CancelledError:
                raise
            except Exception as error:
                order_failures += 1
                logger.exception(
                    "CryptoBot background invoice sync failed: "
                    "order_id=%s",
                    order_id,
                )

                await self._record_order_sync_failure(
                    order_id=order_id,
                    error=error,
                )

        notifications = await self._get_pending_notification_batch()

        notifications_attempted = 0
        notifications_delivered = 0
        notifications_persisted = 0
        notifications_skipped = 0
        notification_failures = 0

        for notification in notifications:
            try:
                async with self.session_factory() as session:
                    service = CryptoBotPaymentNotificationService(session)

                    async def send_message(
                        text: str,
                        *,
                        telegram_id: int = notification.telegram_id,
                    ) -> None:
                        await self.bot.send_message(
                            chat_id=telegram_id,
                            text=text,
                        )

                    delivery = await service.deliver(
                        event_id=notification.event_id,
                        order_id=notification.order_id,
                        telegram_id=notification.telegram_id,
                        send_message=send_message,
                    )

                if delivery.attempted:
                    notifications_attempted += 1
                else:
                    notifications_skipped += 1

                if delivery.delivered:
                    notifications_delivered += 1

                if delivery.persisted:
                    notifications_persisted += 1
                elif delivery.attempted:
                    notification_failures += 1

            except asyncio.CancelledError:
                # The notification claim remains committed and will become
                # available again only after its TTL expires.
                raise
            except Exception:
                notification_failures += 1
                logger.exception(
                    "CryptoBot background notification failed: "
                    "event_id=%s order_id=%s telegram_id=%s",
                    notification.event_id,
                    notification.order_id,
                    notification.telegram_id,
                )

        result = CryptoBotBackgroundSyncRunResult(
            orders_selected=len(order_ids),
            orders_checked=orders_checked,
            order_failures=order_failures,
            notifications_selected=len(notifications),
            notifications_attempted=notifications_attempted,
            notifications_delivered=notifications_delivered,
            notifications_persisted=notifications_persisted,
            notifications_skipped=notifications_skipped,
            notification_failures=notification_failures,
        )

        if (
            result.orders_selected > 0
            or result.notifications_selected > 0
            or result.order_failures > 0
            or result.notification_failures > 0
        ):
            logger.info(
                "CryptoBot background sync completed: "
                "orders_selected=%s orders_checked=%s "
                "order_failures=%s notifications_selected=%s "
                "notifications_attempted=%s "
                "notifications_delivered=%s "
                "notifications_persisted=%s "
                "notifications_skipped=%s "
                "notification_failures=%s",
                result.orders_selected,
                result.orders_checked,
                result.order_failures,
                result.notifications_selected,
                result.notifications_attempted,
                result.notifications_delivered,
                result.notifications_persisted,
                result.notifications_skipped,
                result.notification_failures,
            )
        else:
            logger.debug(
                "CryptoBot background sync completed: no pending work."
            )

        return result

    async def _record_order_sync_failure(
        self,
        *,
        order_id: int,
        error: Exception,
    ) -> None:
        error_message = f"{type(error).__name__}: {error}"[:1000]
        payload = json.dumps(
            {
                "order_id": order_id,
                "phase": "invoice_sync",
                "error_class": type(error).__name__,
                "error_message": str(error)[:1000],
            },
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )

        try:
            async with self.session_factory() as session:
                try:
                    repository = SystemErrorRecordRepository(session)
                    pending = (
                        await repository
                        .get_unresolved_by_entity_and_error_type(
                            entity_type="order",
                            entity_id=order_id,
                            error_type=CRYPTOBOT_INVOICE_SYNC_ERROR_TYPE,
                        )
                    )

                    if pending is None:
                        await repository.create(
                            entity_type="order",
                            entity_id=order_id,
                            error_type=CRYPTOBOT_INVOICE_SYNC_ERROR_TYPE,
                            error_message=error_message,
                            payload=payload,
                        )
                    else:
                        await repository.update_pending_failure(
                            pending,
                            entity_type="order",
                            entity_id=order_id,
                            error_message=error_message,
                            payload=payload,
                        )

                    await session.commit()
                except asyncio.CancelledError:
                    raise
                except Exception:
                    await session.rollback()
                    raise
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "Failed to persist CryptoBot invoice sync system error: "
                "order_id=%s",
                order_id,
            )

    async def _resolve_order_sync_failure(
        self,
        *,
        session: AsyncSession,
        order_id: int,
    ) -> None:
        try:
            repository = SystemErrorRecordRepository(session)
            pending = (
                await repository.get_unresolved_by_entity_and_error_type(
                    entity_type="order",
                    entity_id=order_id,
                    error_type=CRYPTOBOT_INVOICE_SYNC_ERROR_TYPE,
                )
            )

            if pending is not None:
                await repository.mark_resolved(pending)

            await session.commit()
        except asyncio.CancelledError:
            raise
        except Exception:
            try:
                await session.rollback()
            except Exception:
                logger.exception(
                    "Failed to rollback CryptoBot system-error "
                    "resolution transaction: order_id=%s",
                    order_id,
                )

            logger.exception(
                "Failed to resolve CryptoBot invoice sync system error: "
                "order_id=%s",
                order_id,
            )

    async def _get_pending_order_batch(self) -> list[int]:
        batch_size = self.settings.cryptobot_background_sync_batch_size

        async with self.session_factory() as session:
            repository = OrderRepository(session)
            order_ids = await repository.get_pending_cryptobot_order_ids(
                limit=batch_size,
                after_id=self._order_cursor,
            )

            if not order_ids and self._order_cursor > 0:
                self._order_cursor = 0
                order_ids = (
                    await repository.get_pending_cryptobot_order_ids(
                        limit=batch_size,
                        after_id=0,
                    )
                )

        if order_ids:
            self._order_cursor = order_ids[-1]

        return order_ids

    async def _get_pending_notification_batch(
        self,
    ) -> list[PendingCryptoBotNotification]:
        batch_size = self.settings.cryptobot_background_sync_batch_size

        async with self.session_factory() as session:
            repository = PaymentEventRepository(session)
            notifications = (
                await repository.get_pending_cryptobot_notifications(
                    limit=batch_size,
                    after_event_id=self._notification_cursor,
                )
            )

            if not notifications and self._notification_cursor > 0:
                self._notification_cursor = 0
                notifications = (
                    await repository.get_pending_cryptobot_notifications(
                        limit=batch_size,
                        after_event_id=0,
                    )
                )

        if notifications:
            self._notification_cursor = notifications[-1].event_id

        return notifications
