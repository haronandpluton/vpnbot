from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import get_settings
from app.services.admin_lookup_service import (
    AdminLookupService,
    clean,
    datetime_to_str,
    decimal_to_str,
    enum_to_str,
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
        f"Name: {clean(user.first_name)} {clean(user.last_name)}\n"
        f"Language: {clean(user.language_code)}\n"
        f"Admin: {user.is_admin}\n"
        f"Blocked: {user.is_blocked}\n"
        f"Created: {datetime_to_str(user.created_at)}\n"
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
        f"Status: {enum_to_str(order.status)}\n"
        f"User ID: {clean(order.user_id)}\n"
        f"Tariff: {enum_to_str(order.tariff_code)}\n"
        f"Device limit: {clean(order.device_limit)}\n"
        f"Price USD: {decimal_to_str(order.price_usd)}\n"
        f"Payment method: {enum_to_str(order.payment_method)}\n"
        f"Payment option ID: {clean(order.payment_option_id)}\n"
        f"Expected: {decimal_to_str(order.expected_amount)} "
        f"{enum_to_str(order.expected_currency)} / {enum_to_str(order.expected_network)}\n"
        f"Destination address: <code>{clean(order.destination_address)}</code>\n"
        f"Memo/tag: {clean(order.destination_memo_tag)}\n"
        f"Expires at: {datetime_to_str(order.expires_at)}\n"
        f"Paid at: {datetime_to_str(order.paid_at)}\n"
        f"Activated at: {datetime_to_str(order.activated_at)}\n"
        f"Source: {clean(order.source)}\n"
        f"Failure reason: {clean(order.failure_reason)}\n"
        f"Created: {datetime_to_str(order.created_at)}\n"
        f"Updated: {datetime_to_str(order.updated_at)}\n"
    )


def _format_payment_short(payment) -> str:
    return (
        f"Payment #{payment.id}\n"
        f"Status: {enum_to_str(payment.status)}\n"
        f"Amount: {decimal_to_str(payment.amount)} "
        f"{enum_to_str(payment.currency)} / {enum_to_str(payment.network)}\n"
        f"TXID: <code>{clean(payment.txid)}</code>\n"
        f"Provider payment ID: {clean(payment.provider_payment_id)}\n"
        f"Confirmations: {clean(payment.confirmations)}\n"
        f"Created: {datetime_to_str(payment.created_at)}\n"
    )


def _format_payment_full(payment) -> str:
    if payment is None:
        return (
            "<b>Payment</b>\n"
            "Не найден\n"
        )

    return (
        "<b>Payment</b>\n"
        f"ID: {payment.id}\n"
        f"Order ID: {clean(payment.order_id)}\n"
        f"User ID: {clean(payment.user_id)}\n"
        f"Status: {enum_to_str(payment.status)}\n"
        f"Payment method: {enum_to_str(payment.payment_method)}\n"
        f"Payment option ID: {clean(payment.payment_option_id)}\n"
        f"Amount: {decimal_to_str(payment.amount)} "
        f"{enum_to_str(payment.currency)} / {enum_to_str(payment.network)}\n"
        f"TXID: <code>{clean(payment.txid)}</code>\n"
        f"Provider payment ID: {clean(payment.provider_payment_id)}\n"
        f"Address from: <code>{clean(payment.address_from)}</code>\n"
        f"Address to: <code>{clean(payment.address_to)}</code>\n"
        f"Memo/tag: {clean(payment.memo_tag)}\n"
        f"Confirmations: {clean(payment.confirmations)}\n"
        f"Detected at: {datetime_to_str(payment.detected_at)}\n"
        f"Confirmed at: {datetime_to_str(payment.confirmed_at)}\n"
        f"Created: {datetime_to_str(payment.created_at)}\n"
        f"Updated: {datetime_to_str(payment.updated_at)}\n"
    )


