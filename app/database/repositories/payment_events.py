from sqlalchemy import select

from app.database.models import PaymentEvent
from app.database.repositories.base import BaseRepository


class PaymentEventRepository(BaseRepository):
    async def create(
        self,
        payment_id: int | None,
        order_id: int | None,
        event_type: str,
        provider: str,
        external_event_id: str | None = None,
        txid: str | None = None,
        payload: str | None = None,
    ) -> PaymentEvent:
        event = PaymentEvent(
            payment_id=payment_id,
            order_id=order_id,
            event_type=event_type,
            provider=provider,
            external_event_id=external_event_id,
            txid=txid,
            payload=payload,
        )
        self.session.add(event)
        await self.session.flush()
        return event

    async def get_unprocessed(self) -> list[PaymentEvent]:
        stmt = select(PaymentEvent).where(PaymentEvent.processed == False)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def mark_processed(
        self,
        event: PaymentEvent,
        processing_status: str | None = None,
        error_message: str | None = None,
    ) -> PaymentEvent:
        event.processed = True
        event.processing_status = processing_status
        event.error_message = error_message
        await self.session.flush()
        return event