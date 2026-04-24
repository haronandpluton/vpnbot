import asyncio
import time
from decimal import Decimal

from sqlalchemy import func, select

from app.common.enums import TariffCode
from app.database.models import Order, Payment, PaymentEvent
from app.database.session import SessionLocal
from app.payment_core.enums.order_status import OrderStatus
from app.payment_core.enums.payment_status import PaymentStatus
from app.services.order_service import OrderService
from app.services.payment_event_service import PaymentEventService


async def main():
    suffix = str(int(time.time() * 1000))

    telegram_id = int(f"566856{suffix[-6:]}")
    external_event_id = f"duplicate_external_event_{suffix}"
    second_external_event_id = f"duplicate_external_event_second_{suffix}"
    txid = f"duplicate_txid_{suffix}"

    async with SessionLocal() as session:
        order_service = OrderService(session)
        payment_event_service = PaymentEventService(session)

        order = await order_service.create_order(
            telegram_id=telegram_id,
            tariff_code=TariffCode.DEVICES_1,
            payment_option_code="usdt_trc20",
            username=f"duplicate_test_user_{suffix}",
            first_name="Duplicate",
            last_name="Tester",
            language_code="ru",
        )

        print("ORDER READY:")
        print("id =", order.id)
        print("status =", order.status)

        first_event, first_payment, first_paid_order = (
            await payment_event_service.process_confirmed_event(
                order_id=order.id,
                amount=Decimal("4.00"),
                provider="test_provider",
                event_type="payment_confirmed",
                external_event_id=external_event_id,
                txid=txid,
                address_from="sender_wallet",
                address_to="receiver_wallet",
                confirmations=3,
                raw_payload=f'{{"source": "duplicate_test", "step": "first", "suffix": "{suffix}"}}',
            )
        )

        print("\nFIRST EVENT RESULT:")
        print("event_id =", first_event.id)
        print("event_status =", first_event.processing_status)
        print("event_payment_id =", first_event.payment_id)
        print("payment_id =", first_payment.id)
        print("payment_status =", first_payment.status)
        print("order_id =", first_paid_order.id)
        print("order_status =", first_paid_order.status)

        same_event, same_payment, same_order = (
            await payment_event_service.process_confirmed_event(
                order_id=order.id,
                amount=Decimal("4.00"),
                provider="test_provider",
                event_type="payment_confirmed",
                external_event_id=external_event_id,
                txid=txid,
                address_from="sender_wallet",
                address_to="receiver_wallet",
                confirmations=3,
                raw_payload=f'{{"source": "duplicate_test", "step": "same_event", "suffix": "{suffix}"}}',
            )
        )

        print("\nSAME EXTERNAL EVENT RESULT:")
        print("event_id =", same_event.id)
        print("event_status =", same_event.processing_status)
        print("event_payment_id =", same_event.payment_id)
        print("payment_id =", None if same_payment is None else same_payment.id)
        print("payment_status =", None if same_payment is None else same_payment.status)
        print("order_id =", None if same_order is None else same_order.id)
        print("order_status =", None if same_order is None else same_order.status)

        second_event, second_payment, second_order = (
            await payment_event_service.process_confirmed_event(
                order_id=order.id,
                amount=Decimal("4.00"),
                provider="test_provider",
                event_type="payment_confirmed",
                external_event_id=second_external_event_id,
                txid=txid,
                address_from="sender_wallet",
                address_to="receiver_wallet",
                confirmations=3,
                raw_payload=f'{{"source": "duplicate_test", "step": "same_txid", "suffix": "{suffix}"}}',
            )
        )

        print("\nSAME TXID, DIFFERENT EXTERNAL EVENT RESULT:")
        print("event_id =", second_event.id)
        print("event_status =", second_event.processing_status)
        print("event_payment_id =", second_event.payment_id)
        print("payment_id =", second_payment.id)
        print("payment_status =", second_payment.status)
        print("order_id =", second_order.id)
        print("order_status =", second_order.status)

        payment_count_result = await session.execute(
            select(func.count()).select_from(Payment).where(Payment.txid == txid)
        )
        payment_count = payment_count_result.scalar_one()

        event_count_result = await session.execute(
            select(func.count())
            .select_from(PaymentEvent)
            .where(PaymentEvent.txid == txid)
        )
        event_count = event_count_result.scalar_one()

        db_payment_result = await session.execute(
            select(Payment).where(Payment.id == first_payment.id)
        )
        db_payment = db_payment_result.scalar_one()

        db_order_result = await session.execute(
            select(Order).where(Order.id == order.id)
        )
        db_order = db_order_result.scalar_one()

        print("\nDB CHECK:")
        print("payment_count_by_txid =", payment_count)
        print("event_count_by_txid =", event_count)
        print("db_payment_status =", db_payment.status)
        print("db_order_status =", db_order.status)

        assert first_event.id == same_event.id
        assert first_payment.id == same_payment.id
        assert first_paid_order.id == same_order.id

        assert second_event.id != first_event.id
        assert second_payment.id == first_payment.id
        assert second_order.id == order.id

        assert payment_count == 1
        assert event_count == 2

        assert db_payment.status == PaymentStatus.CONFIRMED
        assert db_order.status == OrderStatus.PAID

        print("\nDUPLICATE EVENT TEST PASSED")


if __name__ == "__main__":
    asyncio.run(main())