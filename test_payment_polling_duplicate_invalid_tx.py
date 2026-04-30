import asyncio
import time
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
    telegram_id = int(f"611113{suffix[-6:]}")

    async with SessionLocal() as session:
        order_service = OrderService(session)

        order = await order_service.create_order(
            telegram_id=telegram_id,
            tariff_code=TariffCode.DEVICES_1,
            payment_option_code="usdt_trc20",
            username=f"duplicate_invalid_tx_user_{suffix}",
            first_name="DuplicateInvalid",
            last_name="Tester",
            language_code="ru",
        )

        order.expected_amount = Decimal("4.00")
        order.expected_currency = "USDT"
        order.expected_network = "TRC20"
        order.destination_address = f"duplicate_invalid_receiver_{suffix}"
        await session.commit()

        tx = NormalizedTransaction(
            txid=f"duplicate_invalid_txid_{suffix}",
            amount=Decimal("3.00"),
            currency="USDT",
            network="TRC20",
            address_from="mock_sender_wallet",
            address_to=order.destination_address,
            confirmations=3,
            provider="mock",
            raw_payload={
                "source": "duplicate_invalid_test",
                "expected_amount": "4.00",
                "actual_amount": "3.00",
            },
        )

        processor = PaymentPollingProcessor(session)

        first_event, first_payment, first_subscription, first_config_uri = (
            await processor.process_transaction(tx)
        )

        second_event, second_payment, second_subscription, second_config_uri = (
            await processor.process_transaction(tx)
        )

        db_order = (
            await session.execute(select(Order).where(Order.id == order.id))
        ).scalar_one()

        events = list(
            (
                await session.execute(
                    select(PaymentEvent).where(PaymentEvent.txid == tx.txid)
                )
            ).scalars().all()
        )

        payments = list(
            (
                await session.execute(
                    select(Payment).where(Payment.txid == tx.txid)
                )
            ).scalars().all()
        )

        subscriptions = list(
            (
                await session.execute(
                    select(Subscription).where(Subscription.order_id == order.id)
                )
            ).scalars().all()
        )

        assert first_event.id == second_event.id
        assert first_payment.id == second_payment.id

        assert len(events) == 1
        assert len(payments) == 1
        assert len(subscriptions) == 0

        assert first_event.processed is True
        assert first_event.processing_status == "invalid"
        assert first_event.error_message == "wrong_amount"

        assert first_payment.status == PaymentStatus.INVALID
        assert first_payment.amount == Decimal("3.00000000") or first_payment.amount == Decimal("3.00")

        assert db_order.status == OrderStatus.WAITING_PAYMENT
        assert db_order.paid_at is None
        assert db_order.activated_at is None

        assert first_subscription is None
        assert second_subscription is None
        assert first_config_uri is None
        assert second_config_uri is None

        print("DUPLICATE INVALID TX TEST PASSED")


if __name__ == "__main__":
    asyncio.run(main())