import asyncio
import time
from decimal import Decimal

from app.common.enums import TariffCode
from app.database.session import SessionLocal
from app.payment_adapters.base import NormalizedTransaction
from app.payment_polling.processor import PaymentPollingProcessor
from app.services.order_service import OrderService
from app.services.payment_check_service import PaymentCheckService


async def main():
    suffix = str(int(time.time() * 1000))
    telegram_id = int(f"633333{suffix[-6:]}")

    async with SessionLocal() as session:
        order_service = OrderService(session)
        check_service = PaymentCheckService(session)

        order = await order_service.create_order(
            telegram_id=telegram_id,
            tariff_code=TariffCode.DEVICES_1,
            payment_option_code="usdt_trc20",
            username=f"payment_check_user_{suffix}",
            first_name="PaymentCheck",
            last_name="Tester",
            language_code="ru",
        )

        order.expected_amount = Decimal("4.00")
        order.expected_currency = "USDT"
        order.expected_network = "TRC20"
        order.destination_address = f"payment_check_receiver_{suffix}"
        await session.commit()

        waiting_result = await check_service.check_order_payment(order.id)

        assert waiting_result.status == "waiting_payment"
        assert waiting_result.order_id == order.id
        assert waiting_result.payment_id is None
        assert waiting_result.subscription_id is None

        tx = NormalizedTransaction(
            txid=f"payment_check_txid_{suffix}",
            amount=Decimal("4.00"),
            currency="USDT",
            network="TRC20",
            address_from="mock_sender_wallet",
            address_to=order.destination_address,
            confirmations=3,
            provider="mock",
            raw_payload={
                "source": "payment_check_test",
                "expected_amount": "4.00",
                "actual_amount": "4.00",
            },
        )

        processor = PaymentPollingProcessor(session)
        event, payment, subscription, config_uri = await processor.process_transaction(tx)

        activated_result = await check_service.check_order_payment(order.id)

        assert activated_result.status == "activated"
        assert activated_result.order_id == order.id
        assert activated_result.payment_id == payment.id
        assert activated_result.event_id == event.id
        assert activated_result.subscription_id == subscription.id
        assert config_uri is not None

        print("PAYMENT CHECK SERVICE TEST PASSED")


if __name__ == "__main__":
    asyncio.run(main())