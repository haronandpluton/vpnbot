from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import get_settings
from app.services.adsgram_client import AdsGramClient
from app.services.adsgram_outbox_service import (
    AdsGramOutboxRunResult,
    AdsGramOutboxService,
)

logger = logging.getLogger(__name__)


class AdsGramOutboxScheduler:
    """Periodically delivers pending AdsGram conversions."""

    def __init__(
        self,
        session_factory: Callable[[], AsyncSession],
    ) -> None:
        self.session_factory = session_factory
        self.settings = get_settings()

    async def run_forever(self) -> None:
        if not self.settings.adsgram_enabled:
            logger.info("AdsGram outbox scheduler disabled.")
            return

        interval = (
            self.settings.adsgram_scheduler_interval_seconds
        )
        initial_delay = (
            self.settings
            .adsgram_scheduler_initial_delay_seconds
        )

        logger.info(
            "AdsGram outbox scheduler started: "
            "interval=%s seconds initial_delay=%s seconds "
            "batch_size=%s max_attempts=%s",
            interval,
            initial_delay,
            self.settings.adsgram_scheduler_batch_size,
            self.settings.adsgram_max_attempts,
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
                        "AdsGram outbox scheduler "
                        "iteration failed."
                    )

                await asyncio.sleep(interval)

        except asyncio.CancelledError:
            logger.info(
                "AdsGram outbox scheduler cancelled."
            )
            raise

    async def run_once(
        self,
    ) -> AdsGramOutboxRunResult:
        client = AdsGramClient(
            api_url=self.settings.adsgram_api_url,
            api_token=self.settings.adsgram_api_token,
            timeout_seconds=(
                self.settings
                .adsgram_request_timeout_seconds
            ),
        )

        async with self.session_factory() as session:
            result = await AdsGramOutboxService(
                session,
                client,
                batch_size=(
                    self.settings
                    .adsgram_scheduler_batch_size
                ),
                claim_ttl_seconds=(
                    self.settings.adsgram_claim_ttl_seconds
                ),
                max_attempts=(
                    self.settings.adsgram_max_attempts
                ),
            ).run_once()

        if (
            result.claimed == 0
            and result.stale_requeued == 0
        ):
            logger.debug(
                "AdsGram outbox check completed: "
                "no due conversions."
            )
            return result

        has_warning = any(
            (
                result.stale_requeued,
                result.retried,
                result.failed,
                result.lost_claim,
                result.processing_errors,
            )
        )

        log = (
            logger.warning
            if has_warning
            else logger.info
        )

        log(
            "AdsGram outbox iteration completed: "
            "stale_requeued=%s claimed=%s sent=%s "
            "retried=%s failed=%s lost_claim=%s "
            "processing_errors=%s",
            result.stale_requeued,
            result.claimed,
            result.sent,
            result.retried,
            result.failed,
            result.lost_claim,
            result.processing_errors,
        )

        return result