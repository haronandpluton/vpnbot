import asyncio
import time
from decimal import Decimal

from sqlalchemy import func, select

from app.common.enums import TariffCode
from app.database.models import Order, Payment, Subscription
from app.database.session import SessionLocal
from app.payment_core.enums.order_status import OrderStatus
from app.payment_core.enums.payment_status import PaymentStatus
from app.payment_core.enums.subscription_status import SubscriptionStatus
from app.services.order_service import OrderService
from app.services.payment_service import PaymentService
from app.services.subscription_service import SubscriptionService


async def create_paid_order(
    order_service: OrderService,
    payment_service: PaymentService,
    telegram_id: int,
    suffix: str,
    step: str,
):
    order = await order_service.create_order(
        telegram_id=telegram_id,
        tariff_code=TariffCode.DEVICES_1,
        payment_option_code="usdt_trc20",
        username=f"renewal_test_user_{suffix}",
        first_name="Renewal",
        last_name="Tester",
        language_code="ru",
    )

    payment = await payment_service.create_payment_for_order(
        order_id=order.id,
        amount=Decimal("4.00"),
        txid=f"renewal_txid_{step}_{suffix}",
        address_from="sender_wallet",
        address_to="receiver_wallet",
        confirmations=3,
        raw_payload=f'{{"source": "renewal_test", "step": "{step}", "suffix": "{suffix}"}}',
    )

    payment = await payment_service.mark_payment_detected(payment.id)
    confirmed_payment, paid_order = await payment_service.confirm_payment(payment.id)

    return paid_order, confirmed_payment


async def main():
    suffix = str(int(time.time() * 1000))
    telegram_id = int(f"566858{suffix[-6:]}")

    async with SessionLocal() as session:
        order_service = OrderService(session)
        payment_service = PaymentService(session)
        subscription_service = SubscriptionService(session)

        first_order, first_payment = await create_paid_order(
            order_service=order_service,
            payment_service=payment_service,
            telegram_id=telegram_id,
            suffix=suffix,
            step="first",
        )

        first_subscription, first_config_uri = (
            await subscription_service.activate_or_extend_by_order(first_order.id)
        )

        print("FIRST SUBSCRIPTION:")
        print("order_id =", first_order.id)
        print("payment_id =", first_payment.id)
        print("subscription_id =", first_subscription.id)
        print("uuid =", first_subscription.uuid)
        print("expires_at =", first_subscription.expires_at)
        print("config_uri =", first_config_uri)

        first_subscription_id = first_subscription.id
        first_uuid = first_subscription.uuid
        first_expires_at = first_subscription.expires_at

        second_order, second_payment = await create_paid_order(
            order_service=order_service,
            payment_service=payment_service,
            telegram_id=telegram_id,
            suffix=suffix,
            step="second",
        )

        renewed_subscription, second_config_uri = (
            await subscription_service.activate_or_extend_by_order(second_order.id)
        )

        print("\nRENEWED SUBSCRIPTION:")
        print("order_id =", second_order.id)
        print("payment_id =", second_payment.id)
        print("subscription_id =", renewed_subscription.id)
        print("uuid =", renewed_subscription.uuid)
        print("expires_at =", renewed_subscription.expires_at)
        print("config_uri =", second_config_uri)

        subscription_count_result = await session.execute(
            select(func.count())
            .select_from(Subscription)
            .where(Subscription.user_id == second_order.user_id)
        )
        subscription_count = subscription_count_result.scalar_one()

        db_first_order_result = await session.execute(
            select(Order).where(Order.id == first_order.id)
        )
        db_first_order = db_first_order_result.scalar_one()

        db_second_order_result = await session.execute(
            select(Order).where(Order.id == second_order.id)
        )
        db_second_order = db_second_order_result.scalar_one()

        db_second_payment_result = await session.execute(
            select(Payment).where(Payment.id == second_payment.id)
        )
        db_second_payment = db_second_payment_result.scalar_one()

        db_subscription_result = await session.execute(
            select(Subscription).where(Subscription.id == first_subscription_id)
        )
        db_subscription = db_subscription_result.scalar_one()

        print("\nDB CHECK:")
        print("subscription_count =", subscription_count)
        print("first_order_status =", db_first_order.status)
        print("second_order_status =", db_second_order.status)
        print("second_payment_status =", db_second_payment.status)
        print("subscription_status =", db_subscription.status)
        print("subscription_uuid =", db_subscription.uuid)
        print("subscription_expires_at =", db_subscription.expires_at)

        assert db_first_order.status == OrderStatus.ACTIVATED
        assert db_second_order.status == OrderStatus.ACTIVATED
        assert db_second_payment.status == PaymentStatus.CONFIRMED

        assert subscription_count == 1
        assert db_subscription.status == SubscriptionStatus.ACTIVE
        assert db_subscription.id == first_subscription_id
        assert db_subscription.uuid == first_uuid
        assert db_subscription.expires_at > first_expires_at
        assert second_config_uri.startswith("vless://")

        print("\nSUBSCRIPTION RENEWAL TEST PASSED")


if __name__ == "__main__":
    asyncio.run(main())