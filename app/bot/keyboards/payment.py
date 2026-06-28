from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def payment_check_keyboard(
    order_id: int,
    *,
    payment_url: str | None = None,
    show_dev_button: bool = True,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []

    if payment_url:
        rows.append(
            [
                InlineKeyboardButton(
                    text="Оплатить через Volet",
                    url=payment_url,
                )
            ]
        )

    rows.append(
        [
            InlineKeyboardButton(
                text="Я оплатил / Проверить оплату",
                callback_data=f"check_payment:{order_id}",
            )
        ]
    )

    if show_dev_button:
        rows.append(
            [
                InlineKeyboardButton(
                    text="DEV: подтвердить mock-платёж",
                    callback_data=f"dev_confirm_payment:{order_id}",
                )
            ]
        )

    return InlineKeyboardMarkup(inline_keyboard=rows)