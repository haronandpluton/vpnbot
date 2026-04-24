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
from app.services.order_service import OrderService
from app.services.payment_activation_service import PaymentActivationService


async def main():
    suffix = str(int(time.time() * 1000))

    telegram_id = int(f"566859{suffix[-6:]}")
    external_event_id = f"activation_external_event_{suffix}"
    txid = f"activation_txid_{suffix}"

    async with SessionLocal() as session:
        order_service = OrderService(session)
        payment_activation_service = PaymentActivationService(session)

        order = await order_service.create_order(
            telegram_id=telegram_id,
            tariff_code=TariffCode.DEVICES_1,
            payment_option_code="usdt_trc20",
            username=f"activation_test_user_{suffix}",
            first_name="Activation",
            last_name="Tester",
            language_code="ru",
        )

        print("ORDER READY:")
        print("id =", order.id)
        print("status =", order.status)
        print("user_id =", order.user_id)

        event, payment, subscription, config_uri = (
            await payment_activation_service.process_confirmed_payment_event_and_activate(
                order_id=order.id,
                amount=Decimal("4.00"),
                provider="test_provider",
                event_type="payment_confirmed",
                external_event_id=external_event_id,
                txid=txid,
                address_from="sender_wallet",
                address_to="receiver_wallet",
                confirmations=3,
                raw_payload=f'{{"source": "activation_test", "suffix": "{suffix}"}}',
            )
        )

        print("\nACTIVATION RESULT:")
        print("event_id =", event.id)
        print("event_status =", event.processing_status)
        print("payment_id =", payment.id)
        print("payment_status =", payment.status)
        print("subscription_id =", subscription.id)
        print("subscription_status =", subscription.status)
        print("subscription_uuid =", subscription.uuid)
        print("config_uri =", config_uri)

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

        db_subscription_result = await session.execute(
            select(Subscription).where(Subscription.id == subscription.id)
        )
        db_subscription = db_subscription_result.scalar_one()

        print("\nDB CHECK:")
        print("db_event_status =", db_event.processing_status)
        print("db_payment_status =", db_payment.status)
        print("db_order_status =", db_order.status)
        print("db_subscription_status =", db_subscription.status)
        print("db_subscription_uuid =", db_subscription.uuid)

        assert db_event.processed is True
        assert db_event.processing_status == "confirmed"
        assert db_payment.status == PaymentStatus.CONFIRMED
        assert db_order.status == OrderStatus.ACTIVATED
        assert db_subscription.status == SubscriptionStatus.ACTIVE
        assert db_subscription.user_id == order.user_id
        assert db_subscription.order_id == order.id
        assert db_subscription.uuid is not None
        assert config_uri.startswith("vless://")

        print("\nPAYMENT ACTIVATION SERVICE TEST PASSED")


if __name__ == "__main__":
    asyncio.run(main())