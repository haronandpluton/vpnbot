from datetime import datetime

from sqlalchemy import select

from app.common.enums import CurrencyCode, NetworkCode
from app.database.models import Payment
from app.database.repositories.base import BaseRepository
from app.payment_core.enums.payment_method import PaymentMethod
from app.payment_core.enums.payment_status import PaymentStatus


class PaymentRepository(BaseRepository):
    async def get_by_id(self, payment_id: int) -> Payment | None:
        stmt = select(Payment).where(Payment.id == payment_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_txid(self, txid: str) -> Payment | None:
        stmt = select(Payment).where(Payment.txid == txid)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_provider_payment_id(self, provider_payment_id: str) -> Payment | None:
        stmt = select(Payment).where(Payment.provider_payment_id == provider_payment_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_order_id(self, order_id: int) -> list[Payment]:
        stmt = select(Payment).where(Payment.order_id == order_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create(
        self,
        order_id: int,
        user_id: int,
        payment_method: PaymentMethod,
        amount,
        payment_option_id: int | None = None,
        currency: CurrencyCode | None = None,
        network: NetworkCode | None = None,
        txid: str | None = None,
        provider_payment_id: str | None = None,
        address_from: str | None = None,
        address_to: str | None = None,
        memo_tag: str | None = None,
        confirmations: int | None = None,
        detected_at: datetime | None = None,
        raw_payload: str | None = None,
        status: PaymentStatus = PaymentStatus.NEW,
    ) -> Payment:
        payment = Payment(
            order_id=order_id,
            user_id=user_id,
            status=status,
            payment_method=payment_method,
            payment_option_id=payment_option_id,
            txid=txid,
            provider_payment_id=provider_payment_id,
            amount=amount,
            currency=currency,
            network=network,
            address_from=address_from,
            address_to=address_to,
            memo_tag=memo_tag,
            confirmations=confirmations,
            detected_at=detected_at,
            raw_payload=raw_payload,
        )
        self.session.add(payment)
        await self.session.flush()
        return payment

    async def mark_detected(self, payment: Payment, detected_at: datetime | None = None) -> Payment:
        payment.status = PaymentStatus.DETECTED
        payment.detected_at = detected_at or datetime.utcnow()
        await self.session.flush()
        return payment

    async def mark_confirmed(self, payment: Payment, confirmed_at: datetime) -> Payment:
        payment.status = PaymentStatus.CONFIRMED
        payment.confirmed_at = confirmed_at
        await self.session.flush()
        return payment

    async def mark_invalid(self, payment: Payment) -> Payment:
        payment.status = PaymentStatus.INVALID
        await self.session.flush()
        return payment

    async def mark_duplicate(self, payment: Payment) -> Payment:
        payment.status = PaymentStatus.DUPLICATE
        await self.session.flush()
        return payment

    async def mark_expired(self, payment: Payment) -> Payment:
        payment.status = PaymentStatus.EXPIRED
        await self.session.flush()
        return payment

    async def mark_error(self, payment: Payment) -> Payment:
        payment.status = PaymentStatus.ERROR
        await self.session.flush()
        return payment