def _format_event_short(event) -> str:
    return (
        f"Event #{event.id}\n"
        f"Payment ID: {clean(event.payment_id)}\n"
        f"Type: {clean(event.event_type)}\n"
        f"Status: {clean(event.processing_status)}\n"
        f"Error: {clean(event.error_message)}\n"
        f"External ID: <code>{clean(event.external_event_id)}</code>\n"
        f"TXID: <code>{clean(event.txid)}</code>\n"
        f"Processed: {event.processed}\n"
        f"Processed at: {datetime_to_str(event.processed_at)}\n"
        f"Created: {datetime_to_str(event.created_at)}\n"
    )


def _format_subscription_short(subscription) -> str:
    return (
        f"Subscription #{subscription.id}\n"
        f"Status: {enum_to_str(subscription.status)}\n"
        f"UUID: <code>{clean(subscription.uuid)}</code>\n"
        f"VPN server ID: {clean(subscription.vpn_server_id)}\n"
        f"Device limit: {clean(subscription.device_limit)}\n"
        f"Starts at: {datetime_to_str(subscription.starts_at)}\n"
        f"Expires at: {datetime_to_str(subscription.expires_at)}\n"
        f"Last access sent: {datetime_to_str(subscription.last_access_sent_at)}\n"
        f"Disabled at: {datetime_to_str(subscription.disabled_at)}\n"
        f"Config version: {clean(subscription.config_version)}\n"
        f"Error reason: {clean(subscription.error_reason)}\n"
        f"Created: {datetime_to_str(subscription.created_at)}\n"
    )


@router.message(Command("admin_order"))
async def admin_order_command(
    message: Message,
    session: AsyncSession,
):
    if message.from_user is None:
        return

    if not _is_admin(message.from_user.id):
        await message.answer("Нет доступа.")
        return

    order_id = _parse_id_from_command(message)

    if order_id is None:
        await message.answer(
            "Использование:\n"
            "<code>/admin_order 68</code>",
            parse_mode="HTML",
        )
        return

    result = await AdminLookupService(session).get_order_card(order_id)

    if not result.found:
        await message.answer(f"Order #{order_id} не найден.")
        return

    payments = result.payments or []
    events = result.events or []
    subscriptions = result.subscriptions or []

    text_parts = [
        "<b>Admin Order Lookup</b>\n",
        _format_order_block(result.order),
        _format_user_block(result.user),
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

    text_parts.append("<b>Subscriptions</b>\n")
    if subscriptions:
        for subscription in subscriptions[:5]:
            text_parts.append(_format_subscription_short(subscription))
    else:
        text_parts.append("Нет подписок\n")

    await message.answer(
        "\n".join(text_parts),
        parse_mode="HTML",
    )


@router.message(Command("admin_payment"))
async def admin_payment_command(
    message: Message,
    session: AsyncSession,
):
    if message.from_user is None:
        return

    if not _is_admin(message.from_user.id):
        await message.answer("Нет доступа.")
        return

    payment_id = _parse_id_from_command(message)

    if payment_id is None:
        await message.answer(
            "Использование:\n"
            "<code>/admin_payment 96</code>",
            parse_mode="HTML",
        )
        return

    result = await AdminLookupService(session).get_payment_card(payment_id)

    if not result.found:
        await message.answer(f"Payment #{payment_id} не найден.")
        return

    events = result.events or []
    subscriptions = result.subscriptions or []

    text_parts = [
        "<b>Admin Payment Lookup</b>\n",
        _format_payment_full(result.payment),
        _format_order_block(result.order),
        _format_user_block(result.user),
    ]

    text_parts.append("<b>Events</b>\n")
    if events:
        for event in events[:5]:
            text_parts.append(_format_event_short(event))
    else:
        text_parts.append("Нет событий\n")

    text_parts.append("<b>Subscriptions</b>\n")
    if subscriptions:
        for subscription in subscriptions[:5]:
            text_parts.append(_format_subscription_short(subscription))
    else:
        text_parts.append("Нет подписок\n")

    await message.answer(
        "\n".join(text_parts),
        parse_mode="HTML",
    )