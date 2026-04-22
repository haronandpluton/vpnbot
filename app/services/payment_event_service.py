from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.repositories.orders import OrderRepository
from app.database.repositories.payment_events import PaymentEventRepository
from app.services.payment_service import PaymentService


class PaymentEventService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.order_repository = OrderRepository(session)
        self.payment_event_repository = PaymentEventRepository(session)
        self.payment_service = PaymentService(session)

    async def process_detected_event(
        self,
        order_id: int,
        amount: Decimal,
        provider: str,
        event_type: str,
        external_event_id: str | None = None,
        txid: str | None = None,
        address_from: str | None = None,
        address_to: str | None = None,
        memo_tag: str | None = None,
        confirmations: int | None = None,
        raw_payload: str | None = None,
    ):
        try:
            if external_event_id is not None:
                existing_event = await self.payment_event_repository.get_by_external_event_id(
                    external_event_id
                )
                if existing_event is not None:
                    await self.session.commit()
                    return existing_event, None, None

            order = await self.order_repository.get_by_id(order_id)
            if order is None:
                raise ValueError(f"Order not found: {order_id}")

            event = await self.payment_event_repository.create(
                payment_id=None,
                order_id=order.id,
                event_type=event_type,
                provider=provider,
                external_event_id=external_event_id,
                txid=txid,
                payload=raw_payload,
            )

            payment = await self.payment_service._create_payment_for_order(
                order_id=order.id,
                amount=amount,
                txid=txid,
                provider_payment_id=external_event_id,
                address_from=address_from,
                address_to=address_to,
                memo_tag=memo_tag,
                confirmations=confirmations,
                raw_payload=raw_payload,
            )

            await self.payment_event_repository.attach_payment(
                event=event,
                payment_id=payment.id,
            )

            payment = await self.payment_service._mark_payment_detected(payment.id)

            await self.payment_event_repository.mark_processed(
                event=event,
                processing_status="detected",
                error_message=None,
            )

            await self.session.commit()
            return event, payment, order

        except Exception:
            await self.session.rollback()
            raise

    async def process_confirmed_event(
        self,
        order_id: int,
        amount: Decimal,
        provider: str,
        event_type: str,
        external_event_id: str | None = None,
        txid: str | None = None,
        address_from: str | None = None,
        address_to: str | None = None,
        memo_tag: str | None = None,
        confirmations: int | None = None,
        raw_payload: str | None = None,
    ):
        try:
            if external_event_id is not None:
                existing_event = await self.payment_event_repository.get_by_external_event_id(
                    external_event_id
                )
                if existing_event is not None:
                    await self.session.commit()
                    return existing_event, None, None

            order = await self.order_repository.get_by_id(order_id)
            if order is None:
                raise ValueError(f"Order not found: {order_id}")

            event = await self.payment_event_repository.create(
                payment_id=None,
                order_id=order.id,
                event_type=event_type,
                provider=provider,
                external_event_id=external_event_id,
                txid=txid,
                payload=raw_payload,
            )

            payment = await self.payment_service._create_payment_for_order(
                order_id=order.id,
                amount=amount,
                txid=txid,
                provider_payment_id=external_event_id,
                address_from=address_from,
                address_to=address_to,
                memo_tag=memo_tag,
                confirmations=confirmations,
                raw_payload=raw_payload,
            )

            await self.payment_event_repository.attach_payment(
                event=event,
                payment_id=payment.id,
            )

            payment = await self.payment_service._mark_payment_detected(payment.id)
            confirmed_payment, paid_order = await self.payment_service._confirm_payment(
                payment.id
            )

            await self.payment_event_repository.mark_processed(
                event=event,
                processing_status="confirmed",
                error_message=None,
            )

            await self.session.commit()
            return event, confirmed_payment, paid_order

        except Exception:
            await self.session.rollback()
            raise