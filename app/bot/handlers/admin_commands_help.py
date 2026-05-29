from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app.bot.keyboards.admin_menu import admin_back_keyboard
from app.config.settings import get_settings

router = Router()


def _is_admin(telegram_id: int) -> bool:
    settings = get_settings()
    return telegram_id in settings.admin_ids


def _commands_help_text() -> str:
    return (
        "<b>Список доступных команд</b>\n\n"

        "<b>Пользовательские команды</b>\n\n"

        "<code>/start</code>\n"
        "Запуск бота и вход в основной сценарий.\n\n"

        "<code>/buy</code>\n"
        "Создание заказа на покупку VPN-доступа.\n\n"

        "<code>/my_subscription</code>\n"
        "Показывает активную VPN-подписку пользователя, срок действия, лимит устройств и VLESS-конфиг.\n\n"

        "<code>/info</code>\n"
        "Информационный раздел бота, если подключен соответствующий handler.\n\n"

        "<b>Админ-панель</b>\n\n"

        "<code>/admin</code>\n"
        "Главное меню администратора с кнопками: статистика, активные подписки, invalid payments, журнал действий, поиск и список команд.\n\n"

        "<code>/admin_stats</code>\n"
        "Общая статистика проекта: пользователи, заказы, платежи, подписки, выручка.\n\n"

        "<code>/admin_active_subscriptions</code>\n"
        "Список активных подписок, отсортированный по ближайшему окончанию.\n\n"

        "<code>/admin_invalid_payments</code>\n"
        "Список некорректных платежей: wrong_amount, wrong_network, wrong_currency.\n\n"

        "<b>Поиск сущностей</b>\n\n"

        "<code>/admin_order 49</code>\n"
        "Детальная карточка заказа: order, user, payments, events, subscriptions.\n\n"

        "<code>/admin_payment 45</code>\n"
        "Детальная карточка платежа: payment, order, user, events, subscriptions.\n\n"

        "<code>/admin_subscription 15</code>\n"
        "Детальная карточка подписки: subscription, user, order, payments, events.\n\n"

        "<code>/admin_user 46</code>\n"
        "Поиск пользователя по внутреннему User ID.\n\n"

        "<code>/admin_user_tg 611113612212</code>\n"
        "Поиск пользователя по Telegram ID.\n\n"

        "<b>Ручные действия администратора</b>\n\n"

        "<code>/admin_resend_config 72</code>\n"
        "Повторно отправляет пользователю VPN-конфиг по активированной подписке. Новый UUID не создается.\n\n"

        "<code>/admin_extend_subscription 15 30</code>\n"
        "Ручное продление подписки на указанное количество дней. Действие пишется в audit log.\n\n"

        "<code>/admin_disable_subscription 17 test_cleanup</code>\n"
        "Ручное отключение подписки с причиной. Действие пишется в audit log.\n\n"

        "<b>Журнал действий</b>\n\n"

        "<code>/admin_actions</code>\n"
        "Последние действия администраторов.\n\n"

        "<code>/admin_actions_subscription 17</code>\n"
        "Журнал действий по конкретной подписке.\n\n"

        "<code>/admin_actions_user 58</code>\n"
        "Журнал действий по конкретному пользователю.\n\n"

        "<b>Dev/test-команды</b>\n\n"

        "<code>/dev_create_active_subscription</code>\n"
        "Создает тестовую активную подписку. Используется только в разработке.\n\n"

        "<code>/test_payment_check</code>\n"
        "Тестовая команда проверки платежного сценария, если handler подключен.\n\n"

        "<b>Защита dev/test-команд</b>\n\n"
        "Dev/test-команды проходят через <code>DevCommandsGuardMiddleware</code>.\n"
        "Они выполняются только если пользователь является админом и в настройках включено:\n"
        "<code>DEV_MODE=true</code>\n\n"
        "На production должно быть:\n"
        "<code>DEV_MODE=false</code>"
    )


@router.message(Command("admin_commands"))
async def admin_commands_command(message: Message):
    if message.from_user is None:
        return

    if not _is_admin(message.from_user.id):
        await message.answer("Нет доступа.")
        return

    await message.answer(
        _commands_help_text(),
        reply_markup=admin_back_keyboard(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "admin_menu:commands_help")
async def admin_menu_commands_help_callback(callback: CallbackQuery):
    if callback.from_user is None:
        return

    if not _is_admin(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return

    await callback.message.edit_text(
        _commands_help_text(),
        reply_markup=admin_back_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()