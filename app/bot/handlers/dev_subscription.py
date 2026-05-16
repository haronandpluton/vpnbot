from decimal import Decimal

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.enums import TariffCode
from app.payment_adapters.base import NormalizedTransaction
from app.payment_polling.processor import PaymentPollingProcessor
from app.services.order_service import OrderService

router = Router()


@router.message(Command("dev_create_active_subscription"))
async def dev_create_active_subscription_command(
    message: Message,
    session: AsyncSession,
):
    await message.answer("Dev-команда получена. Создаю подписку...")

    order_service = OrderService(session)

    order = await order_service.create_order(
        telegram_id=message.from_user.id,
        tariff_code=TariffCode.DEVICES_1,
        payment_option_code="usdt_trc20",
        username=message.from_user.username,
        first_name=message.from_user.first_name,
        last_name=message.from_user.last_name,
        language_code=message.from_user.language_code,
    )

    order.expected_amount = Decimal("4.00")
    order.expected_currency = "USDT"
    order.expected_network = "TRC20"
    order.destination_address = f"dev_active_receiver_{order.id}"

    await session.commit()

    tx = NormalizedTransaction(
        txid=f"dev_active_txid_{order.id}",
        amount=Decimal("4.00"),
        currency="USDT",
        network="TRC20",
        address_from="dev_mock_sender_wallet",
        address_to=order.destination_address,
        confirmations=3,
        provider="mock",
        raw_payload={
            "source": "dev_create_active_subscription",
            "order_id": order.id,
            "telegram_id": message.from_user.id,
        },
    )

    processor = PaymentPollingProcessor(session)
    event, payment, subscription, config_uri = await processor.process_transaction(tx)

    text = (
        "Dev-подписка создана и активирована.\n\n"
        f"Order ID: {order.id}\n"
        f"Payment ID: {payment.id}\n"
        f"Event ID: {event.id}\n"
        f"Subscription ID: {subscription.id}\n\n"
        "Теперь отправь команду:\n"
        "/my_subscription"
    )

    await message.answer(text)