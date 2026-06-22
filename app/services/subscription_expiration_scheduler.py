from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import get_settings
from app.services.subscription_expiration_service import SubscriptionExpirationService

logger = logging.getLogger(__name__)


class SubscriptionExpirationScheduler:
    """
    Background scheduler ??? ??????????????? ????????? ????????.

    ???????? ?????? ???????? ????:
    - ???????????? ???? active-???????? ? expires_at <= now;
    - ????????? ?? ? expired;
    - ????????? metadata sync ?? VPS;
    - ?? ?????? ???? ??? ???????.
    """

    def __init__(
        self,
        session_factory: Callable[[], AsyncSession],
    ) -> None:
        self.session_factory = session_factory
        self.settings = get_settings()

    async def run_forever(self) -> None:
        if not self.settings.subscription_expiration_scheduler_enabled:
            logger.info("Subscription expiration scheduler disabled.")
            return

        interval = self.settings.subscription_expiration_interval_seconds
        initial_delay = self.settings.subscription_expiration_initial_delay_seconds

        logger.info(
            "Subscription expiration scheduler started: interval=%s seconds, initial_delay=%s seconds",
            interval,
            initial_delay,
        )

        if initial_delay > 0:
            await asyncio.sleep(initial_delay)

        while True:
            try:
                await self.run_once()
            except asyncio.CancelledError:
                logger.info("Subscription expiration scheduler cancelled.")
                raise
            except Exception:
                logger.exception("Subscription expiration scheduler iteration failed.")

            await asyncio.sleep(interval)

    async def run_once(self) -> None:
        async with self.session_factory() as session:
            result = await SubscriptionExpirationService(session).expire_due_subscriptions(
                sync_metadata=True,
            )

        if result.expired_count > 0:
            logger.warning(
                "Expired subscriptions processed: count=%s, sync_status=%s, sync_error=%s",
                result.expired_count,
                result.sync_status,
                result.sync_error,
            )

            for item in result.expired_items:
                logger.warning(
                    "Subscription expired automatically: subscription_id=%s user_id=%s uuid=%s expires_at=%s",
                    item.subscription_id,
                    item.user_id,
                    item.uuid,
                    item.expires_at,
                )
        else:
            logger.info(
                "Subscription expiration check completed: no expired active subscriptions."
            )
