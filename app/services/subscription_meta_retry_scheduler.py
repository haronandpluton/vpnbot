from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import get_settings
from app.services.subscription_meta_sync_service import SubscriptionMetaSyncService

logger = logging.getLogger(__name__)


class SubscriptionMetaRetryScheduler:
    """Retries failed ZA metadata snapshots recorded in system_errors."""

    def __init__(
        self,
        session_factory: Callable[[], AsyncSession],
    ) -> None:
        self.session_factory = session_factory
        self.settings = get_settings()

    async def run_forever(self) -> None:
        if not self.settings.subscription_meta_retry_scheduler_enabled:
            logger.info("Subscription metadata retry scheduler disabled.")
            return

        interval = self.settings.subscription_meta_retry_interval_seconds
        initial_delay = self.settings.subscription_meta_retry_initial_delay_seconds

        logger.info(
            "Subscription metadata retry scheduler started: "
            "interval=%s seconds, initial_delay=%s seconds",
            interval,
            initial_delay,
        )

        if initial_delay > 0:
            await asyncio.sleep(initial_delay)

        while True:
            try:
                await self.run_once()
            except asyncio.CancelledError:
                logger.info("Subscription metadata retry scheduler cancelled.")
                raise
            except Exception:
                logger.exception(
                    "Subscription metadata retry scheduler iteration failed."
                )

            await asyncio.sleep(interval)

    async def run_once(self) -> None:
        async with self.session_factory() as session:
            result = await SubscriptionMetaSyncService(session).retry_pending()

        if not result.attempted:
            logger.debug("No pending subscription metadata sync errors.")
            return

        if result.ok:
            logger.info(
                "Subscription metadata retry succeeded: "
                "pending_count=%s resolved_count=%s exported_count=%s skipped_count=%s",
                result.pending_count,
                result.resolved_count,
                None
                if result.sync_result is None
                else result.sync_result.exported_count,
                None
                if result.sync_result is None
                else result.sync_result.skipped_count,
            )
            return

        logger.warning(
            "Subscription metadata retry failed: pending_count=%s error=%s",
            result.pending_count,
            result.error,
        )
