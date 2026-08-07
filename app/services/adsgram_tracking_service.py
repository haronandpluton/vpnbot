from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.repositories.adsgram_conversions import (
    AdsGramConversionRepository,
)
from app.database.repositories.payments import PaymentRepository
from app.database.repositories.users import UserRepository

ADSGRAM_GOAL_REGISTRATION = 1
ADSGRAM_GOAL_FIRST_PURCHASE = 2
ADSGRAM_GOAL_REPEAT_PURCHASE = 3

_CAMPAIGN_ID_PATTERN = re.compile(
    r"^[A-Za-z0-9_-]{1,64}$"
)


@dataclass(frozen=True, slots=True)
class AdsGramAttributionResult:
    status: str
    user_id: int | None = None
    campaign_id: str | None = None
    conversion_id: int | None = None


@dataclass(frozen=True, slots=True)
class AdsGramPurchaseResult:
    status: str
    user_id: int | None = None
    order_id: int | None = None
    payment_id: int | None = None
    campaign_id: str | None = None
    goal_type: int | None = None
    conversion_id: int | None = None


def normalize_adsgram_campaign_id(
    value: str | None,
) -> str | None:
    if value is None:
        return None

    normalized = value.strip()

    if not _CAMPAIGN_ID_PATTERN.fullmatch(normalized):
        return None

    return normalized


