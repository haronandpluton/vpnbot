from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import get_settings
from app.database.repositories.payment_events import PaymentEventRepository
from app.database.repositories.system_errors import SystemErrorRecordRepository


logger = logging.getLogger(__name__)

CRYPTOBOT_NOTIFICATION_ERROR_TYPE = "cryptobot_notification_failed"

CRYPTOBOT_PAYMENT_CONFIRMED_TEXT = (
    "Payment confirmed. VPN access is active. "
    "Open “My Subscription” and click “Connect VPN”."
)

NotificationSender = Callable[[str], Awaitable[Any]]


@dataclass(frozen=True, slots=True)
class CryptoBotNotificationDeliveryResult:
    attempted: bool
    delivered: bool
    persisted: bool
    reason: str | None = None


class CryptoBotPaymentNotificationService:
    """
    Delivers one CryptoBot activation notification using a durable lease.

    The notification claim is committed before calling Telegram, so no
    database transaction or row lock remains open during the network request.
    """

    def __init__(
        self,
        session: AsyncSession,
        *,
        payment_event_repository: PaymentEventRepository | None = None,
        system_error_repository: SystemErrorRecordRepository | None = None,
        settings=None,
    ) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.payment_event_repository = (
            payment_event_repository
            if payment_event_repository is not None
            else PaymentEventRepository(session)
        )
        self.system_error_repository = (
            system_error_repository
            if system_error_repository is not None
            else SystemErrorRecordRepository(session)
        )

    async def deliver(
        self,
        *,
        event_id: int,
        order_id: int,
        telegram_id: int,
        send_message: NotificationSender,
    ) -> CryptoBotNotificationDeliveryResult:
        claimed_at = datetime.now(UTC)
        stale_before = claimed_at - timedelta(
            seconds=self.settings.cryptobot_notification_claim_ttl_seconds
        )
        claim_token = uuid4().hex

        try:
            claimed = await self.payment_event_repository.claim_notification(
                event_id,
                claim_token=claim_token,
                claimed_at=claimed_at,
                stale_before=stale_before,
            )
            await self.session.commit()
        except Exception:
            await self._rollback_safely()
            logger.exception(
                "CryptoBot notification claim failed: "
                "event_id=%s order_id=%s telegram_id=%s",
                event_id,
                order_id,
                telegram_id,
            )
            raise

        if not claimed:
            return CryptoBotNotificationDeliveryResult(
                attempted=False,
                delivered=False,
                persisted=False,
                reason="not_claimed",
            )

        try:
            await send_message(CRYPTOBOT_PAYMENT_CONFIRMED_TEXT)
        except asyncio.CancelledError:
            # Delivery outcome is ambiguous during task cancellation.
            # Keep the committed claim until its TTL expires instead of
            # releasing it and risking an immediate duplicate notification.
            logger.warning(
                "CryptoBot notification delivery cancelled; "
                "claim retained until TTL: "
                "event_id=%s order_id=%s telegram_id=%s",
                event_id,
                order_id,
                telegram_id,
            )
            raise
        except Exception as error:
            logger.exception(
                "CryptoBot activation notification delivery failed: "
                "event_id=%s order_id=%s telegram_id=%s",
                event_id,
                order_id,
                telegram_id,
            )

            await self._release_claim(
                event_id=event_id,
                claim_token=claim_token,
            )
            await self._record_failure(
                event_id=event_id,
                order_id=order_id,
                telegram_id=telegram_id,
                phase="send",
                error=error,
            )

            return CryptoBotNotificationDeliveryResult(
                attempted=True,
                delivered=False,
                persisted=False,
                reason="send_failed",
            )

        try:
            persisted = (
                await self.payment_event_repository.mark_notification_sent(
                    event_id,
                    claim_token=claim_token,
                )
            )
            await self.session.commit()
        except Exception as error:
            await self._rollback_safely()

            logger.exception(
                "CryptoBot notification finalization failed after delivery: "
                "event_id=%s order_id=%s telegram_id=%s",
                event_id,
                order_id,
                telegram_id,
            )

            await self._record_failure(
                event_id=event_id,
                order_id=order_id,
                telegram_id=telegram_id,
                phase="finalize",
                error=error,
            )

            return CryptoBotNotificationDeliveryResult(
                attempted=True,
                delivered=True,
                persisted=False,
                reason="finalize_failed",
            )

        if not persisted:
            error = RuntimeError(
                "Notification claim was lost before delivery finalization"
            )

            logger.error(
                "CryptoBot notification claim lost after delivery: "
                "event_id=%s order_id=%s telegram_id=%s",
                event_id,
                order_id,
                telegram_id,
            )

            await self._record_failure(
                event_id=event_id,
                order_id=order_id,
                telegram_id=telegram_id,
                phase="finalize",
                error=error,
            )

            return CryptoBotNotificationDeliveryResult(
                attempted=True,
                delivered=True,
                persisted=False,
                reason="claim_lost",
            )

        await self._resolve_failure(event_id)

        return CryptoBotNotificationDeliveryResult(
            attempted=True,
            delivered=True,
            persisted=True,
        )

    async def _release_claim(
        self,
        *,
        event_id: int,
        claim_token: str,
    ) -> None:
        try:
            await self.payment_event_repository.release_notification_claim(
                event_id,
                claim_token=claim_token,
            )
            await self.session.commit()
        except Exception:
            await self._rollback_safely()
            logger.exception(
                "Failed to release CryptoBot notification claim: "
                "event_id=%s",
                event_id,
            )

    async def _record_failure(
        self,
        *,
        event_id: int,
        order_id: int,
        telegram_id: int,
        phase: str,
        error: Exception,
    ) -> None:
        error_message = f"{type(error).__name__}: {error}"[:1000]
        payload = json.dumps(
            {
                "payment_event_id": event_id,
                "order_id": order_id,
                "telegram_id": telegram_id,
                "phase": phase,
                "error_class": type(error).__name__,
                "error_message": str(error),
            },
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )

        try:
            pending = (
                await self.system_error_repository
                .get_unresolved_by_entity_and_error_type(
                    entity_type="payment_event",
                    entity_id=event_id,
                    error_type=CRYPTOBOT_NOTIFICATION_ERROR_TYPE,
                )
            )

            if pending is None:
                await self.system_error_repository.create(
                    entity_type="payment_event",
                    entity_id=event_id,
                    error_type=CRYPTOBOT_NOTIFICATION_ERROR_TYPE,
                    error_message=error_message,
                    payload=payload,
                )
            else:
                await self.system_error_repository.update_pending_failure(
                    pending,
                    entity_type="payment_event",
                    entity_id=event_id,
                    error_message=error_message,
                    payload=payload,
                )

            await self.session.commit()
        except Exception:
            await self._rollback_safely()
            logger.exception(
                "Failed to persist CryptoBot notification system error: "
                "event_id=%s order_id=%s phase=%s",
                event_id,
                order_id,
                phase,
            )

    async def _resolve_failure(self, event_id: int) -> None:
        try:
            pending = (
                await self.system_error_repository
                .get_unresolved_by_entity_and_error_type(
                    entity_type="payment_event",
                    entity_id=event_id,
                    error_type=CRYPTOBOT_NOTIFICATION_ERROR_TYPE,
                )
            )

            if pending is not None:
                await self.system_error_repository.mark_resolved(pending)

            await self.session.commit()
        except Exception:
            await self._rollback_safely()
            logger.exception(
                "Failed to resolve CryptoBot notification system error: "
                "event_id=%s",
                event_id,
            )

    async def _rollback_safely(self) -> None:
        try:
            await self.session.rollback()
        except Exception:
            logger.exception(
                "Failed to rollback CryptoBot notification transaction."
            )
