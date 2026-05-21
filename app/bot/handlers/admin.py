from decimal import Decimal
from typing import Any

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.admin_menu import admin_back_keyboard, admin_main_menu_keyboard
from app.config.settings import get_settings
from app.services.admin_action_log_service import AdminActionLookupService
from app.services.admin_active_subscriptions_service import (
    AdminActiveSubscriptionsService,
)
from app.services.admin_invalid_payments_service import AdminInvalidPaymentsService
from app.services.admin_stats_service import AdminStatsService

router = Router()

TELEGRAM_MESSAGE_LIMIT = 3900


def _is_admin(telegram_id: int) -> bool:
    settings = get_settings()
    return telegram_id in settings.admin_ids


def _format_decimal(value: Decimal | None) -> str:
    if value is None:
        return "—"

    normalized = value.quantize(Decimal("0.00000001"))
    text = f"{normalized:f}"
    text = text.rstrip("0").rstrip(".")

    if not text:
        return "0"

    return text


def _format_datetime(value: Any) -> str:
    if value is None:
        return "—"

    return value.strftime("%d.%m.%Y %H:%M")


def _format_datetime_seconds(value: Any) -> str:
    if value is None:
        return "—"

    return value.strftime("%d.%m.%Y %H:%M:%S")


def _clean(value: Any) -> str:
    if value is None or value == "":
        return "—"

    return str(value)


def _split_messages(blocks: list[str], limit: int = TELEGRAM_MESSAGE_LIMIT) -> list[str]:
    messages: list[str] = []
    current = ""

    for block in blocks:
        if len(current) + len(block) > limit:
            if current:
                messages.append(current)
                current = ""

        current += block

    if current:
        messages.append(current)

    return messages


def _admin_menu_text() -> str:
    return (
        "<b>Админ-панель</b>\n\n"
        "Выбери раздел:\n\n"
        "Статистика — общие цифры проекта.\n"
        "Активные подписки — список действующих доступов.\n"
        "Некорректные платежи — wrong amount / wrong network / wrong currency.\n"
        "Журнал действий — последние ручные действия администраторов.\n"
        "Поиск — карточки заказа, платежа, подписки или пользователя."
    )


async def _send_admin_menu_message(message: Message) -> None:
    await message.answer(
        _admin_menu_text(),
        reply_markup=admin_main_menu_keyboard(),
        parse_mode="HTML",
    )


