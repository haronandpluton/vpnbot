from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def vpn_access_keyboard(subscription_id: int) -> InlineKeyboardMarkup:
    show_config_callback = f"vpn_access:show_config:{subscription_id}"

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Connect VPN",
                    callback_data=show_config_callback,
                )
            ],
            [
                InlineKeyboardButton(
                    text="Send Access Again",
                    callback_data=show_config_callback,
                )
            ],
            [
                InlineKeyboardButton(
                    text="Renew Subscription",
                    callback_data=f"renew_subscription:{subscription_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Buy Another Subscription",
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
                    text="If Happ Does Not Open",
                    callback_data="vpn_access:happ_fallback",
                )
            ],
        ]
    )


def expired_subscription_keyboard(
    subscription_id: int,
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Renew Subscription",
                    callback_data=(
                        f"renew_subscription:{subscription_id}"
                    ),
                )
            ]
        ]
    )
