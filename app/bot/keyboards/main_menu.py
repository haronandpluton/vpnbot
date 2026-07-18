from decimal import Decimal

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.bot.utils.custom_emoji import (
    GIFT_CUSTOM_EMOJI_ID,
    STAR_CUSTOM_EMOJI_ID,
)
from app.common.enums import TariffCode
from app.config.payment_options import (
    CRYPTOBOT_PAYMENT_OPTION_CODES,
    get_payment_option,
)
from app.config.tariffs import get_purchasable_tariffs, get_tariff

TELEGRAM_STARS_PAYMENT_OPTION_CODE = "telegram_stars"


def main_menu_keyboard(
    *,
    trial_eligible: bool = False,
) -> InlineKeyboardMarkup:
    if trial_eligible:
        primary_button = InlineKeyboardButton(
            text="GET 3 VPN DAYS",
            callback_data="activate_trial",
        )
    else:
        primary_button = InlineKeyboardButton(
            text="Buy VPN",
            callback_data="buy_vpn",
        )

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [primary_button],
            [
                InlineKeyboardButton(
                    text="My Subscription",
                    callback_data="my_subscription",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Download VPN",
                    callback_data="download_vpn",
                )
            ],
            [
                InlineKeyboardButton(
                    text="FAQ",
                    callback_data="faq",
                ),
                InlineKeyboardButton(
                    text="Support",
                    callback_data="support",
                ),
            ],
        ]
    )

def _format_price_usd(value: Decimal) -> str:
    return format(value.normalize(), "f")

def _format_tariff_button_price(value: Decimal) -> str:
    return _format_price_usd(value).replace(".", ",")


def tariff_keyboard(
    target_subscription_id: int | None = None,
) -> InlineKeyboardMarkup:
    rows = []

    for tariff in get_purchasable_tariffs():
        if target_subscription_id is None:
            callback_data = f"select_tariff:{tariff.code.value}"
        else:
            callback_data = f"renew_tariff:{target_subscription_id}:{tariff.code.value}"

        rows.append(
            [
                InlineKeyboardButton(
                    text=(
                        f"{_format_tariff_button_price(tariff.price_usd)}$ — "
                        f"{tariff.title.replace(' 🎁', '')}"
                    ),
                    callback_data=callback_data,
                    icon_custom_emoji_id=GIFT_CUSTOM_EMOJI_ID,
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
                text="Back",
                callback_data=back_callback,
            )
        ]
    )

    return InlineKeyboardMarkup(inline_keyboard=rows)


def payment_method_keyboard(
    tariff_code: str,
    target_subscription_id: int | None = None,
    *,
    telegram_stars_enabled: bool = False,
) -> InlineKeyboardMarkup:
    tariff = get_tariff(TariffCode(tariff_code))
    rows: list[list[InlineKeyboardButton]] = []
    currency_buttons: list[InlineKeyboardButton] = []

    for option_code in CRYPTOBOT_PAYMENT_OPTION_CODES:
        option = get_payment_option(option_code)
        if not option.is_active or option.currency is None:
            continue

        if target_subscription_id is None:
            callback_data = f"select_payment:{tariff.code.value}:{option.code}"
        else:
            callback_data = (
                f"renew_pay:{target_subscription_id}:{tariff.code.value}:{option.code}"
            )

        currency_buttons.append(
            InlineKeyboardButton(
                text=option.currency.value,
                callback_data=callback_data,
            )
        )

        if len(currency_buttons) == 2:
            rows.append(currency_buttons)
            currency_buttons = []

    if currency_buttons:
        rows.append(currency_buttons)
    stars_option = get_payment_option(
        TELEGRAM_STARS_PAYMENT_OPTION_CODE
    )

    if (
        telegram_stars_enabled
        and stars_option.is_active
        and tariff.stars_price is not None
        and tariff.stars_price > 0
    ):
        if target_subscription_id is None:
            stars_callback = (
                f"select_stars:{tariff.code.value}"
            )
        else:
            stars_callback = (
                f"renew_stars:{target_subscription_id}:"
                f"{tariff.code.value}"
            )

        rows.append(
            [
                InlineKeyboardButton(
                    text=(
                        f"Telegram Stars — "
                        f"{tariff.stars_price} XTR"
                    ),
                    callback_data=stars_callback,
                    icon_custom_emoji_id=STAR_CUSTOM_EMOJI_ID,
                )
            ]
        )

    if target_subscription_id is None:
        back_callback = "buy_vpn"
    else:
        back_callback = f"renew_subscription:{target_subscription_id}"

    rows.append(
        [
            InlineKeyboardButton(
                text="Back",
                callback_data=back_callback,
            )
        ]
    )

    return InlineKeyboardMarkup(inline_keyboard=rows)


def back_to_main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Back to Menu",
                    callback_data="back_to_main_menu",
                )
            ]
        ]
    )
