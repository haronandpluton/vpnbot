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
                    text="USDT TRC20",
                    callback_data=f"select_payment:{tariff_code}:usdt_trc20",
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