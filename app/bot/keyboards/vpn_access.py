from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def vpn_access_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Подключить VPN",
                    callback_data="vpn_access:show_config",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Отправить доступ снова",
                    callback_data="vpn_access:show_config",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Happ VPN: Android",
                    callback_data="vpn_access:happ_android",
                ),
                InlineKeyboardButton(
                    text="Happ VPN: iPhone",
                    callback_data="vpn_access:happ_ios",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Если Happ не открывается",
                    callback_data="vpn_access:happ_fallback",
                )
            ],
        ]
    )