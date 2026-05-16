from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def payment_check_keyboard(order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Я оплатил / Проверить оплату",
                    callback_data=f"check_payment:{order_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="DEV: подтвердить mock-платеж",
                    callback_data=f"dev_confirm_payment:{order_id}",
                )
            ],
        ]
    )