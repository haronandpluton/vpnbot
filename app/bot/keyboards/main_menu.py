from decimal import Decimal

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.common.enums import TariffCode
from app.config.tariffs import get_purchasable_tariffs, get_tariff


def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Купить VPN",
                    callback_data="buy_vpn",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Моя подписка",
                    callback_data="my_subscription",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Скачать VPN",
                    callback_data="download_vpn",
                )
            ],
            [
                InlineKeyboardButton(
                    text="FAQ",
                    callback_data="faq",
                ),
                InlineKeyboardButton(
                    text="Поддержка",
                    callback_data="support",
                ),
            ],
        ]
    )


def _format_price_usd(value: Decimal) -> str:
    return format(value.normalize(), "f")


def tariff_keyboard(
    target_subscription_id: int | None = None,
) -> InlineKeyboardMarkup:
    rows = []

    for tariff in get_purchasable_tariffs():
        if target_subscription_id is None:
            callback_data = f"select_tariff:{tariff.code.value}"
        else:
            callback_data = (
                f"renew_tariff:{target_subscription_id}:{tariff.code.value}"
            )

        rows.append(
            [
                InlineKeyboardButton(
                    text=(
                        f"{tariff.title} — "
                        f"{_format_price_usd(tariff.price_usd)} USDT"
                    ),
                    callback_data=callback_data,
                )
            ]
        )

    if target_subscription_id is None:
        back_callback = "back_to_main_menu"
    else:
        back_callback = "my_subscription"

    rows.append(
        [
            InlineKeyboardButton(
                text="Назад",
                callback_data=back_callback,
            )
        ]
    )

    return InlineKeyboardMarkup(inline_keyboard=rows)


def payment_method_keyboard(
    tariff_code: str,
    target_subscription_id: int | None = None,
) -> InlineKeyboardMarkup:
    tariff = get_tariff(TariffCode(tariff_code))

    if target_subscription_id is None:
        payment_callback = (
            f"select_payment:{tariff.code.value}:cryptobot_usdt"
        )
        back_callback = "buy_vpn"
    else:
        payment_callback = (
            f"renew_pay:{target_subscription_id}:"
            f"{tariff.code.value}:cryptobot_usdt"
        )
        back_callback = f"renew_subscription:{target_subscription_id}"

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=(
                        f"CryptoBot — "
                        f"{_format_price_usd(tariff.price_usd)} USDT"
                    ),
                    callback_data=payment_callback,
                )
            ],
            [
                InlineKeyboardButton(
                    text="Назад",
                    callback_data=back_callback,
                )
            ],
        ]
    )


def back_to_main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Назад в меню",
                    callback_data="back_to_main_menu",
                )
            ]
        ]
    )
