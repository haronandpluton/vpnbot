from sqlalchemy import select

from app.database.models import AdsGramConversion
from app.database.repositories.base import BaseRepository


class AdsGramConversionRepository(BaseRepository):
    async def get_by_idempotency_key(
        self,
        idempotency_key: str,
    ) -> AdsGramConversion | None:
        stmt = select(AdsGramConversion).where(
            AdsGramConversion.idempotency_key == idempotency_key
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