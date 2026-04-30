import asyncio
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select

from app.common.enums import TariffCode
from app.database.models import Order, Payment, PaymentEvent, Subscription
from app.database.session import SessionLocal
from app.payment_adapters.base import NormalizedTransaction
from app.payment_core.enums.order_status import OrderStatus
from app.payment_core.enums.payment_status import PaymentStatus
from app.payment_polling.processor import PaymentPollingProcessor
from app.services.order_service import OrderService


async def main():
    suffix = str(int(time.time() * 1000))
    telegram_id = int(f"622223{suffix[-6:]}")

    async with SessionLocal() as session:
        order_service = OrderService(session)

        order = await order_service.create_order(
            telegram_id=telegram_id,
            tariff_code=TariffCode.DEVICES_1,
            payment_option_code="usdt_trc20",
            username=f"late_payment_test_user_{suffix}",
            first_name="LatePayment",
            last_name="Tester",
            language_code="ru",
        )

        order.expected_amount = Decimal("4.00")
        order.expected_currency = "USDT"
        order.expected_network = "TRC20"
        order.destination_address = f"late_payment_receiver_{suffix}"
        order.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        await session.commit()

        tx = NormalizedTransaction(
            txid=f"late_payment_txid_{suffix}",
            amount=Decimal("4.00"),
            currency="USDT",
            network="TRC20",
            address_from="mock_sender_wallet",
            address_to=order.destination_address,
            confirmations=3,
            provider="mock",
            raw_payload={
                "source": "late_payment_test",
                "expected_amount": "4.00",
                "actual_amount": "4.00",
                "order_expired": True,
            },
        )

        processor = PaymentPollingProcessor(session)
        event, payment, subscription, config_uri = await processor.process_transaction(tx)

        db_order = (
            await session.execute(select(Order).where(Order.id == order.id))
        ).scalar_one()

        db_event = (
            await session.execute(select(PaymentEvent).where(PaymentEvent.id == event.id))
        ).scalar_one()

        db_payment = (
            await session.execute(select(Payment).where(Payment.id == payment.id))
        ).scalar_one()

        db_subscriptions = list(
            (
                await session.execute(
                    select(Subscription).where(Subscription.order_id == order.id)
                )
            ).scalars().all()
        )

        assert db_event.processed is True
        assert db_event.processing_status == "expired"
        assert db_event.error_message == "Late payment for expired order"

        assert db_payment.status == PaymentStatus.EXPIRED
        assert db_payment.amount == Decimal("4.00000000") or db_payment.amount == Decimal("4.00")
        assert db_payment.currency == "USDT"
        assert db_payment.network == "TRC20"

        assert db_order.status == OrderStatus.EXPIRED
        assert db_order.paid_at is None
        assert db_order.activated_at is None

        assert len(db_subscriptions) == 0
        assert subscription is None
        assert config_uri is None

        print("LATE PAYMENT POLLING TEST PASSED")


if __name__ == "__main__":
    asyncio.run(main())