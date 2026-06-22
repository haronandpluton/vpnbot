from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import get_settings
from app.services.order_expiration_service import OrderExpirationService

logger = logging.getLogger(__name__)


class OrderExpirationScheduler:
    """
    Background scheduler для автоматического истечения неоплаченных заказов.

    Работает внутри процесса бота:
    - периодически ищет created/waiting_payment orders с expires_at <= now;
    - переводит их в expired;
    - не трогает paid/activated orders;
    - не роняет бота при ошибках.
    """

    def __init__(
        self,
        session_factory: Callable[[], AsyncSession],
    ) -> None:
        self.session_factory = session_factory
        self.settings = get_settings()

    async def run_forever(self) -> None:
        if not self.settings.order_expiration_scheduler_enabled:
            logger.info("Order expiration scheduler disabled.")
            return

        interval = self.settings.order_expiration_interval_seconds
        initial_delay = self.settings.order_expiration_initial_delay_seconds

        logger.info(
            "Order expiration scheduler started: interval=%s seconds, initial_delay=%s seconds",
            interval,
            initial_delay,
        )

        if initial_delay > 0:
            await asyncio.sleep(initial_delay)

        while True:
            try:
                await self.run_once()
            except asyncio.CancelledError:
                logger.info("Order expiration scheduler cancelled.")
                raise
            except Exception:
                logger.exception("Order expiration scheduler iteration failed.")

            await asyncio.sleep(interval)

    async def run_once(self) -> None:
        async with self.session_factory() as session:
            result = await OrderExpirationService(session).expire_due_orders()

        if result.expired_count > 0:
            logger.warning(
                "Expired unpaid orders processed: count=%s",
                result.expired_count,
            )

            for item in result.expired_items:
                logger.warning(
                    "Order expired automatically: order_id=%s user_id=%s %s->%s expires_at=%s",
                    item.order_id,
                    item.user_id,
                    item.old_status,
                    item.new_status,
                    item.expires_at,
                )
        else:
            logger.info(
                "Order expiration check completed: no expired unpaid orders."
            )