async def _edit_admin_menu_callback(callback: CallbackQuery) -> None:
    await callback.message.edit_text(
        _admin_menu_text(),
        reply_markup=admin_main_menu_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


def _format_stats_text(stats) -> str:
    return (
        "<b>Статистика проекта</b>\n\n"
        "<b>Пользователи</b>\n"
        f"Всего: {stats.users_total}\n\n"

        "<b>Заказы</b>\n"
        f"Всего: {stats.orders_total}\n"
        f"Ожидают оплату: {stats.orders_waiting_payment}\n"
        f"Оплачены: {stats.orders_paid}\n"
        f"Активированы: {stats.orders_activated}\n"
        f"Истекли: {stats.orders_expired}\n"
        f"Ошибочные: {stats.orders_failed}\n"
        f"Отменены: {stats.orders_cancelled}\n\n"

        "<b>Платежи</b>\n"
        f"Всего: {stats.payments_total}\n"
        f"Подтверждены: {stats.payments_confirmed}\n"
        f"Некорректные: {stats.payments_invalid}\n"
        f"Дубликаты: {stats.payments_duplicate}\n"
        f"Ошибки: {stats.payments_error}\n\n"

        "<b>Подписки</b>\n"
        f"Всего: {stats.subscriptions_total}\n"
        f"Активные: {stats.subscriptions_active}\n"
        f"Истекшие: {stats.subscriptions_expired}\n"
        f"Отключенные: {stats.subscriptions_disabled}\n\n"

        "<b>Выручка</b>\n"
        f"Confirmed payments: {_format_decimal(stats.confirmed_revenue_total)}"
    )


def _format_admin_actions_text(items) -> str:
    if not items:
        return (
            "<b>Журнал действий</b>\n\n"
            "Записей пока нет.\n\n"
            "Команды:\n"
            "<code>/admin_actions</code>\n"
            "<code>/admin_actions_subscription 15</code>\n"
            "<code>/admin_actions_user 58</code>"
        )

    blocks: list[str] = [
        "<b>Журнал действий</b>\n"
        "Последние 20 записей.\n"
        f"Найдено: {len(items)}\n\n"
    ]

    for item in items:
        admin_username = f"@{item.admin_username}" if item.admin_username else "—"

        blocks.append(
            f"<b>AdminAction #{item.action_id}</b>\n"
            f"Action: {_clean(item.action_type)}\n"
            f"Admin user ID: {_clean(item.admin_user_id)}\n"
            f"Admin TG ID: {_clean(item.admin_telegram_id)}\n"
            f"Admin username: {admin_username}\n"
            f"Target user ID: {_clean(item.target_user_id)}\n"
            f"Order ID: {_clean(item.order_id)}\n"
            f"Payment ID: {_clean(item.payment_id)}\n"
            f"Subscription ID: {_clean(item.subscription_id)}\n"
            f"Reason: {_clean(item.reason)}\n"
            f"Payload: <code>{_clean(item.payload)}</code>\n"
            f"Created: {_format_datetime_seconds(item.created_at)}\n"
            "Commands:\n"
        )

        if item.subscription_id is not None:
            blocks.append(
                f"<code>/admin_actions_subscription {item.subscription_id}</code>\n"
                f"<code>/admin_subscription {item.subscription_id}</code>\n"
            )

        if item.target_user_id is not None:
            blocks.append(
                f"<code>/admin_actions_user {item.target_user_id}</code>\n"
                f"<code>/admin_user {item.target_user_id}</code>\n"
            )

        if item.order_id is not None:
            blocks.append(f"<code>/admin_order {item.order_id}</code>\n")

        if item.payment_id is not None:
            blocks.append(f"<code>/admin_payment {item.payment_id}</code>\n")

        blocks.append("\n")

    return "".join(blocks)


async def _send_stats(message: Message, session: AsyncSession) -> None:
    stats = await AdminStatsService(session).get_stats()

    await message.answer(
        _format_stats_text(stats),
        reply_markup=admin_back_keyboard(),
        parse_mode="HTML",
    )


async def _send_stats_callback(callback: CallbackQuery, session: AsyncSession) -> None:
    stats = await AdminStatsService(session).get_stats()

    await callback.message.edit_text(
        _format_stats_text(stats),
        reply_markup=admin_back_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


async def _send_actions_callback(
    callback: CallbackQuery,
    session: AsyncSession,
) -> None:
    items = await AdminActionLookupService(session).get_last_actions(limit=20)
    text = _format_admin_actions_text(items)

    if len(text) <= TELEGRAM_MESSAGE_LIMIT:
        await callback.message.edit_text(
            text,
            reply_markup=admin_back_keyboard(),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    blocks = text.split("\n\n")
    prepared_blocks = [block + "\n\n" for block in blocks]
    messages = _split_messages(prepared_blocks)

    await callback.message.edit_text(
        messages[0],
        reply_markup=admin_back_keyboard(),
        parse_mode="HTML",
    )

    for next_text in messages[1:]:
        await callback.message.answer(
            next_text,
            reply_markup=admin_back_keyboard(),
            parse_mode="HTML",
        )

    await callback.answer()


async def _send_invalid_payments_callback(
    callback: CallbackQuery,
    session: AsyncSession,
) -> None:
    items = await AdminInvalidPaymentsService(session).get_last_invalid_payments(
        limit=10,
    )

    if not items:
        await callback.message.edit_text(
            "Некорректных платежей пока нет.",
            reply_markup=admin_back_keyboard(),
        )
        await callback.answer()
        return

    blocks: list[str] = [
        "<b>Некорректные платежи</b>\n"
        "Последние 10 записей:\n\n"
    ]

    for item in items:
        username_text = f"@{item.username}" if item.username else "—"

        blocks.append(
            f"<b>Payment #{item.payment_id}</b>\n"
            f"Order ID: {_clean(item.order_id)}\n"
            f"Event ID: {_clean(item.event_id)}\n"
            f"User ID: {_clean(item.user_id)}\n"
            f"Telegram ID: {_clean(item.telegram_id)}\n"
            f"Username: {username_text}\n"
            f"Amount: {_format_decimal(item.amount)} {_clean(item.currency)}\n"
            f"Network: {_clean(item.network)}\n"
            f"Reason: {_clean(item.reason)}\n"
            f"TXID: <code>{_clean(item.txid)}</code>\n"
            f"Created: {_format_datetime(item.created_at)}\n"
            f"Commands:\n"
            f"<code>/admin_payment {item.payment_id}</code>\n"
            f"<code>/admin_order {_clean(item.order_id)}</code>\n"
            "\n"
        )

    messages = _split_messages(blocks)

    await callback.message.edit_text(
        messages[0],
        reply_markup=admin_back_keyboard(),
        parse_mode="HTML",
    )

    for text in messages[1:]:
        await callback.message.answer(
            text,
            reply_markup=admin_back_keyboard(),
            parse_mode="HTML",
        )

    await callback.answer()


async def _send_active_subscriptions_callback(
    callback: CallbackQuery,
    session: AsyncSession,
) -> None:
    items = await AdminActiveSubscriptionsService(session).get_active_subscriptions(
        limit=50,
    )

    if not items:
        await callback.message.edit_text(
            "Активных подписок пока нет.",
            reply_markup=admin_back_keyboard(),
        )
        await callback.answer()
        return

    blocks: list[str] = [
        "<b>Активные подписки</b>\n"
        "Ближайшие к окончанию первые.\n"
        f"Найдено: {len(items)}\n\n"
    ]

    for item in items:
        username_text = f"@{item.username}" if item.username else "—"

        blocks.append(
            f"<b>Subscription #{item.subscription_id}</b>\n"
            f"Order ID: {_clean(item.order_id)}\n"
            f"User ID: {_clean(item.user_id)}\n"
            f"Telegram ID: {_clean(item.telegram_id)}\n"
            f"Username: {username_text}\n"
            f"Status: {_clean(item.status)}\n"
            f"Tariff: {_clean(item.order_tariff_code)}\n"
            f"Order status: {_clean(item.order_status)}\n"
            f"Device limit: {_clean(item.device_limit)}\n"
            f"VPN server ID: {_clean(item.vpn_server_id)}\n"
            f"Starts: {_format_datetime(item.starts_at)}\n"
            f"Expires: {_format_datetime(item.expires_at)}\n"
            f"Last access sent: {_format_datetime(item.last_access_sent_at)}\n"
            f"UUID: <code>{_clean(item.uuid)}</code>\n"
            f"Commands:\n"
            f"<code>/admin_subscription {item.subscription_id}</code>\n"
            f"<code>/admin_order {_clean(item.order_id)}</code>\n"
            f"<code>/admin_resend_config {_clean(item.order_id)}</code>\n"
            f"<code>/admin_extend_subscription {item.subscription_id} 30</code>\n"
            f"<code>/admin_disable_subscription {item.subscription_id} reason</code>\n"
            "\n"
        )

    messages = _split_messages(blocks)

    await callback.message.edit_text(
        messages[0],
        reply_markup=admin_back_keyboard(),
        parse_mode="HTML",
    )

    for text in messages[1:]:
        await callback.message.answer(
            text,
            reply_markup=admin_back_keyboard(),
            parse_mode="HTML",
        )

    await callback.answer()


@router.message(Command("admin"))
async def admin_command(message: Message):
    if message.from_user is None:
        return

    if not _is_admin(message.from_user.id):
        await message.answer("Нет доступа.")
        return

    await _send_admin_menu_message(message)


@router.message(Command("admin_stats"))
async def admin_stats_command(
    message: Message,
    session: AsyncSession,
):
    if message.from_user is None:
        return

    if not _is_admin(message.from_user.id):
        await message.answer("Нет доступа.")
        return

    await _send_stats(message, session)


@router.callback_query(F.data == "admin_menu:home")
async def admin_menu_home_callback(callback: CallbackQuery):
    if callback.from_user is None:
        return

    if not _is_admin(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return

    await _edit_admin_menu_callback(callback)


@router.callback_query(F.data == "admin_menu:stats")
async def admin_menu_stats_callback(
    callback: CallbackQuery,
    session: AsyncSession,
):
    if callback.from_user is None:
        return

    if not _is_admin(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return

    await _send_stats_callback(callback, session)


@router.callback_query(F.data == "admin_menu:active_subscriptions")
async def admin_menu_active_subscriptions_callback(
    callback: CallbackQuery,
    session: AsyncSession,
):
    if callback.from_user is None:
        return

    if not _is_admin(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return

    await _send_active_subscriptions_callback(callback, session)


@router.callback_query(F.data == "admin_menu:invalid_payments")
async def admin_menu_invalid_payments_callback(
    callback: CallbackQuery,
    session: AsyncSession,
):
    if callback.from_user is None:
        return

    if not _is_admin(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return

    await _send_invalid_payments_callback(callback, session)


@router.callback_query(F.data == "admin_menu:actions")
async def admin_menu_actions_callback(
    callback: CallbackQuery,
    session: AsyncSession,
):
    if callback.from_user is None:
        return

    if not _is_admin(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return

    await _send_actions_callback(callback, session)


@router.callback_query(F.data == "admin_menu:order_lookup_help")
async def admin_menu_order_lookup_help_callback(callback: CallbackQuery):
    if callback.from_user is None:
        return

    if not _is_admin(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return

    await callback.message.edit_text(
        "<b>Поиск заказа</b>\n\n"
        "Использование:\n"
        "<code>/admin_order 68</code>\n\n"
        "Команда покажет:\n"
        "Order, User, Payments, Events, Subscriptions.",
        reply_markup=admin_back_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "admin_menu:payment_lookup_help")
async def admin_menu_payment_lookup_help_callback(callback: CallbackQuery):
    if callback.from_user is None:
        return

    if not _is_admin(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return

    await callback.message.edit_text(
        "<b>Поиск платежа</b>\n\n"
        "Использование:\n"
        "<code>/admin_payment 96</code>\n\n"
        "Команда покажет:\n"
        "Payment, Order, User, Events, Subscriptions.",
        reply_markup=admin_back_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "admin_menu:subscription_lookup_help")
async def admin_menu_subscription_lookup_help_callback(callback: CallbackQuery):
    if callback.from_user is None:
        return

    if not _is_admin(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return

    await callback.message.edit_text(
        "<b>Поиск подписки</b>\n\n"
        "Использование:\n"
        "<code>/admin_subscription 14</code>\n\n"
        "Команда покажет:\n"
        "Subscription, User, Order, Payments, Events.",
        reply_markup=admin_back_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "admin_menu:user_lookup_help")
async def admin_menu_user_lookup_help_callback(callback: CallbackQuery):
    if callback.from_user is None:
        return

    if not _is_admin(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return

    await callback.message.edit_text(
        "<b>Поиск пользователя</b>\n\n"
        "По внутреннему User ID:\n"
        "<code>/admin_user 46</code>\n\n"
        "По Telegram ID:\n"
        "<code>/admin_user_tg 611113612212</code>\n\n"
        "Команда покажет:\n"
        "User, последние orders, payments, subscriptions.",
        reply_markup=admin_back_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()