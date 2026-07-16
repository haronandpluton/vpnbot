from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def vpn_access_keyboard(
    subscription_id: int,
    *,
    renewable: bool = True,
) -> InlineKeyboardMarkup:
    show_config_callback = (
        f"vpn_access:show_config:{subscription_id}"
    )

    rows = [
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
    ]

    if renewable:
        rows.append(
            [
                InlineKeyboardButton(
                    text="Renew Subscription",
                    callback_data=(
                        f"renew_subscription:{subscription_id}"
                    ),
                )
            ]
        )

    rows.append(
        [
            InlineKeyboardButton(
                text=(
                    "Buy Another Subscription"
                    if renewable
                    else "Buy VPN"
                ),
                callback_data="buy_vpn",
            )
        ]
    )

    rows.extend(
        [
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

    return InlineKeyboardMarkup(
        inline_keyboard=rows,
    )


def expired_subscription_keyboard(
    subscription_id: int,
    *,
    renewable: bool = True,
) -> InlineKeyboardMarkup:
    if renewable:
        button = InlineKeyboardButton(
            text="Renew Subscription",
            callback_data=(
                f"renew_subscription:{subscription_id}"
            ),
        )
    else:
        button = InlineKeyboardButton(
            text="Buy VPN",
            callback_data="buy_vpn",
        )

    return InlineKeyboardMarkup(
        inline_keyboard=[[button]],
    )
