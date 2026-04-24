import asyncio
import time
from decimal import Decimal



from sqlalchemy import select

from app.common.enums import TariffCode
from app.database.models import Order, Payment
from app.database.session import SessionLocal
from app.services.order_service import OrderService
from app.services.payment_service import PaymentService


async def main():
    suffix = str(int(time.time() * 1000))

    telegram_id = int(f"566854{suffix[-6:]}")
    txid = f"test_txid_{suffix}"

    async with SessionLocal() as session:
        order_service = OrderService(session)
        payment_service = PaymentService(session)

        order = await order_service.create_order(
            telegram_id=telegram_id,
            tariff_code=TariffCode.DEVICES_1,
            payment_option_code="usdt_trc20",
            username=f"test_user_{suffix}",
            first_name="Test",
            last_name="User",
            language_code="ru",
        )

        print("ORDER READY:")
        print("id =", order.id)
        print("status =", order.status)
        print("payment_option_id =", order.payment_option_id)

        payment = await payment_service.create_payment_for_order(
            order_id=order.id,
            amount=Decimal("4.00"),
            txid=txid,
            address_from="sender_wallet",
            address_to="receiver_wallet",
            confirmations=1,
            raw_payload=f'{{"demo": true, "suffix": "{suffix}"}}',
        )

        print("\nPAYMENT CREATED:")
        print("id =", payment.id)
        print("status =", payment.status)
        print("txid =", payment.txid)

        detected_payment = await payment_service.mark_payment_detected(payment.id)

        print("\nPAYMENT DETECTED:")
        print("id =", detected_payment.id)
        print("status =", detected_payment.status)

        confirmed_payment, paid_order = await payment_service.confirm_payment(payment.id)

        print("\nPAYMENT CONFIRMED:")
        print("id =", confirmed_payment.id)
        print("status =", confirmed_payment.status)
        print("confirmed_at =", confirmed_payment.confirmed_at)

        print("\nORDER AFTER PAYMENT:")
        print("id =", paid_order.id)
        print("status =", paid_order.status)
        print("paid_at =", paid_order.paid_at)

        payment_result = await session.execute(
            select(Payment).where(Payment.id == payment.id)
        )
        db_payment = payment_result.scalar_one()

        order_result = await session.execute(
            select(Order).where(Order.id == order.id)
        )
        db_order = order_result.scalar_one()

        print("\nDB CHECK:")
        print("payment_status =", db_payment.status)
        print("order_status =", db_order.status)


import app.services.payment_service as ps
print(ps.__file__)

if __name__ == "__main__":
    asyncio.run(main())