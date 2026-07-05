from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


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


def tariff_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="1 устройство — 4 USDT",
                    callback_data="select_tariff:devices_1",
                )
            ],
            [
                InlineKeyboardButton(
                    text="2 устройства — скоро",
                    callback_data="select_tariff:devices_2",
                )
            ],
            [
                InlineKeyboardButton(
                    text="3 устройства — скоро",
                    callback_data="select_tariff:devices_3",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Назад",
                    callback_data="back_to_main_menu",
                )
            ],
        ]
    )


def payment_method_keyboard(tariff_code: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="CryptoBot — 4 USDT",
                    callback_data=f"select_payment:{tariff_code}:cryptobot_usdt",
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