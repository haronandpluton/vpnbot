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
        due_ids = (
            select(AdsGramConversion.id)
            .where(
                AdsGramConversion.status == "pending",
                or_(
                    AdsGramConversion.next_attempt_at.is_(None),
                    AdsGramConversion.next_attempt_at <= now,
                ),
            )
            .order_by(AdsGramConversion.id.asc())
            .limit(limit)
        )

        # Один атомарный UPDATE:
        # два воркера не смогут успешно захватить
        # одну и ту же pending-запись.
        claim_stmt = (
            update(AdsGramConversion)
            .where(
                AdsGramConversion.status == "pending",
                AdsGramConversion.id.in_(due_ids),
            )
            .values(
                status="processing",
                claim_token=claim_token,
                claimed_at=now,
                last_attempt_at=now,
                attempt_count=(
                        AdsGramConversion.attempt_count + 1
                ),
            )
            .returning(
                AdsGramConversion.id,
                AdsGramConversion.user_id,
                AdsGramConversion.order_id,
                AdsGramConversion.campaign_id,
                AdsGramConversion.goal_type,
                AdsGramConversion.attempt_count,
            )
            .execution_options(
                synchronize_session=False
            )
        )

        claim_result = await self.session.execute(
            claim_stmt
        )
        claimed_rows = claim_result.all()

        if not claimed_rows:
            return []

        user_ids = {
            int(row.user_id)
            for row in claimed_rows
        }

        user_stmt = select(
            User.id,
            User.telegram_id,
        ).where(
            User.id.in_(user_ids)
        )

        user_result = await self.session.execute(
            user_stmt
        )

        telegram_ids = {
            int(user_id): int(telegram_id)
            for user_id, telegram_id
            in user_result.all()
        }

        claimed: list[ClaimedAdsGramConversion] = []

        for row in claimed_rows:
            telegram_id = telegram_ids.get(
                int(row.user_id)
            )

            if telegram_id is None:
                raise RuntimeError(
                    "AdsGram conversion user not found: "
                    f"conversion_id={row.id} "
                    f"user_id={row.user_id}"
                )

            claimed.append(
                ClaimedAdsGramConversion(
                    id=int(row.id),
                    user_id=int(row.user_id),
                    telegram_id=telegram_id,
                    order_id=(
                        int(row.order_id)
                        if row.order_id is not None
                        else None
                    ),
                    campaign_id=row.campaign_id,
                    goal_type=int(row.goal_type),
                    attempt_count=int(
                        row.attempt_count
                    ),
                    claim_token=claim_token,
                )
            )

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