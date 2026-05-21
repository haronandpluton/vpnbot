from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def admin_main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Статистика",
                    callback_data="admin_menu:stats",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Активные подписки",
                    callback_data="admin_menu:active_subscriptions",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Некорректные платежи",
                    callback_data="admin_menu:invalid_payments",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Поиск заказа",
                    callback_data="admin_menu:order_lookup_help",
                ),
                InlineKeyboardButton(
                    text="Поиск платежа",
                    callback_data="admin_menu:payment_lookup_help",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Поиск подписки",
                    callback_data="admin_menu:subscription_lookup_help",
                ),
                InlineKeyboardButton(
                    text="Поиск пользователя",
                    callback_data="admin_menu:user_lookup_help",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Обновить меню",
                    callback_data="admin_menu:home",
                )
            ],
        ]
    )


def admin_back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Назад в админ-меню",
                    callback_data="admin_menu:home",
                )
            ]
        ]
    )