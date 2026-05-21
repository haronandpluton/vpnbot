from decimal import Decimal
from typing import Any

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import get_settings
from app.services.admin_subscription_lookup_service import (
    AdminSubscriptionLookupService,
)

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
    if user is None:
        return (
            "<b>User</b>\n"
            "Не найден\n"
        )

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
    )


def _format_subscription_block(subscription) -> str:
    if subscription is None:
        return (
            "<b>Subscription</b>\n"
            "Не найдена\n"
        )

    return (
        "<b>Subscription</b>\n"
        f"ID: {subscription.id}\n"
        f"Status: {_enum_to_str(subscription.status)}\n"
        f"User ID: {_clean(subscription.user_id)}\n"
        f"Order ID: {_clean(subscription.order_id)}\n"
        f"VPN server ID: {_clean(subscription.vpn_server_id)}\n"
        f"UUID: <code>{_clean(subscription.uuid)}</code>\n"
        f"Device limit: {_clean(subscription.device_limit)}\n"
        f"Starts at: {_format_datetime(subscription.starts_at)}\n"
        f"Expires at: {_format_datetime(subscription.expires_at)}\n"
        f"Last access sent at: {_format_datetime(subscription.last_access_sent_at)}\n"
        f"Disabled at: {_format_datetime(subscription.disabled_at)}\n"
        f"Config version: {_clean(subscription.config_version)}\n"
        f"Error reason: {_clean(subscription.error_reason)}\n"
        f"Created: {_format_datetime(subscription.created_at)}\n"
        f"Updated: {_format_datetime(subscription.updated_at)}\n"
    )


def _format_order_block(order) -> str:
    if order is None:
        return (
            "<b>Order</b>\n"
            "Не найден\n"
        )

    return (
        "<b>Order</b>\n"
        f"ID: {order.id}\n"
        f"Status: {_enum_to_str(order.status)}\n"
        f"Tariff: {_enum_to_str(order.tariff_code)}\n"
        f"Device limit: {_clean(order.device_limit)}\n"
        f"Price USD: {_format_decimal(order.price_usd)}\n"
        f"Payment method: {_enum_to_str(order.payment_method)}\n"
        f"Payment option ID: {_clean(order.payment_option_id)}\n"
        f"Expected: {_format_decimal(order.expected_amount)} "
        f"{_enum_to_str(order.expected_currency)} / {_enum_to_str(order.expected_network)}\n"
        f"Destination address: <code>{_clean(order.destination_address)}</code>\n"
        f"Expires at: {_format_datetime(order.expires_at)}\n"
        f"Paid at: {_format_datetime(order.paid_at)}\n"
        f"Activated at: {_format_datetime(order.activated_at)}\n"
        f"Failure reason: {_clean(order.failure_reason)}\n"
        f"Created: {_format_datetime(order.created_at)}\n"
    )


def _format_payment_short(payment) -> str:
    return (
        f"Payment #{payment.id}\n"
        f"Status: {_enum_to_str(payment.status)}\n"
        f"Amount: {_format_decimal(payment.amount)} "
        f"{_enum_to_str(payment.currency)} / {_enum_to_str(payment.network)}\n"
        f"TXID: <code>{_clean(payment.txid)}</code>\n"
        f"Confirmations: {_clean(payment.confirmations)}\n"
        f"Created: {_format_datetime(payment.created_at)}\n"
    )


def _format_event_short(event) -> str:
    return (
        f"Event #{event.id}\n"
        f"Payment ID: {_clean(event.payment_id)}\n"
        f"Type: {_clean(event.event_type)}\n"
        f"Status: {_clean(event.processing_status)}\n"
        f"Error: {_clean(event.error_message)}\n"
        f"TXID: <code>{_clean(event.txid)}</code>\n"
        f"Processed: {event.processed}\n"
        f"Processed at: {_format_datetime(event.processed_at)}\n"
        f"Created: {_format_datetime(event.created_at)}\n"
    )


@router.message(Command("admin_subscription"))
async def admin_subscription_command(
    message: Message,
    session: AsyncSession,
):
    if message.from_user is None:
        return

    if not _is_admin(message.from_user.id):
        await message.answer("Нет доступа.")
        return

    subscription_id = _parse_id_from_command(message)

    if subscription_id is None:
        await message.answer(
            "Использование:\n"
            "<code>/admin_subscription 14</code>",
            parse_mode="HTML",
        )
        return

    result = await AdminSubscriptionLookupService(session).get_subscription_card(
        subscription_id=subscription_id,
    )

    if not result.found:
        await message.answer(f"Subscription #{subscription_id} не найдена.")
        return

    subscription = result.subscription
    order = result.order
    user = result.user
    payments = result.payments or []
    events = result.events or []

    text_parts = [
        "<b>Admin Subscription Lookup</b>\n",
        _format_subscription_block(subscription),
        _format_user_block(user),
        _format_order_block(order),
    ]

    text_parts.append("<b>Payments</b>\n")
    if payments:
        for payment in payments[:5]:
            text_parts.append(_format_payment_short(payment))
    else:
        text_parts.append("Нет платежей\n")

    text_parts.append("<b>Events</b>\n")
    if events:
        for event in events[:5]:
            text_parts.append(_format_event_short(event))
    else:
        text_parts.append("Нет событий\n")

    text_parts.append("<b>Commands</b>\n")
    if order is not None:
        text_parts.append(f"<code>/admin_order {order.id}</code>\n")
        text_parts.append(f"<code>/admin_resend_config {order.id}</code>\n")

    if user is not None:
        text_parts.append(f"<code>/admin_user {user.id}</code> — позже\n")

    await message.answer(
        "\n".join(text_parts),
        parse_mode="HTML",
    )