from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.main_menu import payment_method_keyboard, tariff_keyboard
from app.bot.keyboards.payment import payment_check_keyboard
from app.common.enums import TariffCode
from app.config.payment_options import (
    get_payment_option,
    is_cryptobot_payment_option,
)
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


def _parse_positive_id(raw_value: str) -> int | None:
    if not raw_value.isdigit():
        return None

    value = int(raw_value)

    if value <= 0:
        return None

    return value


def _tariff_details_text(
    tariff: TariffConfig,
    *,
    target_subscription_id: int | None = None,
) -> str:
    if target_subscription_id is None:
        title = f"Тариф: {tariff.title}"
    else:
        title = (
            f"Продление подписки ID: {target_subscription_id}\nТариф: {tariff.title}"
        )

    return (
        f"{title}\n"
        f"Устройств: {tariff.device_limit}\n"
        f"Срок доступа: {tariff.duration_days} "
        f"{_days_word(tariff.duration_days)}\n"
        f"Стоимость: {_format_price_usd(tariff.price_usd)} USD\n\n"
        "Оплачивая подписку, ты подтверждаешь, что ознакомился "
        "с правилами сервиса: /rules\n\n"
        "Выберите валюту оплаты:"
    )


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


@router.callback_query(F.data.startswith("renew_subscription:"))
async def renew_subscription_callback(callback: CallbackQuery):
    subscription_id_raw = callback.data.removeprefix("renew_subscription:")
    subscription_id = _parse_positive_id(subscription_id_raw)

    if subscription_id is None:
        await callback.answer(
            "Некорректная подписка.",
            show_alert=True,
        )
        return

    await callback.message.edit_text(
        (f"Продление подписки ID: {subscription_id}\n\nВыбери срок продления:"),
        reply_markup=tariff_keyboard(
            target_subscription_id=subscription_id,
        ),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("select_tariff:"))
async def select_tariff_callback(callback: CallbackQuery):
    tariff_code_raw = callback.data.removeprefix("select_tariff:")
    tariff = _get_purchasable_tariff(tariff_code_raw)

    if tariff is None:
        await callback.answer(
            "Этот тариф недоступен.",
            show_alert=True,
        )
        return

    await callback.message.edit_text(
        _tariff_details_text(tariff),
        reply_markup=payment_method_keyboard(tariff.code.value),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("renew_tariff:"))
async def select_renewal_tariff_callback(callback: CallbackQuery):
    parts = callback.data.split(":")

    if len(parts) != 3:
        await callback.answer(
            "Некорректный выбор тарифа.",
            show_alert=True,
        )
        return

    _, subscription_id_raw, tariff_code_raw = parts
    subscription_id = _parse_positive_id(subscription_id_raw)
    tariff = _get_purchasable_tariff(tariff_code_raw)

    if subscription_id is None:
        await callback.answer(
            "Некорректная подписка.",
            show_alert=True,
        )
        return

    if tariff is None:
        await callback.answer(
            "Этот тариф недоступен.",
            show_alert=True,
        )
        return

    await callback.message.edit_text(
        _tariff_details_text(
            tariff,
            target_subscription_id=subscription_id,
        ),
        reply_markup=payment_method_keyboard(
            tariff.code.value,
            target_subscription_id=subscription_id,
        ),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("select_payment:"))
@router.callback_query(F.data.startswith("renew_pay:"))
async def select_payment_callback(
    callback: CallbackQuery,
    session: AsyncSession,
):
    parts = callback.data.split(":")
    target_subscription_id: int | None = None

    if callback.data.startswith("select_payment:"):
        if len(parts) != 3:
            await callback.answer(
                "Некорректный выбор оплаты",
                show_alert=True,
            )
            return

        _, tariff_code_raw, payment_option_code = parts
    else:
        if len(parts) != 4:
            await callback.answer(
                "Некорректный выбор оплаты",
                show_alert=True,
            )
            return

        (
            _,
            subscription_id_raw,
            tariff_code_raw,
            payment_option_code,
        ) = parts
        target_subscription_id = _parse_positive_id(subscription_id_raw)

        if target_subscription_id is None:
            await callback.answer(
                "Некорректная подписка.",
                show_alert=True,
            )
            return

    tariff = _get_purchasable_tariff(tariff_code_raw)

    if tariff is None:
        await callback.answer(
            "Этот тариф недоступен",
            show_alert=True,
        )
        return

    try:
        payment_option = get_payment_option(payment_option_code)
    except ValueError:
        payment_option = None

    if (
        payment_option is None
        or not payment_option.is_active
        or payment_option.currency is None
        or not is_cryptobot_payment_option(payment_option_code)
    ):
        await callback.answer(
            "Этот способ оплаты пока недоступен",
            show_alert=True,
        )
        return

    settings = get_settings()
    if not settings.cryptobot_enabled:
        await callback.answer(
            "CryptoBot сейчас отключен",
            show_alert=True,
        )
        return

    order_service = OrderService(session)

    create_order_kwargs = {
        "telegram_id": callback.from_user.id,
        "tariff_code": tariff.code,
        "payment_option_code": payment_option_code,
        "username": callback.from_user.username,
        "first_name": callback.from_user.first_name,
        "last_name": callback.from_user.last_name,
        "language_code": callback.from_user.language_code,
    }

    if target_subscription_id is not None:
        create_order_kwargs["target_subscription_id"] = target_subscription_id

    try:
        order = await order_service.create_order(**create_order_kwargs)
    except ValueError:
        if target_subscription_id is None:
            raise

        await callback.answer(
            "Эту подписку нельзя продлить.",
            show_alert=True,
        )
        return

    try:
        invoice = await CryptoBotPaymentService(session).ensure_invoice_for_order(
            order.id
        )
    except CryptoBotAPIError as exc:
        await session.rollback()
        await callback.message.answer(
            "Не удалось создать счёт CryptoBot. "
            "Попробуй позже или обратись в поддержку."
        )
        await callback.answer(
            "Ошибка создания счёта",
            show_alert=True,
        )
        raise exc

    payment_url = (
        invoice.get("bot_invoice_url")
        or invoice.get("pay_url")
        or invoice.get("mini_app_invoice_url")
        or invoice.get("web_app_invoice_url")
        or order.destination_address
    )

    if target_subscription_id is None:
        order_title = "Заказ создан."
        target_line = ""
    else:
        order_title = "Заказ на продление создан."
        target_line = f"Подписка ID: {target_subscription_id}\n"

    text = (
        f"{order_title}\n\n"
        f"Order ID: {order.id}\n"
        f"{target_line}"
        f"Тариф: {tariff.title}\n"
        f"Устройств: {order.device_limit}\n"
        f"Срок доступа: {order.duration_days} "
        f"{_days_word(order.duration_days)}\n"
        f"Стоимость: {order.price_usd:.2f} USD\n"
        f"Валюта оплаты: {payment_option.currency.value}\n"
        "Оплата: CryptoBot\n\n"
        "Нажми «Оплатить через CryptoBot». CryptoBot рассчитает "
        "точную сумму в выбранной валюте по цене заказа в USD.\n\n"
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
