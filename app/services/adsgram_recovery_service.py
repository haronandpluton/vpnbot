from __future__ import annotations

import json
import logging

from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.repositories.system_errors import (
    SystemErrorRecordRepository,
)
from app.services.adsgram_tracking_service import (
    AdsGramTrackingService,
)

logger = logging.getLogger(__name__)

ADSGRAM_START_ATTRIBUTION_ERROR_TYPE = (
    "adsgram_start_attribution_failed"
)
ADSGRAM_PURCHASE_ENQUEUE_ERROR_TYPE = (
    "adsgram_purchase_enqueue_failed"
)

@dataclass(frozen=True, slots=True)
class AdsGramRecoveryRunResult:
    start_checked: int
    purchase_checked: int
    resolved: int
    deferred: int
    failed: int

class AdsGramRecoveryService:
    def __init__(
            self,
            session: AsyncSession,
            *,
            system_error_repository: (
                    SystemErrorRecordRepository | None
            ) = None,
            tracking_service_factory: Callable[
                [AsyncSession],
                AdsGramTrackingService,
            ] = AdsGramTrackingService,
            batch_size: int = 50,
    ) -> None:
        self.session = session
        self.system_error_repository = (
            system_error_repository
            or SystemErrorRecordRepository(session)
        )
        if batch_size < 1:
            raise ValueError(
                "AdsGram recovery batch_size must be >= 1."
            )

        self.tracking_service_factory = (
            tracking_service_factory
        )
        self.batch_size = batch_size
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

    async def run_once(
        self,
    ) -> AdsGramRecoveryRunResult:
        start_errors = (
            await self.system_error_repository
            .get_unresolved_by_error_type(
                ADSGRAM_START_ATTRIBUTION_ERROR_TYPE
            )
        )[: self.batch_size]

        counters = {
            "resolved": 0,
            "deferred": 0,
            "failed": 0,
        }

        # Сначала восстанавливаем attribution.
        # Purchase recovery может зависеть от неё.
        for error_record in start_errors:
            outcome = await self._replay_start(
                error_record
            )
            counters[outcome] += 1

        purchase_errors = (
            await self.system_error_repository
            .get_unresolved_by_error_type(
                ADSGRAM_PURCHASE_ENQUEUE_ERROR_TYPE
            )
        )[: self.batch_size]

        for error_record in purchase_errors:
            outcome = await self._replay_purchase(
                error_record
            )
            counters[outcome] += 1

        return AdsGramRecoveryRunResult(
            start_checked=len(start_errors),
            purchase_checked=len(purchase_errors),
            resolved=counters["resolved"],
            deferred=counters["deferred"],
            failed=counters["failed"],
        )

    async def _replay_start(
        self,
        error_record,
    ) -> str:
        entity_type = error_record.entity_type
        entity_id = error_record.entity_id
        error_type = error_record.error_type
        raw_payload = error_record.payload

        try:
            payload = self._parse_payload(
                raw_payload
            )
            user_id = self._require_int(
                payload,
                "user_id",
            )

            if (
                entity_type != "user"
                or entity_id != user_id
            ):
                raise ValueError(
                    "AdsGram start recovery entity "
                    "does not match payload: "
                    f"entity_type={entity_type!r} "
                    f"entity_id={entity_id!r} "
                    f"user_id={user_id!r}"
                )
            telegram_id = self._require_int(
                payload,
                "telegram_id",
            )
            campaign_id = self._require_str(
                payload,
                "campaign_id",
            )
            enqueue_registration = (
                self._require_bool(
                    payload,
                    "enqueue_registration",
                )
            )

            result = await (
                self.tracking_service_factory(
                    self.session
                )
                .capture_start_attribution(
                    telegram_id=telegram_id,
                    campaign_id=campaign_id,
                    enqueue_registration=(
                        enqueue_registration
                    ),
                )
            )

            success = False

            if enqueue_registration:
                success = (
                    result.status
                    in {
                        "attributed",
                        "already_attributed",
                    }
                    and result.conversion_id
                    is not None
                )
            else:
                success = result.status in {
                    "attributed_without_registration",
                    "already_attributed",
                }

            if not success:
                raise RuntimeError(
                    "AdsGram start replay returned "
                    f"status={result.status!r} "
                    "conversion_id="
                    f"{result.conversion_id!r}"
                )

            await self.system_error_repository.mark_resolved(
                error_record
            )
            await self.session.commit()

            return "resolved"

        except Exception as error:
            await self._record_replay_failure(
                entity_type=entity_type,
                entity_id=entity_id,
                error_type=error_type,
                payload=raw_payload,
                error=error,
            )
            return "failed"

    async def _replay_purchase(
        self,
        error_record,
    ) -> str:
        entity_type = error_record.entity_type
        entity_id = error_record.entity_id
        error_type = error_record.error_type
        raw_payload = error_record.payload

        try:
            payload = self._parse_payload(
                raw_payload
            )

            user_id = self._require_int(
                payload,
                "user_id",
            )
            order_id = self._require_int(
                payload,
                "order_id",
            )
            if (
                entity_type != "order"
                or entity_id != order_id
            ):
                raise ValueError(
                    "AdsGram purchase recovery entity "
                    "does not match payload: "
                    f"entity_type={entity_type!r} "
                    f"entity_id={entity_id!r} "
                    f"order_id={order_id!r}"
                )
            payment_id = self._require_int(
                payload,
                "payment_id",
            )

            result = await (
                self.tracking_service_factory(
                    self.session
                )
                .enqueue_purchase_conversion(
                    user_id=user_id,
                    order_id=order_id,
                    payment_id=payment_id,
                )
            )

            if (
                result.status
                in {"queued", "already_queued"}
                and result.conversion_id is not None
            ):
                await (
                    self.system_error_repository
                    .mark_resolved(error_record)
                )
                await self.session.commit()
                return "resolved"

            if result.status == "not_attributed":
                pending_start = await (
                    self.system_error_repository
                    .get_unresolved_by_entity_and_error_type(
                        entity_type="user",
                        entity_id=user_id,
                        error_type=(
                            ADSGRAM_START_ATTRIBUTION_ERROR_TYPE
                        ),
                    )
                )

                if pending_start is not None:
                    # Attribution ещё не восстановлена.
                    # Purchase не считаем новой ошибкой.
                    return "deferred"

                # Пользователь действительно не рекламный.
                # AdsGram conversion для него не требуется.
                await (
                    self.system_error_repository
                    .mark_resolved(error_record)
                )
                await self.session.commit()
                return "resolved"

            raise RuntimeError(
                "AdsGram purchase replay returned "
                f"status={result.status!r} "
                "conversion_id="
                f"{result.conversion_id!r}"
            )

        except Exception as error:
            await self._record_replay_failure(
                entity_type=entity_type,
                entity_id=entity_id,
                error_type=error_type,
                payload=raw_payload,
                error=error,
            )
            return "failed"

    @staticmethod
    def _parse_payload(
        raw_payload: str | None,
    ) -> dict:
        if raw_payload is None:
            raise ValueError(
                "AdsGram recovery payload is missing."
            )

        payload = json.loads(raw_payload)

        if not isinstance(payload, dict):
            raise ValueError(
                "AdsGram recovery payload must be an object."
            )

        return payload

    @staticmethod
    def _require_int(
        payload: dict,
        key: str,
    ) -> int:
        value = payload.get(key)

        if (
            isinstance(value, bool)
            or not isinstance(value, int)
        ):
            raise ValueError(
                f"AdsGram recovery field {key!r} "
                "must be an integer."
            )

        return value

    @staticmethod
    def _require_str(
        payload: dict,
        key: str,
    ) -> str:
        value = payload.get(key)

        if (
            not isinstance(value, str)
            or not value
        ):
            raise ValueError(
                f"AdsGram recovery field {key!r} "
                "must be a non-empty string."
            )

        return value

    @staticmethod
    def _require_bool(
        payload: dict,
        key: str,
    ) -> bool:
        value = payload.get(key)

        if not isinstance(value, bool):
            raise ValueError(
                f"AdsGram recovery field {key!r} "
                "must be a boolean."
            )

        return value

    async def _record_replay_failure(
        self,
        *,
        entity_type: str,
        entity_id: int | None,
        error_type: str,
        payload: str | None,
        error: Exception,
    ) -> None:
        error_message = (
            f"{type(error).__name__}: {error}"
        )[:1000]

        try:
            await self.session.rollback()

            pending = await (
                self.system_error_repository
                .get_unresolved_by_entity_and_error_type(
                    entity_type=entity_type,
                    entity_id=entity_id,
                    error_type=error_type,
                )
            )

            # Другой worker мог уже закрыть запись.
            if pending is None:
                return

            await (
                self.system_error_repository
                .update_pending_failure(
                    pending,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    error_message=error_message,
                    payload=payload,
                )
            )

            await self.session.commit()

        except Exception:
            logger.exception(
                "Failed to update AdsGram replay failure: "
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
                    "Failed to rollback AdsGram "
                    "replay failure update."
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