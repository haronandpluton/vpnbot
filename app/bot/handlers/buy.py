
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.main_menu import payment_method_keyboard, tariff_keyboard
from app.bot.keyboards.payment import payment_check_keyboard
from app.common.enums import TariffCode
from app.config.settings import get_settings
from app.config.tariffs import (
    PURCHASABLE_TARIFF_CODES,
    TariffConfig,
    get_tariff,
)
from app.payment_adapters.cryptobot import CryptoBotAPIError
from app.services.cryptobot_payment_service import CryptoBotPaymentService
from app.services.order_service import OrderService

router = Router()

def _format_price_usd(value) -> str:
    return format(value.normalize(), "f")


def _days_word(days: int) -> str:
    if days % 10 == 1 and days % 100 != 11:
        return "день"

    if days % 10 in {2, 3, 4} and days % 100 not in {12, 13, 14}:
        return "дня"

    return "дней"


def _get_purchasable_tariff(raw_code: str) -> TariffConfig | None:
    try:
        tariff_code = TariffCode(raw_code)
    except ValueError:
        return None

    if tariff_code not in PURCHASABLE_TARIFF_CODES:
        return None

    return get_tariff(tariff_code)


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
    tariff_code_raw = callback.data.replace("select_tariff:", "")
    tariff = _get_purchasable_tariff(tariff_code_raw)

    if tariff is None:
        await callback.answer(
            "Этот тариф недоступен.",
            show_alert=True,
        )
        return

    text = (
        f"Тариф: {tariff.title}\n"
        f"Устройств: {tariff.device_limit}\n"
        f"Срок доступа: {tariff.duration_days} "
        f"{_days_word(tariff.duration_days)}\n"
        f"Стоимость: {_format_price_usd(tariff.price_usd)} USDT\n\n"
        "Оплачивая подписку, ты подтверждаешь, что ознакомился "
        "с правилами сервиса: /rules\n\n"
        "Выбери способ оплаты:"
    )

    await callback.message.edit_text(
        text,
        reply_markup=payment_method_keyboard(tariff.code.value),
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

    tariff = _get_purchasable_tariff(tariff_code_raw)

    if tariff is None:
        await callback.answer(
            "Этот тариф недоступен",
            show_alert=True,
        )
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
        tariff_code=tariff.code,
        payment_option_code=payment_option_code,
        username=callback.from_user.username,
        first_name=callback.from_user.first_name,
        last_name=callback.from_user.last_name,
        language_code=callback.from_user.language_code,
    )

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
        f"Тариф: {tariff.title}\n"
        f"Устройств: {order.device_limit}\n"
        f"Срок доступа: {order.duration_days} "
        f"{_days_word(order.duration_days)}\n"
        f"Сумма: {order.price_usd:.2f} USDT\n"
        "Оплата: CryptoBot\n\n"
        "Нажми «Оплатить через CryptoBot» и подтверди оплату "
        "в CryptoBot.\n\n"
        "После оплаты вернись в бот и нажми "
        "«Я оплатил / Проверить оплату»."
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
