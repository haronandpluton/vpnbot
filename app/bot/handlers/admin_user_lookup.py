from decimal import Decimal
from typing import Any

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import get_settings
from app.services.admin_user_lookup_service import AdminUserLookupService

router = Router()


def _is_admin(telegram_id: int) -> bool:
    settings = get_settings()
    return telegram_id in settings.admin_ids


def _parse_id_from_command(message: Message) -> int | None:
    if message.text is None:
        return None

    parts = message.text.strip().split(maxsplit=1)

    if len(parts) != 2:
        return None

    raw_id = parts[1].strip()

    if not raw_id.isdigit():
        return None

    return int(raw_id)


def _clean(value: Any) -> str:
    if value is None or value == "":
        return "—"

    return str(value)


def _enum_to_str(value: Any) -> str:
    if value is None:
        return "—"

    if hasattr(value, "value"):
        return str(value.value)

    return str(value)


def _format_datetime(value: Any) -> str:
    if value is None:
        return "—"

    return value.strftime("%d.%m.%Y %H:%M:%S")


def _format_decimal(value: Decimal | None) -> str:
    if value is None:
        return "—"

    normalized = value.quantize(Decimal("0.00000001"))
    text = f"{normalized:f}".rstrip("0").rstrip(".")

    return text or "0"


def _format_user_block(user) -> str:
    username = f"@{user.username}" if user.username else "—"

    return (
        "<b>User</b>\n"
        f"ID: {user.id}\n"
        f"Telegram ID: {user.telegram_id}\n"
        f"Username: {username}\n"
        f"Name: {_clean(user.first_name)} {_clean(user.last_name)}\n"
        f"Language: {_clean(user.language_code)}\n"
        f"Admin: {user.is_admin}\n"
        f"Blocked: {user.is_blocked}\n"
        f"Created: {_format_datetime(user.created_at)}\n"
        f"Updated: {_format_datetime(user.updated_at)}\n"
    )


def _format_order_short(order) -> str:
    return (
        f"<b>Order #{order.id}</b>\n"
        f"Status: {_enum_to_str(order.status)}\n"
        f"Tariff: {_enum_to_str(order.tariff_code)}\n"
        f"Device limit: {_clean(order.device_limit)}\n"
        f"Expected: {_format_decimal(order.expected_amount)} "
        f"{_enum_to_str(order.expected_currency)} / {_enum_to_str(order.expected_network)}\n"
        f"Price USD: {_format_decimal(order.price_usd)}\n"
        f"Created: {_format_datetime(order.created_at)}\n"
        f"Command: <code>/admin_order {order.id}</code>\n"
    )


def _format_payment_short(payment) -> str:
    return (
        f"<b>Payment #{payment.id}</b>\n"
        f"Order ID: {_clean(payment.order_id)}\n"
        f"Status: {_enum_to_str(payment.status)}\n"
        f"Amount: {_format_decimal(payment.amount)} "
        f"{_enum_to_str(payment.currency)} / {_enum_to_str(payment.network)}\n"
        f"TXID: <code>{_clean(payment.txid)}</code>\n"
        f"Created: {_format_datetime(payment.created_at)}\n"
        f"Command: <code>/admin_payment {payment.id}</code>\n"
    )


def _format_subscription_short(subscription) -> str:
    return (
        f"<b>Subscription #{subscription.id}</b>\n"
        f"Order ID: {_clean(subscription.order_id)}\n"
        f"Status: {_enum_to_str(subscription.status)}\n"
        f"Device limit: {_clean(subscription.device_limit)}\n"
        f"Expires at: {_format_datetime(subscription.expires_at)}\n"
        f"UUID: <code>{_clean(subscription.uuid)}</code>\n"
        f"Commands:\n"
        f"<code>/admin_subscription {subscription.id}</code>\n"
        f"<code>/admin_resend_config {_clean(subscription.order_id)}</code>\n"
    )


def _build_user_card_text(result) -> str:
    user = result.user
    orders = result.orders or []
    payments = result.payments or []
    subscriptions = result.subscriptions or []

    text_parts: list[str] = [
        "<b>Admin User Lookup</b>\n",
        _format_user_block(user),
        "<b>Summary</b>\n"
        f"Invalid payments count: {result.invalid_payments_count}\n",
    ]

    text_parts.append("<b>Last orders</b>\n")
    if orders:
        for order in orders:
            text_parts.append(_format_order_short(order))
    else:
        text_parts.append("Заказов нет\n")

    text_parts.append("<b>Last payments</b>\n")
    if payments:
        for payment in payments:
            text_parts.append(_format_payment_short(payment))
    else:
        text_parts.append("Платежей нет\n")

    text_parts.append("<b>Last subscriptions</b>\n")
    if subscriptions:
        for subscription in subscriptions:
            text_parts.append(_format_subscription_short(subscription))
    else:
        text_parts.append("Подписок нет\n")

    text_parts.append("<b>Commands</b>\n")
    text_parts.append(f"<code>/admin_user {user.id}</code>\n")
    text_parts.append(f"<code>/admin_user_tg {user.telegram_id}</code>\n")

    return "\n".join(text_parts)


@router.message(Command("admin_user"))
async def admin_user_command(
    message: Message,
    session: AsyncSession,
):
    if message.from_user is None:
        return

    if not _is_admin(message.from_user.id):
        await message.answer("Нет доступа.")
        return

    user_id = _parse_id_from_command(message)

    if user_id is None:
        await message.answer(
            "Использование:\n"
            "<code>/admin_user 46</code>",
            parse_mode="HTML",
        )
        return

    result = await AdminUserLookupService(session).get_user_card_by_user_id(
        user_id=user_id,
    )

    if not result.found:
        await message.answer(f"User #{user_id} не найден.")
        return

    await message.answer(
        _build_user_card_text(result),
        parse_mode="HTML",
    )


@router.message(Command("admin_user_tg"))
async def admin_user_tg_command(
    message: Message,
    session: AsyncSession,
):
    if message.from_user is None:
        return

    if not _is_admin(message.from_user.id):
        await message.answer("Нет доступа.")
        return

    telegram_id = _parse_id_from_command(message)

    if telegram_id is None:
        await message.answer(
            "Использование:\n"
            "<code>/admin_user_tg 611113612212</code>",
            parse_mode="HTML",
        )
        return

    result = await AdminUserLookupService(session).get_user_card_by_telegram_id(
        telegram_id=telegram_id,
    )

    if not result.found:
        await message.answer(f"User с Telegram ID {telegram_id} не найден.")
        return

    await message.answer(
        _build_user_card_text(result),
        parse_mode="HTML",
    )