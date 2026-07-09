from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from decimal import Decimal

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

def tariff_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=(
                    f"{tariff.title} — "
                    f"{_format_price_usd(tariff.price_usd)} USDT"
                ),
                callback_data=f"select_tariff:{tariff.code.value}",
            )
        ]
        for tariff in get_purchasable_tariffs()
    ]

    rows.append(
        [
            InlineKeyboardButton(
                text="Назад",
                callback_data="back_to_main_menu",
            )
        ]
    )

    return InlineKeyboardMarkup(inline_keyboard=rows)


def payment_method_keyboard(tariff_code: str) -> InlineKeyboardMarkup:
    tariff = get_tariff(TariffCode(tariff_code))

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=(
                        f"CryptoBot — "
                        f"{_format_price_usd(tariff.price_usd)} USDT"
                    ),
                    callback_data=(
                        f"select_payment:{tariff.code.value}:cryptobot_usdt"
                    ),
                )
            ],
            [
                InlineKeyboardButton(
                    text="Назад",
                    callback_data="buy_vpn",
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