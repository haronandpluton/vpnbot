import asyncio
import time
from decimal import Decimal

from sqlalchemy import select

from app.common.enums import TariffCode
from app.database.models import Order, Payment, PaymentEvent, Subscription
from app.database.session import SessionLocal
from app.payment_core.enums.order_status import OrderStatus
from app.payment_core.enums.payment_status import PaymentStatus
from app.payment_core.enums.subscription_status import SubscriptionStatus
from app.payment_polling.loop import PaymentPollingLoop
from app.services.order_service import OrderService


async def main():
    suffix = str(int(time.time() * 1000))

    telegram_id = int(f"566862{suffix[-6:]}")

    async with SessionLocal() as session:
        order_service = OrderService(session)

        order = await order_service.create_order(
            telegram_id=telegram_id,
            tariff_code=TariffCode.DEVICES_1,
            payment_option_code="usdt_trc20",
            username=f"polling_test_user_{suffix}",
            first_name="Polling",
            last_name="Tester",
            language_code="ru",
        )

        order.expected_amount = Decimal("4.00")
        await session.commit()

        print("ORDER READY:")
        print("id =", order.id)
        print("status =", order.status)
        print("expected_amount =", order.expected_amount)
        print("expected_currency =", order.expected_currency)
        print("expected_network =", order.expected_network)

        polling = PaymentPollingLoop(session)
        results = await polling.run_once()

        print("\nPOLLING RESULT:")
        print("results_count =", len(results))

        if not results:
            raise RuntimeError("Polling did not process any transaction")

        event, payment, subscription, config_uri = results[0]

        print("\nPROCESSED RESULT:")
        print("event_id =", event.id)
        print("event_status =", event.processing_status)
        print("payment_id =", payment.id)
        print("payment_status =", payment.status)
        print("subscription_id =", subscription.id)
        print("subscription_status =", subscription.status)
        print("config_uri =", config_uri)

        db_order_result = await session.execute(
            select(Order).where(Order.id == order.id)
        )
        db_order = db_order_result.scalar_one()

        db_event_result = await session.execute(
            select(PaymentEvent).where(PaymentEvent.id == event.id)
        )
        db_event = db_event_result.scalar_one()

        db_payment_result = await session.execute(
            select(Payment).where(Payment.id == payment.id)
        )
        db_payment = db_payment_result.scalar_one()

        db_subscription_result = await session.execute(
            select(Subscription).where(Subscription.id == subscription.id)
        )
        db_subscription = db_subscription_result.scalar_one()

        print("\nDB CHECK:")
        print("db_order_status =", db_order.status)
        print("db_event_status =", db_event.processing_status)
        print("db_payment_status =", db_payment.status)
        print("db_subscription_status =", db_subscription.status)
        print("db_subscription_uuid =", db_subscription.uuid)

        assert db_order.status == OrderStatus.ACTIVATED
        assert db_event.processed is True
        assert db_event.processing_status == "confirmed"
        assert db_payment.status == PaymentStatus.CONFIRMED
        assert db_subscription.status == SubscriptionStatus.ACTIVE
        assert db_subscription.user_id == order.user_id
        assert db_subscription.order_id == order.id
        assert config_uri.startswith("vless://")

        print("\nPOLLING INTEGRATION TEST PASSED")


if __name__ == "__main__":
    asyncio.run(main())