from decimal import Decimal

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.main_menu import payment_method_keyboard, tariff_keyboard
from app.bot.keyboards.payment import payment_check_keyboard
from app.common.enums import CurrencyCode, TariffCode
from app.config.settings import get_settings
from app.payment_adapters.cryptobot import CryptoBotAPIError
from app.services.cryptobot_payment_service import CryptoBotPaymentService
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
        await callback.answer(
            "Этот тариф пока недоступен. Сейчас активен тариф на 1 устройство.",
            show_alert=True,
        )
        return

    text = (
        "Тариф: 1 устройство\n"
        "Стоимость: 4 USDT\n"
        "Срок: 30 дней\n\n"
        "Выбери способ оплаты:"
    )

    await callback.message.edit_text(
        text,
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

    if payment_option_code != "cryptobot_usdt":
        await callback.answer("Этот способ оплаты пока недоступен", show_alert=True)
        return

    settings = get_settings()
    if not settings.cryptobot_enabled:
        await callback.answer("CryptoBot сейчас отключен", show_alert=True)
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
    order.expected_currency = CurrencyCode.USDT
    order.expected_network = None

    try:
        invoice = await CryptoBotPaymentService(session).ensure_invoice_for_order(
            order.id
        )
    except CryptoBotAPIError as exc:
        await session.rollback()
        await callback.message.answer(
            "Не удалось создать счёт CryptoBot. Попробуй позже или обратись в поддержку."
        )
        await callback.answer("Ошибка создания счёта", show_alert=True)
        raise exc

    payment_url = invoice.get("pay_url") or order.destination_address

    text = (
        "Заказ создан.\n\n"
        f"Order ID: {order.id}\n"
        "Тариф: 1 устройство\n"
        "Срок: 30 дней\n"
        "Сумма: 4.00 USDT\n"
        "Оплата: CryptoBot\n\n"
        "Нажми «Оплатить через CryptoBot» и подтверди оплату в CryptoBot.\n\n"
        "После оплаты вернись в бот и нажми «Я оплатил / Проверить оплату»."
    )

    await callback.message.edit_text(
        text,
        reply_markup=payment_check_keyboard(
            order.id,
            payment_url=payment_url,
            payment_url_text="Оплатить через CryptoBot",
            show_dev_button=settings.dev_mode,
        ),
        parse_mode="HTML",
    )
    await callback.answer()
