import asyncio
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select

from app.common.enums import TariffCode
from app.database.models import Order, Payment, PaymentEvent, Subscription
from app.database.session import SessionLocal
from app.payment_core.enums.order_status import OrderStatus
from app.payment_core.enums.payment_status import PaymentStatus
from app.services.order_service import OrderService
from app.services.payment_event_service import PaymentEventService


async def main():
    suffix = str(int(time.time() * 1000))

    telegram_id = int(f"566861{suffix[-6:]}")
    external_event_id = f"late_external_event_{suffix}"
    txid = f"late_txid_{suffix}"

    async with SessionLocal() as session:
        order_service = OrderService(session)
        payment_event_service = PaymentEventService(session)

        order = await order_service.create_order(
            telegram_id=telegram_id,
            tariff_code=TariffCode.DEVICES_1,
            payment_option_code="usdt_trc20",
            username=f"late_payment_user_{suffix}",
            first_name="Late",
            last_name="Tester",
            language_code="ru",
        )

        order.status = OrderStatus.EXPIRED
        order.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        await session.commit()

        print("ORDER EXPIRED:")
        print("id =", order.id)
        print("status =", order.status)
        print("expires_at =", order.expires_at)

        event, payment, paid_order = await payment_event_service.process_confirmed_event(
            order_id=order.id,
            amount=Decimal("4.00"),
            provider="test_provider",
            event_type="payment_confirmed",
            external_event_id=external_event_id,
            txid=txid,
            address_from="sender_wallet",
            address_to="receiver_wallet",
            confirmations=3,
            raw_payload=f'{{"source": "late_payment_test", "suffix": "{suffix}"}}',
        )

        print("\nLATE EVENT RESULT:")
        print("event_id =", event.id)
        print("event_status =", event.processing_status)
        print("event_error =", event.error_message)
        print("event_payment_id =", event.payment_id)

        print("\nPAYMENT RESULT:")
        print("payment_id =", payment.id)
        print("payment_status =", payment.status)

        print("\nORDER RESULT:")
        print("paid_order =", paid_order)

        payment_count_result = await session.execute(
            select(func.count()).select_from(Payment).where(Payment.txid == txid)
        )
        payment_count = payment_count_result.scalar_one()

        event_count_result = await session.execute(
            select(func.count())
            .select_from(PaymentEvent)
            .where(PaymentEvent.external_event_id == external_event_id)
        )
        event_count = event_count_result.scalar_one()

        subscription_count_result = await session.execute(
            select(func.count())
            .select_from(Subscription)
            .where(Subscription.user_id == order.user_id)
        )
        subscription_count = subscription_count_result.scalar_one()

        db_order_result = await session.execute(
            select(Order).where(Order.id == order.id)
        )
        db_order = db_order_result.scalar_one()

        db_payment_result = await session.execute(
            select(Payment).where(Payment.id == payment.id)
        )
        db_payment = db_payment_result.scalar_one()

        db_event_result = await session.execute(
            select(PaymentEvent).where(PaymentEvent.id == event.id)
        )
        db_event = db_event_result.scalar_one()

        print("\nDB CHECK:")
        print("payment_count =", payment_count)
        print("event_count =", event_count)
        print("subscription_count =", subscription_count)
        print("db_order_status =", db_order.status)
        print("db_payment_status =", db_payment.status)
        print("db_event_status =", db_event.processing_status)
        print("db_event_error =", db_event.error_message)

        assert paid_order is None

        assert payment_count == 1
        assert event_count == 1
        assert subscription_count == 0

        assert db_order.status == OrderStatus.EXPIRED
        assert db_payment.status == PaymentStatus.EXPIRED
        assert db_event.processed is True
        assert db_event.processing_status == "expired"
        assert db_event.payment_id == db_payment.id

        print("\nLATE PAYMENT TEST PASSED")


if __name__ == "__main__":
    asyncio.run(main())