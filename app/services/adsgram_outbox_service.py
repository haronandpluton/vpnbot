from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.repositories.adsgram_conversions import (
    AdsGramConversionRepository,
    ClaimedAdsGramConversion,
)
from app.database.repositories.system_errors import (
    SystemErrorRecordRepository,
)
from app.services.adsgram_client import (
    AdsGramAPIError,
    AdsGramClient,
)

logger = logging.getLogger(__name__)

ADSGRAM_DELIVERY_ERROR_TYPE = "adsgram_delivery_failed"


@dataclass(frozen=True, slots=True)
class AdsGramOutboxRunResult:
    stale_requeued: int
    claimed: int
    sent: int
    retried: int
    failed: int
    lost_claim: int
    processing_errors: int


def calculate_adsgram_retry_delay_seconds(
    attempt_count: int,
) -> int:
    exponent = max(0, attempt_count - 1)
    return min(3600, 30 * (2**exponent))


class AdsGramOutboxService:
    def __init__(
        self,
        session: AsyncSession,
        client: AdsGramClient,
        *,
        conversion_repository: (
            AdsGramConversionRepository | None
        ) = None,
        system_error_repository: (
            SystemErrorRecordRepository | None
        ) = None,
        batch_size: int = 50,
        claim_ttl_seconds: int = 900,
        max_attempts: int = 8,
        now_factory: Callable[[], datetime] | None = None,
    ) -> None:
        self.session = session
        self.client = client
        self.conversion_repository = (
            conversion_repository
            or AdsGramConversionRepository(session)
        )
        self.system_error_repository = (
            system_error_repository
            or SystemErrorRecordRepository(session)
        )
        self.batch_size = batch_size
        self.claim_ttl_seconds = claim_ttl_seconds
        self.max_attempts = max_attempts
        self.now_factory = (
            now_factory
            or (lambda: datetime.now(UTC))
        )

    async def run_once(self) -> AdsGramOutboxRunResult:
        now = self.now_factory()
        claim_token = uuid4().hex

        try:
            stale_requeued = (
                await self.conversion_repository
                .requeue_stale_claims(
                    stale_before=now
                    - timedelta(
                        seconds=self.claim_ttl_seconds
                    ),
                    now=now,
                )
            )

            claimed = (
                await self.conversion_repository.claim_due(
                    now=now,
                    limit=self.batch_size,
                    claim_token=claim_token,
                )
            )

            # Важно: транзакция завершена до первого HTTP-запроса.
            await self.session.commit()

        except Exception:
            await self.session.rollback()
            raise

        counters = {
            "sent": 0,
            "retried": 0,
            "failed": 0,
            "lost_claim": 0,
            "processing_errors": 0,
        }

        for conversion in claimed:
            try:
                outcome = await self._deliver_one(
                    conversion
                )
            except Exception:
                counters["processing_errors"] += 1

                try:
                    await self.session.rollback()
                except Exception:
                    logger.exception(
                        "AdsGram outbox rollback failed: "
                        "conversion_id=%s",
                        conversion.id,
                    )

                logger.exception(
                    "AdsGram outbox item processing failed: "
                    "conversion_id=%s user_id=%s "
                    "attempt_count=%s",
                    conversion.id,
                    conversion.user_id,
                    conversion.attempt_count,
                )
                continue

            counters[outcome] += 1

        return AdsGramOutboxRunResult(
            stale_requeued=stale_requeued,
            claimed=len(claimed),
            sent=counters["sent"],
            retried=counters["retried"],
            failed=counters["failed"],
            lost_claim=counters["lost_claim"],
            processing_errors=counters[
                "processing_errors"
            ],
        )

    async def _deliver_one(
        self,
        conversion: ClaimedAdsGramConversion,
    ) -> str:
        try:
            response = await self.client.confirm_conversion(
                telegram_id=conversion.telegram_id,
                campaign_id=conversion.campaign_id,
                goal_type=conversion.goal_type,
            )

        except AdsGramAPIError as error:
            return await self._handle_delivery_failure(
                conversion=conversion,
                error=error,
                retryable=error.retryable,
                http_status=error.status_code,
                response_body=error.response_body,
            )

        except Exception as error:
            # Неожиданная ошибка клиента или адаптера.
            # Сначала считаем её временной, но ограничиваем
            # общее число попыток.
            return await self._handle_delivery_failure(
                conversion=conversion,
                error=error,
                retryable=True,
                http_status=None,
                response_body=None,
            )

        sent_at = self.now_factory()

        updated = (
            await self.conversion_repository.mark_sent(
                conversion_id=conversion.id,
                claim_token=conversion.claim_token,
                sent_at=sent_at,
                http_status=response.status_code,
            )
        )

        await self.session.commit()

        if not updated:
            logger.warning(
                "AdsGram conversion claim was lost before "
                "success persistence: conversion_id=%s",
                conversion.id,
            )
            return "lost_claim"

        logger.info(
            "AdsGram conversion sent: conversion_id=%s "
            "user_id=%s order_id=%s goal_type=%s "
            "attempt_count=%s",
            conversion.id,
            conversion.user_id,
            conversion.order_id,
            conversion.goal_type,
            conversion.attempt_count,
        )

        return "sent"

    async def _handle_delivery_failure(
        self,
        *,
        conversion: ClaimedAdsGramConversion,
        error: Exception,
        retryable: bool,
        http_status: int | None,
        response_body: str | None,
    ) -> str:
        error_message = self._safe_text(
            f"{type(error).__name__}: {error}",
            limit=1000,
        )

        terminal = (
            not retryable
            or conversion.attempt_count
            >= self.max_attempts
        )

        if terminal:
            updated = (
                await self.conversion_repository.mark_failed(
                    conversion_id=conversion.id,
                    claim_token=conversion.claim_token,
                    http_status=http_status,
                    error_message=error_message,
                )
            )

            if updated:
                await self._record_terminal_error(
                    conversion=conversion,
                    error_message=error_message,
                    retryable=retryable,
                    http_status=http_status,
                    response_body=response_body,
                )

            await self.session.commit()

            if not updated:
                logger.warning(
                    "AdsGram conversion claim was lost before "
                    "terminal failure persistence: "
                    "conversion_id=%s",
                    conversion.id,
                )
                return "lost_claim"

            logger.error(
                "AdsGram conversion permanently failed: "
                "conversion_id=%s user_id=%s order_id=%s "
                "goal_type=%s attempt_count=%s "
                "retryable=%s http_status=%s",
                conversion.id,
                conversion.user_id,
                conversion.order_id,
                conversion.goal_type,
                conversion.attempt_count,
                retryable,
                http_status,
            )

            return "failed"

        delay_seconds = (
            calculate_adsgram_retry_delay_seconds(
                conversion.attempt_count
            )
        )
        next_attempt_at = (
            self.now_factory()
            + timedelta(seconds=delay_seconds)
        )

        updated = (
            await self.conversion_repository.mark_retry(
                conversion_id=conversion.id,
                claim_token=conversion.claim_token,
                next_attempt_at=next_attempt_at,
                http_status=http_status,
                error_message=error_message,
            )
        )

        await self.session.commit()

        if not updated:
            logger.warning(
                "AdsGram conversion claim was lost before "
                "retry persistence: conversion_id=%s",
                conversion.id,
            )
            return "lost_claim"

        logger.warning(
            "AdsGram conversion scheduled for retry: "
            "conversion_id=%s attempt_count=%s "
            "delay_seconds=%s http_status=%s",
            conversion.id,
            conversion.attempt_count,
            delay_seconds,
            http_status,
        )

        return "retried"

    async def _record_terminal_error(
        self,
        *,
        conversion: ClaimedAdsGramConversion,
        error_message: str,
        retryable: bool,
        http_status: int | None,
        response_body: str | None,
    ) -> None:
        payload = json.dumps(
            {
                "conversion_id": conversion.id,
                "user_id": conversion.user_id,
                "telegram_id": conversion.telegram_id,
                "order_id": conversion.order_id,
                "campaign_id": conversion.campaign_id,
                "goal_type": conversion.goal_type,
                "attempt_count": conversion.attempt_count,
                "retryable": retryable,
                "http_status": http_status,
                "response_body": self._safe_text(
                    response_body,
                    limit=1000,
                ),
            },
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )

        pending = (
            await self.system_error_repository
            .get_unresolved_by_entity_and_error_type(
                entity_type="adsgram_conversion",
                entity_id=conversion.id,
                error_type=ADSGRAM_DELIVERY_ERROR_TYPE,
            )
        )

        if pending is None:
            await self.system_error_repository.create(
                entity_type="adsgram_conversion",
                entity_id=conversion.id,
                error_type=ADSGRAM_DELIVERY_ERROR_TYPE,
                error_message=error_message,
                payload=payload,
            )
            return

        await self.system_error_repository.update_pending_failure(
            pending,
            entity_type="adsgram_conversion",
            entity_id=conversion.id,
            error_message=error_message,
            payload=payload,
        )

    def _safe_text(
        self,
        value: str | None,
        *,
        limit: int,
    ) -> str | None:
        if value is None:
            return None

        safe_value = value

        token = getattr(
            self.client,
            "api_token",
            "",
        )

        if token:
            safe_value = safe_value.replace(
                token,
                "[REDACTED]",
            )

        return safe_value[:limit]