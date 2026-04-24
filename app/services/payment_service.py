from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.repositories.orders import OrderRepository
from app.database.repositories.payments import PaymentRepository
from app.payment_core.enums.order_status import OrderStatus
from app.payment_core.enums.payment_status import PaymentStatus


class PaymentService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.order_repository = OrderRepository(session)
        self.payment_repository = PaymentRepository(session)

    async def _create_payment_for_order(
        self,
        order_id: int,
        amount: Decimal,
        txid: str | None = None,
        provider_payment_id: str | None = None,
        address_from: str | None = None,
        address_to: str | None = None,
        memo_tag: str | None = None,
        confirmations: int | None = None,
        raw_payload: str | None = None,
        initial_status: PaymentStatus = PaymentStatus.NEW,
    ):
        order = await self.order_repository.get_by_id(order_id)
        if order is None:
            raise ValueError(f"Order not found: {order_id}")

        if txid is not None:
            existing = await self.payment_repository.get_by_txid(txid)
            if existing:
                return existing

        if provider_payment_id is not None:
            existing = await self.payment_repository.get_by_provider_payment_id(
                provider_payment_id
            )
            if existing:
                return existing

        payment = await self.payment_repository.create(
            order_id=order.id,
            user_id=order.user_id,
            payment_method=order.payment_method,
            payment_option_id=order.payment_option_id,
            amount=amount,
            currency=order.expected_currency,
            network=order.expected_network,
            txid=txid,
            provider_payment_id=provider_payment_id,
            address_from=address_from,
            address_to=address_to,
            memo_tag=memo_tag,
            confirmations=confirmations,
            raw_payload=raw_payload,
            status=initial_status,
        )
        return payment

    async def _mark_payment_detected(self, payment_id: int):
        payment = await self.payment_repository.get_by_id(payment_id)
        if payment is None:
            raise ValueError(f"Payment not found: {payment_id}")

        if payment.status in {
            PaymentStatus.DETECTED,
            PaymentStatus.CONFIRMED,
            PaymentStatus.INVALID,
            PaymentStatus.DUPLICATE,
            PaymentStatus.EXPIRED,
        }:
            return payment

        return await self.payment_repository.mark_detected(payment)

    async def _confirm_payment(self, payment_id: int):
        payment = await self.payment_repository.get_by_id(payment_id)
        if payment is None:
            raise ValueError(f"Payment not found: {payment_id}")

        order = await self.order_repository.get_by_id(payment.order_id)

        if payment.status == PaymentStatus.CONFIRMED:
            return payment, order

        if payment.status in {
            PaymentStatus.INVALID,
            PaymentStatus.DUPLICATE,
            PaymentStatus.EXPIRED,
        }:
            return payment, order

        payment = await self.payment_repository.mark_confirmed(payment)

        if order.status == OrderStatus.WAITING_PAYMENT:
            order = await self.order_repository.mark_paid(
                order=order,
                paid_at=payment.confirmed_at,
            )

        return payment, order

    async def create_payment_for_order(self, *args, **kwargs):
        try:
            payment = await self._create_payment_for_order(*args, **kwargs)
            await self.session.commit()
            return payment
        except Exception:
            await self.session.rollback()
            raise

    async def mark_payment_detected(self, payment_id: int):
        try:
            payment = await self._mark_payment_detected(payment_id)
            await self.session.commit()
            return payment
        except Exception:
            await self.session.rollback()
            raise

    async def confirm_payment(self, payment_id: int):
        try:
            payment, order = await self._confirm_payment(payment_id)
            await self.session.commit()
            return payment, order
        except Exception:
            await self.session.rollback()
            raise