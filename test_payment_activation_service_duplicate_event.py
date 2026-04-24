import asyncio
import time
from decimal import Decimal

from sqlalchemy import func, select

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

    telegram_id = int(f"566860{suffix[-6:]}")
    external_event_id = f"activation_duplicate_event_{suffix}"
    txid = f"activation_duplicate_txid_{suffix}"

    async with SessionLocal() as session:
        order_service = OrderService(session)
        activation_service = PaymentActivationService(session)

        order = await order_service.create_order(
            telegram_id=telegram_id,
            tariff_code=TariffCode.DEVICES_1,
            payment_option_code="usdt_trc20",
            username=f"activation_duplicate_user_{suffix}",
            first_name="ActivationDuplicate",
            last_name="Tester",
            language_code="ru",
        )

        print("ORDER READY:")
        print("id =", order.id)
        print("status =", order.status)
        print("user_id =", order.user_id)

        first_event, first_payment, first_subscription, first_config_uri = (
            await activation_service.process_confirmed_payment_event_and_activate(
                order_id=order.id,
                amount=Decimal("4.00"),
                provider="test_provider",
                event_type="payment_confirmed",
                external_event_id=external_event_id,
                txid=txid,
                address_from="sender_wallet",
                address_to="receiver_wallet",
                confirmations=3,
                raw_payload=f'{{"source": "activation_duplicate_test", "step": "first", "suffix": "{suffix}"}}',
            )
        )

        print("\nFIRST ACTIVATION RESULT:")
        print("event_id =", first_event.id)
        print("event_status =", first_event.processing_status)
        print("payment_id =", first_payment.id)
        print("payment_status =", first_payment.status)
        print("subscription_id =", first_subscription.id)
        print("subscription_status =", first_subscription.status)
        print("subscription_uuid =", first_subscription.uuid)
        print("config_uri =", first_config_uri)

        first_subscription_id = first_subscription.id
        first_uuid = first_subscription.uuid
        first_expires_at = first_subscription.expires_at

        second_event, second_payment, second_subscription, second_config_uri = (
            await activation_service.process_confirmed_payment_event_and_activate(
                order_id=order.id,
                amount=Decimal("4.00"),
                provider="test_provider",
                event_type="payment_confirmed",
                external_event_id=external_event_id,
                txid=txid,
                address_from="sender_wallet",
                address_to="receiver_wallet",
                confirmations=3,
                raw_payload=f'{{"source": "activation_duplicate_test", "step": "duplicate", "suffix": "{suffix}"}}',
            )
        )

        print("\nSECOND DUPLICATE ACTIVATION RESULT:")
        print("event_id =", second_event.id)
        print("event_status =", second_event.processing_status)
        print("payment_id =", None if second_payment is None else second_payment.id)
        print("payment_status =", None if second_payment is None else second_payment.status)
        print("subscription_id =", second_subscription.id)
        print("subscription_status =", second_subscription.status)
        print("subscription_uuid =", second_subscription.uuid)
        print("config_uri =", second_config_uri)

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
            select(Payment).where(Payment.id == first_payment.id)
        )
        db_payment = db_payment_result.scalar_one()

        db_subscription_result = await session.execute(
            select(Subscription).where(Subscription.id == first_subscription_id)
        )
        db_subscription = db_subscription_result.scalar_one()

        print("\nDB CHECK:")
        print("payment_count =", payment_count)
        print("event_count =", event_count)
        print("subscription_count =", subscription_count)
        print("db_order_status =", db_order.status)
        print("db_payment_status =", db_payment.status)
        print("db_subscription_status =", db_subscription.status)
        print("db_subscription_uuid =", db_subscription.uuid)
        print("db_subscription_expires_at =", db_subscription.expires_at)

        assert first_event.id == second_event.id
        assert first_payment.id == second_payment.id
        assert first_subscription_id == second_subscription.id
        assert first_uuid == second_subscription.uuid
        assert first_expires_at == second_subscription.expires_at

        assert payment_count == 1
        assert event_count == 1
        assert subscription_count == 1

        assert db_order.status == OrderStatus.ACTIVATED
        assert db_payment.status == PaymentStatus.CONFIRMED
        assert db_subscription.status == SubscriptionStatus.ACTIVE
        assert db_subscription.uuid == first_uuid
        assert db_subscription.expires_at == first_expires_at

        assert first_config_uri.startswith("vless://")
        assert second_config_uri.startswith("vless://")

        print("\nPAYMENT ACTIVATION DUPLICATE EVENT TEST PASSED")


if __name__ == "__main__":
    asyncio.run(main())