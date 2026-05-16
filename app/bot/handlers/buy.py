from decimal import Decimal

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.main_menu import payment_method_keyboard, tariff_keyboard
from app.bot.keyboards.payment import payment_check_keyboard
from app.common.enums import TariffCode
from app.services.order_service import OrderService

router = Router()


@router.message(Command("buy"))
async def buy_command(message: Message):
    await message.answer(
        "Выбери тариф:",
        reply_markup=tariff_keyboard(),
    )


@router.callback_query(F.data == "buy_vpn")
async def buy_vpn_callback(callback: CallbackQuery):
    await callback.message.edit_text(
        "Выбери тариф:",
        reply_markup=tariff_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("select_tariff:"))
async def select_tariff_callback(callback: CallbackQuery):
    tariff_code = callback.data.replace("select_tariff:", "")

    if tariff_code != "devices_1":
        await callback.answer("Этот тариф пока недоступен", show_alert=True)
        return

    await callback.message.edit_text(
        "Выбери способ оплаты:",
        reply_markup=payment_method_keyboard(tariff_code),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("select_payment:"))
async def select_payment_callback(
    callback: CallbackQuery,
    session: AsyncSession,
):
    parts = callback.data.split(":")

    if len(parts) != 3:
        await callback.answer("Некорректный выбор оплаты", show_alert=True)
        return

    _, tariff_code_raw, payment_option_code = parts

    if tariff_code_raw != "devices_1":
        await callback.answer("Этот тариф пока недоступен", show_alert=True)
        return

    if payment_option_code != "usdt_trc20":
        await callback.answer("Этот способ оплаты пока недоступен", show_alert=True)
        return

    order_service = OrderService(session)

    order = await order_service.create_order(
        telegram_id=callback.from_user.id,
        tariff_code=TariffCode.DEVICES_1,
        payment_option_code=payment_option_code,
        username=callback.from_user.username,
        first_name=callback.from_user.first_name,
        last_name=callback.from_user.last_name,
        language_code=callback.from_user.language_code,
    )

    order.expected_amount = Decimal("4.00")
    order.expected_currency = "USDT"
    order.expected_network = "TRC20"

    if order.destination_address is None:
        order.destination_address = f"payment_receiver_order_{order.id}"

    await session.commit()

    text = (
        "Заказ создан.\n\n"
        f"Order ID: {order.id}\n"
        "Тариф: 1 устройство\n"
        "Сумма: 4.00 USDT\n"
        "Сеть: TRC20\n\n"
        "Адрес для оплаты:\n"
        f"<code>{order.destination_address}</code>\n\n"
        "После оплаты нажми кнопку ниже."
    )

    await callback.message.edit_text(
        text,
        reply_markup=payment_check_keyboard(order.id),
        parse_mode="HTML",
    )
    await callback.answer()