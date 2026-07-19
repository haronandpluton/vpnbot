from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import or_, select, update

from app.database.models import Order, PaymentEvent, User
from app.database.repositories.base import BaseRepository
from app.payment_core.enums.order_status import OrderStatus


@dataclass(frozen=True, slots=True)
class PendingCryptoBotNotification:
    event_id: int
    order_id: int
    telegram_id: int


class PaymentEventRepository(BaseRepository):
    async def get_by_id(self, event_id: int) -> PaymentEvent | None:
        stmt = select(PaymentEvent).where(PaymentEvent.id == event_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_external_event_id(self, external_event_id: str) -> PaymentEvent | None:
        stmt = select(PaymentEvent).where(
            PaymentEvent.external_event_id == external_event_id
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_provider_and_external_event_id(
        self,
        *,
        provider: str,
        external_event_id: str,
    ) -> PaymentEvent | None:
        stmt = select(PaymentEvent).where(
            PaymentEvent.provider == provider,
            PaymentEvent.external_event_id == external_event_id,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_pending_cryptobot_notifications(
        self,
        *,
        limit: int,
        after_event_id: int = 0,
    ) -> list[PendingCryptoBotNotification]:
        """
        Return confirmed and activated CryptoBot events awaiting notification.

        Notification delivery is intentionally separate from payment
        activation so a Telegram failure cannot roll back a paid order.
        """
        if limit <= 0:
            return []

        stmt = (
            select(
                PaymentEvent.id,
                Order.id,
                User.telegram_id,
            )
            .join(
                Order,
                Order.id == PaymentEvent.order_id,
            )
            .join(
                User,
                User.id == Order.user_id,
            )
            .where(
                PaymentEvent.provider == "cryptobot",
                PaymentEvent.event_type == "invoice_paid",
                PaymentEvent.id > after_event_id,
                PaymentEvent.processed.is_(True),
                PaymentEvent.processing_status == "confirmed",
                PaymentEvent.payment_id.is_not(None),
                PaymentEvent.notification_sent_at.is_(None),
                Order.status == OrderStatus.ACTIVATED,
                Order.activated_subscription_id.is_not(None),
            )
            .order_by(PaymentEvent.id.asc())
            .limit(limit)
        )

        result = await self.session.execute(stmt)

        return [
            PendingCryptoBotNotification(
                event_id=event_id,
                order_id=order_id,
                telegram_id=telegram_id,
            )
            for event_id, order_id, telegram_id in result.all()
        ]

    async def claim_notification(
        self,
        event_id: int,
        *,
        claim_token: str,
        claimed_at: datetime,
        stale_before: datetime,
    ) -> bool:
        """
        Atomically lease one notification for delivery.

        The transaction must be committed before calling Telegram.
        An abandoned lease may be reclaimed after stale_before.
        """
        stmt = (
            update(PaymentEvent)
            .where(
                PaymentEvent.id == event_id,
                PaymentEvent.notification_sent_at.is_(None),
                or_(
                    PaymentEvent.notification_claimed_at.is_(None),
                    PaymentEvent.notification_claimed_at < stale_before,
                ),
            )
            .values(
                notification_claimed_at=claimed_at,
                notification_claim_token=claim_token,
            )
            .returning(PaymentEvent.id)
        )

        result = await self.session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def mark_notification_sent(
        self,
        event_id: int,
        *,
        claim_token: str,
        sent_at: datetime | None = None,
    ) -> bool:
        """
        Complete delivery only for the process that owns the lease.
        """
        stmt = (
            update(PaymentEvent)
            .where(
                PaymentEvent.id == event_id,
                PaymentEvent.notification_sent_at.is_(None),
                PaymentEvent.notification_claim_token == claim_token,
            )
            .values(
                notification_sent_at=sent_at or datetime.now(UTC),
                notification_claimed_at=None,
                notification_claim_token=None,
            )
            .returning(PaymentEvent.id)
        )

        result = await self.session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def release_notification_claim(
        self,
        event_id: int,
        *,
        claim_token: str,
    ) -> bool:
        """
        Release an owned lease after a handled delivery failure.

        Crashed workers cannot call this method, so their leases are recovered
        later through the notification claim TTL.
        """
        stmt = (
            update(PaymentEvent)
            .where(
                PaymentEvent.id == event_id,
                PaymentEvent.notification_sent_at.is_(None),
                PaymentEvent.notification_claim_token == claim_token,
            )
            .values(
                notification_claimed_at=None,
                notification_claim_token=None,
            )
            .returning(PaymentEvent.id)
        )

        result = await self.session.execute(stmt)
        return result.scalar_one_or_none() is not None

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
        stmt = select(PaymentEvent).where(PaymentEvent.processed.is_(False))
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def attach_payment(self, event: PaymentEvent, payment_id: int) -> PaymentEvent:
        event.payment_id = payment_id
        await self.session.flush()
        return event

    async def mark_processed(
        self,
        event: PaymentEvent,
        processing_status: str | None = None,
        error_message: str | None = None,
    ) -> PaymentEvent:
        event.processed = True
        event.processing_status = processing_status
        event.error_message = error_message
        event.processed_at = datetime.now(UTC)
        await self.session.flush()
        return event
