import asyncio
from decimal import Decimal

from sqlalchemy import select

from app.common.enums import TariffCode
from app.database.models import Order, Payment, PaymentEvent
from app.database.session import SessionLocal
from app.services.order_service import OrderService
from app.services.payment_event_service import PaymentEventService


async def main():
    async with SessionLocal() as session:
        order_service = OrderService(session)
        payment_event_service = PaymentEventService(session)

        order = await order_service.create_order(
            telegram_id=566854075,
            tariff_code=TariffCode.DEVICES_1,
            payment_option_code="usdt_trc20",
            username="event_test_user",
            first_name="Event",
            last_name="Tester",
            language_code="ru",
        )

        print("ORDER READY:")
        print("id =", order.id)
        print("status =", order.status)

        event, payment, paid_order = await payment_event_service.process_confirmed_event(
            order_id=order.id,
            amount=Decimal("4.00"),
            provider="test_provider",
            event_type="payment_confirmed",
            external_event_id="external_event_001",
            txid="event_txid_001",
            address_from="sender_wallet",
            address_to="receiver_wallet",
            confirmations=3,
            raw_payload='{"source": "integration_test"}',
        )

        print("\nEVENT RESULT:")
        print("event_id =", None if event is None else event.id)
        print("event_status =", None if event is None else event.processing_status)
        print("event_payment_id =", None if event is None else event.payment_id)

        print("\nPAYMENT RESULT:")
        print("payment_id =", None if payment is None else payment.id)
        print("payment_status =", None if payment is None else payment.status)

        print("\nORDER RESULT:")
        print("order_id =", None if paid_order is None else paid_order.id)
        print("order_status =", None if paid_order is None else paid_order.status)

        db_event_result = await session.execute(
            select(PaymentEvent).where(PaymentEvent.id == event.id)
        )
        db_event = db_event_result.scalar_one()

        db_payment_result = await session.execute(
            select(Payment).where(Payment.id == payment.id)
        )
        db_payment = db_payment_result.scalar_one()

        db_order_result = await session.execute(
            select(Order).where(Order.id == order.id)
        )
        db_order = db_order_result.scalar_one()

        print("\nDB CHECK:")
        print("db_event_status =", db_event.processing_status)
        print("db_payment_status =", db_payment.status)
        print("db_order_status =", db_order.status)


if __name__ == "__main__":
    asyncio.run(main())