class AdsGramTrackingService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        user_repository: UserRepository | None = None,
        conversion_repository: (
            AdsGramConversionRepository | None
        ) = None,
        payment_repository: PaymentRepository | None = None,
    ) -> None:
        self.session = session
        self.user_repository = (
            user_repository or UserRepository(session)
        )
        self.conversion_repository = (
            conversion_repository
            or AdsGramConversionRepository(session)
        )
        self.payment_repository = (
                payment_repository or PaymentRepository(session)
        )

    async def capture_start_attribution(
            self,
            *,
            telegram_id: int,
            campaign_id: str | None,
            enqueue_registration: bool = True,
    ) -> AdsGramAttributionResult:
        normalized_campaign_id = normalize_adsgram_campaign_id(
            campaign_id
        )

        if normalized_campaign_id is None:
            return AdsGramAttributionResult(
                status="invalid_campaign"
            )

        try:
            user = (
                await self.user_repository
                .get_by_telegram_id_for_update(telegram_id)
            )

            if user is None:
                await self.session.rollback()

                return AdsGramAttributionResult(
                    status="user_not_found"
                )

            # First-touch attribution:
            # последующие рекламные ссылки источник не меняют.
            if user.adsgram_campaign_id is not None:
                conversion = None

                # Если этот вызов относится к реально новому
                # пользователю, registration conversion должна
                # существовать даже если другой конкурентный
                # /start успел сохранить attribution первым.
                if enqueue_registration:
                    idempotency_key = (
                        f"registration:user:{user.id}"
                    )

                    conversion = (
                        await self.conversion_repository
                        .get_by_idempotency_key(
                            idempotency_key
                        )
                    )

                    if conversion is None:
                        conversion = (
                            await self.conversion_repository
                            .create_pending(
                                user_id=user.id,
                                campaign_id=(
                                    user.adsgram_campaign_id
                                ),
                                goal_type=(
                                    ADSGRAM_GOAL_REGISTRATION
                                ),
                                idempotency_key=idempotency_key,
                            )
                        )

                await self.session.commit()

                return AdsGramAttributionResult(
                    status="already_attributed",
                    user_id=user.id,
                    campaign_id=user.adsgram_campaign_id,
                    conversion_id=(
                        conversion.id
                        if conversion is not None
                        else None
                    ),
                )

            await self.user_repository.set_adsgram_attribution(
                user,
                campaign_id=normalized_campaign_id,
                attributed_at=datetime.now(UTC),
            )

            # Старому пользователю можно сохранить источник,
            # но goal type 1 для него отправлять нельзя.
            if not enqueue_registration:
                await self.session.commit()

                return AdsGramAttributionResult(
                    status="attributed_without_registration",
                    user_id=user.id,
                    campaign_id=normalized_campaign_id,
                )

            idempotency_key = (
                f"registration:user:{user.id}"
            )

            conversion = (
                await self.conversion_repository
                .get_by_idempotency_key(idempotency_key)
            )

            if conversion is None:
                conversion = (
                    await self.conversion_repository
                    .create_pending(
                        user_id=user.id,
                        campaign_id=normalized_campaign_id,
                        goal_type=ADSGRAM_GOAL_REGISTRATION,
                        idempotency_key=idempotency_key,
                    )
                )

            await self.session.commit()

            return AdsGramAttributionResult(
                status="attributed",
                user_id=user.id,
                campaign_id=normalized_campaign_id,
                conversion_id=conversion.id,
            )

        except IntegrityError:
            # Защита от гонки двух одинаковых /start.
            await self.session.rollback()

            user = await self.user_repository.get_by_telegram_id(
                telegram_id
            )

            if (
                    user is None
                    or user.adsgram_campaign_id is None
            ):
                raise

            conversion = None

            if enqueue_registration:
                conversion = (
                    await self.conversion_repository
                    .get_by_idempotency_key(
                        f"registration:user:{user.id}"
                    )
                )

            await self.session.commit()

            return AdsGramAttributionResult(
                status="already_attributed",
                user_id=user.id,
                campaign_id=user.adsgram_campaign_id,
                conversion_id=(
                    conversion.id
                    if conversion is not None
                    else None
                ),
            )

        except Exception:
            await self.session.rollback()
            raise
    async def enqueue_purchase_conversion(
        self,
        *,
        user_id: int,
        order_id: int,
        payment_id: int,
    ) -> AdsGramPurchaseResult:
        idempotency_key = f"purchase:order:{order_id}"

        try:
            user = await self.user_repository.get_by_id(
                user_id
            )

            if user is None:
                await self.session.rollback()

                return AdsGramPurchaseResult(
                    status="user_not_found",
                    user_id=user_id,
                    order_id=order_id,
                    payment_id=payment_id,
                )

            if user.adsgram_campaign_id is None:
                await self.session.commit()

                return AdsGramPurchaseResult(
                    status="not_attributed",
                    user_id=user.id,
                    order_id=order_id,
                    payment_id=payment_id,
                )

            existing = (
                await self.conversion_repository
                .get_by_idempotency_key(idempotency_key)
            )

            if existing is not None:
                await self.session.commit()

                return AdsGramPurchaseResult(
                    status="already_queued",
                    user_id=user.id,
                    order_id=order_id,
                    payment_id=payment_id,
                    campaign_id=user.adsgram_campaign_id,
                    goal_type=existing.goal_type,
                    conversion_id=existing.id,
                )

            first_order_id = (
                await self.payment_repository
                .get_first_confirmed_order_id_by_user(
                    user.id
                )
            )

            if first_order_id is None:
                await self.session.commit()

                return AdsGramPurchaseResult(
                    status="confirmed_payment_not_found",
                    user_id=user.id,
                    order_id=order_id,
                    payment_id=payment_id,
                    campaign_id=user.adsgram_campaign_id,
                )

            goal_type = (
                ADSGRAM_GOAL_FIRST_PURCHASE
                if first_order_id == order_id
                else ADSGRAM_GOAL_REPEAT_PURCHASE
            )

            conversion = (
                await self.conversion_repository
                .create_pending(
                    user_id=user.id,
                    order_id=order_id,
                    campaign_id=user.adsgram_campaign_id,
                    goal_type=goal_type,
                    idempotency_key=idempotency_key,
                )
            )

            await self.session.commit()

            return AdsGramPurchaseResult(
                status="queued",
                user_id=user.id,
                order_id=order_id,
                payment_id=payment_id,
                campaign_id=user.adsgram_campaign_id,
                goal_type=goal_type,
                conversion_id=conversion.id,
            )

        except IntegrityError:
            # Защита от одновременной обработки
            # одного и того же payment event.
            await self.session.rollback()

            existing = (
                await self.conversion_repository
                .get_by_idempotency_key(idempotency_key)
            )

            if existing is None:
                raise

            await self.session.commit()

            return AdsGramPurchaseResult(
                status="already_queued",
                user_id=user_id,
                order_id=order_id,
                payment_id=payment_id,
                campaign_id=existing.campaign_id,
                goal_type=existing.goal_type,
                conversion_id=existing.id,
            )

        except Exception:
            await self.session.rollback()
            raise