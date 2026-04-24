import asyncio
import time
from decimal import Decimal

from sqlalchemy import select

from app.common.enums import TariffCode
from app.database.models import Order, Payment, Subscription
from app.database.session import SessionLocal
from app.payment_core.enums.order_status import OrderStatus
from app.payment_core.enums.payment_status import PaymentStatus
from app.payment_core.enums.subscription_status import SubscriptionStatus
from app.services.order_service import OrderService
from app.services.payment_service import PaymentService
from app.services.subscription_service import SubscriptionService


async def main():
    suffix = str(int(time.time() * 1000))

    telegram_id = int(f"566857{suffix[-6:]}")
    txid = f"subscription_txid_{suffix}"

    async with SessionLocal() as session:
        order_service = OrderService(session)
        payment_service = PaymentService(session)
        subscription_service = SubscriptionService(session)

        order = await order_service.create_order(
            telegram_id=telegram_id,
            tariff_code=TariffCode.DEVICES_1,
            payment_option_code="usdt_trc20",
            username=f"subscription_test_user_{suffix}",
            first_name="Subscription",
            last_name="Tester",
            language_code="ru",
        )

        print("ORDER READY:")
        print("id =", order.id)
        print("status =", order.status)
        print("user_id =", order.user_id)

        payment = await payment_service.create_payment_for_order(
            order_id=order.id,
            amount=Decimal("4.00"),
            txid=txid,
            address_from="sender_wallet",
            address_to="receiver_wallet",
            confirmations=3,
            raw_payload=f'{{"source": "subscription_test", "suffix": "{suffix}"}}',
        )

        payment = await payment_service.mark_payment_detected(payment.id)
        confirmed_payment, paid_order = await payment_service.confirm_payment(payment.id)

        print("\nPAYMENT CONFIRMED:")
        print("payment_id =", confirmed_payment.id)
        print("payment_status =", confirmed_payment.status)
        print("order_id =", paid_order.id)
        print("order_status =", paid_order.status)

        subscription, config_uri = (
            await subscription_service.activate_or_extend_by_order(paid_order.id)
        )

        print("\nSUBSCRIPTION ACTIVATED:")
        print("subscription_id =", subscription.id)
        print("subscription_status =", subscription.status)
        print("subscription_uuid =", subscription.uuid)
        print("subscription_device_limit =", subscription.device_limit)
        print("subscription_expires_at =", subscription.expires_at)
        print("config_uri =", config_uri)

        resent_subscription, resent_config_uri = await subscription_service.resend_access(
            user_id=paid_order.user_id
        )

        print("\nACCESS RESENT:")
        print("subscription_id =", resent_subscription.id)
        print("subscription_status =", resent_subscription.status)
        print("subscription_uuid =", resent_subscription.uuid)
        print("last_access_sent_at =", resent_subscription.last_access_sent_at)
        print("resent_config_uri =", resent_config_uri)

        db_order_result = await session.execute(
            select(Order).where(Order.id == paid_order.id)
        )
        db_order = db_order_result.scalar_one()

        db_payment_result = await session.execute(
            select(Payment).where(Payment.id == confirmed_payment.id)
        )
        db_payment = db_payment_result.scalar_one()

        db_subscription_result = await session.execute(
            select(Subscription).where(Subscription.id == subscription.id)
        )
        db_subscription = db_subscription_result.scalar_one()

        print("\nDB CHECK:")
        print("db_order_status =", db_order.status)
        print("db_payment_status =", db_payment.status)
        print("db_subscription_status =", db_subscription.status)
        print("db_subscription_uuid =", db_subscription.uuid)
        print("db_last_access_sent_at =", db_subscription.last_access_sent_at)

        assert db_payment.status == PaymentStatus.CONFIRMED
        assert db_order.status == OrderStatus.ACTIVATED
        assert db_subscription.status == SubscriptionStatus.ACTIVE
        assert db_subscription.user_id == paid_order.user_id
        assert db_subscription.order_id == paid_order.id
        assert db_subscription.uuid is not None
        assert db_subscription.device_limit == paid_order.device_limit
        assert db_subscription.last_access_sent_at is not None
        assert config_uri.startswith("vless://")
        assert resent_config_uri.startswith("vless://")
        assert resent_subscription.uuid == subscription.uuid

        print("\nSUBSCRIPTION SERVICE TEST PASSED")


if __name__ == "__main__":
    asyncio.run(main())