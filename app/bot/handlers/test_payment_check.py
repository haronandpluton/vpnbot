from decimal import Decimal

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.payment import payment_check_keyboard
from app.common.enums import TariffCode
from app.services.order_service import OrderService

router = Router()


@router.message(Command("test_payment_check"))
async def test_payment_check_command(
    message: Message,
    session: AsyncSession,
):
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
    order.destination_address = f"test_receiver_order_{order.id}"

    await session.commit()

    text = (
        "Тестовый заказ создан.\n\n"
        f"Order ID: {order.id}\n"
        "Сумма: 4.00 USDT\n"
        "Сеть: TRC20\n\n"
        "Нажми кнопку ниже, чтобы проверить payment check handler."
    )

    await message.answer(
        text,
        reply_markup=payment_check_keyboard(order.id),
    )