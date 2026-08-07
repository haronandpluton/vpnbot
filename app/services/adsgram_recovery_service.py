from __future__ import annotations

import json
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.repositories.system_errors import (
    SystemErrorRecordRepository,
)

logger = logging.getLogger(__name__)

ADSGRAM_START_ATTRIBUTION_ERROR_TYPE = (
    "adsgram_start_attribution_failed"
)
ADSGRAM_PURCHASE_ENQUEUE_ERROR_TYPE = (
    "adsgram_purchase_enqueue_failed"
)


class AdsGramRecoveryService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        system_error_repository: (
            SystemErrorRecordRepository | None
        ) = None,
    ) -> None:
        self.session = session
        self.system_error_repository = (
            system_error_repository
            or SystemErrorRecordRepository(session)
        )

    async def record_start_failure(
            self,
            *,
            user_id: int,
            telegram_id: int,
            campaign_id: str,
            enqueue_registration: bool,
            error: Exception,
    ) -> None:
        await self._record_failure(
            entity_type="user",
            entity_id=user_id,
            error_type=(
                ADSGRAM_START_ATTRIBUTION_ERROR_TYPE
            ),
            error=error,
            payload={
                "user_id": user_id,
                "telegram_id": telegram_id,
                "campaign_id": campaign_id,
                "enqueue_registration": (
                    enqueue_registration
                ),
            },
        )

    async def record_purchase_failure(
        self,
        *,
        user_id: int,
        order_id: int,
        payment_id: int,
        error: Exception,
    ) -> None:
        await self._record_failure(
            entity_type="order",
            entity_id=order_id,
            error_type=(
                ADSGRAM_PURCHASE_ENQUEUE_ERROR_TYPE
            ),
            error=error,
            payload={
                "user_id": user_id,
                "order_id": order_id,
                "payment_id": payment_id,
            },
        )

    async def _record_failure(
        self,
        *,
        entity_type: str,
        entity_id: int,
        error_type: str,
        error: Exception,
        payload: dict,
    ) -> None:
        error_message = (
            f"{type(error).__name__}: {error}"
        )[:1000]

        serialized_payload = json.dumps(
            {
                **payload,
                "error_class": type(error).__name__,
                "error_message": str(error),
            },
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )

        try:
            await self.session.rollback()

            pending = (
                await self.system_error_repository
                .get_unresolved_by_entity_and_error_type(
                    entity_type=entity_type,
                    entity_id=entity_id,
                    error_type=error_type,
                )
            )

            if pending is None:
                await self.system_error_repository.create(
                    entity_type=entity_type,
                    entity_id=entity_id,
                    error_type=error_type,
                    error_message=error_message,
                    payload=serialized_payload,
                )
            else:
                await (
                    self.system_error_repository
                    .update_pending_failure(
                        pending,
                        entity_type=entity_type,
                        entity_id=entity_id,
                        error_message=error_message,
                        payload=serialized_payload,
                    )
                )

            await self.session.commit()

        except Exception:
            logger.exception(
                "Failed to persist AdsGram recovery error: "
                "entity_type=%s entity_id=%s "
                "error_type=%s",
                entity_type,
                entity_id,
                error_type,
            )

            try:
                await self.session.rollback()
            except Exception:
                logger.exception(
                    "Failed to rollback after AdsGram "
                    "recovery persistence failure."
                )