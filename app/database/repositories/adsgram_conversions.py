from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import or_, select, update

from app.database.models import AdsGramConversion, User
from app.database.repositories.base import BaseRepository


@dataclass(frozen=True, slots=True)
class ClaimedAdsGramConversion:
    id: int
    user_id: int
    telegram_id: int
    order_id: int | None
    campaign_id: str
    goal_type: int
    attempt_count: int
    claim_token: str


class AdsGramConversionRepository(BaseRepository):
    async def get_by_idempotency_key(
        self,
        idempotency_key: str,
    ) -> AdsGramConversion | None:
        stmt = select(AdsGramConversion).where(
            AdsGramConversion.idempotency_key
            == idempotency_key
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create_pending(
        self,
        *,
        user_id: int,
        campaign_id: str,
        goal_type: int,
        idempotency_key: str,
        order_id: int | None = None,
    ) -> AdsGramConversion:
        conversion = AdsGramConversion(
            user_id=user_id,
            order_id=order_id,
            campaign_id=campaign_id,
            goal_type=goal_type,
            idempotency_key=idempotency_key,
            status="pending",
        )
        self.session.add(conversion)
        await self.session.flush()
        return conversion

    async def requeue_stale_claims(
        self,
        *,
        stale_before: datetime,
        now: datetime,
    ) -> int:
        stmt = (
            update(AdsGramConversion)
            .where(
                AdsGramConversion.status == "processing",
                AdsGramConversion.claimed_at.is_not(None),
                AdsGramConversion.claimed_at <= stale_before,
            )
            .values(
                status="pending",
                claim_token=None,
                claimed_at=None,
                next_attempt_at=now,
            )
        )

        result = await self.session.execute(stmt)
        return int(result.rowcount or 0)

    async def claim_due(
        self,
        *,
        now: datetime,
        limit: int,
        claim_token: str,
    ) -> list[ClaimedAdsGramConversion]:
        stmt = (
            select(
                AdsGramConversion,
                User.telegram_id,
            )
            .join(
                User,
                User.id == AdsGramConversion.user_id,
            )
            .where(
                AdsGramConversion.status == "pending",
                or_(
                    AdsGramConversion.next_attempt_at.is_(None),
                    AdsGramConversion.next_attempt_at <= now,
                ),
            )
            .order_by(AdsGramConversion.id.asc())
            .limit(limit)
            .with_for_update(
                skip_locked=True,
                of=AdsGramConversion,
            )
        )

        result = await self.session.execute(stmt)
        rows = result.all()

        claimed: list[ClaimedAdsGramConversion] = []

        for conversion, telegram_id in rows:
            conversion.status = "processing"
            conversion.claim_token = claim_token
            conversion.claimed_at = now
            conversion.last_attempt_at = now
            conversion.attempt_count += 1

            claimed.append(
                ClaimedAdsGramConversion(
                    id=conversion.id,
                    user_id=conversion.user_id,
                    telegram_id=telegram_id,
                    order_id=conversion.order_id,
                    campaign_id=conversion.campaign_id,
                    goal_type=conversion.goal_type,
                    attempt_count=conversion.attempt_count,
                    claim_token=claim_token,
                )
            )

        if claimed:
            await self.session.flush()

        return claimed

    async def mark_sent(
        self,
        *,
        conversion_id: int,
        claim_token: str,
        sent_at: datetime,
        http_status: int,
    ) -> bool:
        stmt = (
            update(AdsGramConversion)
            .where(
                AdsGramConversion.id == conversion_id,
                AdsGramConversion.status == "processing",
                AdsGramConversion.claim_token == claim_token,
            )
            .values(
                status="sent",
                sent_at=sent_at,
                next_attempt_at=None,
                claimed_at=None,
                claim_token=None,
                last_http_status=http_status,
                last_error=None,
            )
        )

        result = await self.session.execute(stmt)
        return result.rowcount == 1

    async def mark_retry(
        self,
        *,
        conversion_id: int,
        claim_token: str,
        next_attempt_at: datetime,
        http_status: int | None,
        error_message: str,
    ) -> bool:
        stmt = (
            update(AdsGramConversion)
            .where(
                AdsGramConversion.id == conversion_id,
                AdsGramConversion.status == "processing",
                AdsGramConversion.claim_token == claim_token,
            )
            .values(
                status="pending",
                next_attempt_at=next_attempt_at,
                claimed_at=None,
                claim_token=None,
                last_http_status=http_status,
                last_error=error_message,
            )
        )

        result = await self.session.execute(stmt)
        return result.rowcount == 1

    async def mark_failed(
        self,
        *,
        conversion_id: int,
        claim_token: str,
        http_status: int | None,
        error_message: str,
    ) -> bool:
        stmt = (
            update(AdsGramConversion)
            .where(
                AdsGramConversion.id == conversion_id,
                AdsGramConversion.status == "processing",
                AdsGramConversion.claim_token == claim_token,
            )
            .values(
                status="failed",
                next_attempt_at=None,
                claimed_at=None,
                claim_token=None,
                last_http_status=http_status,
                last_error=error_message,
            )
        )

        result = await self.session.execute(stmt)
        return result.rowcount == 1