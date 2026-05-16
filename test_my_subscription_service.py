import asyncio
import time
from decimal import Decimal

from app.common.enums import TariffCode
from app.database.session import SessionLocal
from app.payment_adapters.base import NormalizedTransaction
from app.payment_polling.processor import PaymentPollingProcessor
from app.services.my_subscription_service import MySubscriptionService
from app.services.order_service import OrderService


async def main():
    suffix = str(int(time.time() * 1000))
    telegram_id = int(f"644444{suffix[-6:]}")

    async with SessionLocal() as session:
        order_service = OrderService(session)

        order = await order_service.create_order(
            telegram_id=telegram_id,
            tariff_code=TariffCode.DEVICES_1,
            payment_option_code="usdt_trc20",
            username=f"my_subscription_user_{suffix}",
            first_name="MySubscription",
            last_name="Tester",
            language_code="ru",
        )

        order.expected_amount = Decimal("4.00")
        order.expected_currency = "USDT"
        order.expected_network = "TRC20"
        order.destination_address = f"my_subscription_receiver_{suffix}"
        await session.commit()

        tx = NormalizedTransaction(
            txid=f"my_subscription_txid_{suffix}",
            amount=Decimal("4.00"),
            currency="USDT",
            network="TRC20",
            address_from="mock_sender_wallet",
            address_to=order.destination_address,
            confirmations=3,
            provider="mock",
            raw_payload={
                "source": "my_subscription_test",
                "expected_amount": "4.00",
                "actual_amount": "4.00",
            },
        )

        processor = PaymentPollingProcessor(session)
        event, payment, subscription, config_uri = await processor.process_transaction(tx)

        assert subscription is not None
        assert config_uri is not None

        result = await MySubscriptionService(
            session
        ).get_active_subscription_by_telegram_id(
            telegram_id=telegram_id,
        )

        assert result.status == "active"
        assert result.user_id == order.user_id
        assert result.subscription_id == subscription.id
        assert result.config_uri is not None
        assert result.config_uri.startswith("vless://")
        assert result.device_limit == order.device_limit

        print("MY SUBSCRIPTION SERVICE TEST PASSED")


if __name__ == "__main__":
    asyncio.run(main())