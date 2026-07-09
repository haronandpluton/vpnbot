from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def vpn_access_keyboard(subscription_id: int) -> InlineKeyboardMarkup:
    show_config_callback = f"vpn_access:show_config:{subscription_id}"

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Подключить VPN",
                    callback_data=show_config_callback,
                )
            ],
            [
                InlineKeyboardButton(
                    text="Отправить доступ снова",
                    callback_data=show_config_callback,
                )
            ],
            [
                InlineKeyboardButton(
                    text="Купить ещё подписку",
                    callback_data="buy_vpn",
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
