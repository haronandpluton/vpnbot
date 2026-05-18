from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import get_settings
from app.services.admin_active_subscriptions_service import (
    AdminActiveSubscriptionsService,
)

router = Router()

TELEGRAM_MESSAGE_LIMIT = 3900


def _is_admin(telegram_id: int) -> bool:
    settings = get_settings()
    return telegram_id in settings.admin_ids


def _clean(value) -> str:
    if value is None or value == "":
        return "—"

    return str(value)


def _format_datetime(value) -> str:
    if value is None:
        return "—"

    return value.strftime("%d.%m.%Y %H:%M")


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


@router.message(Command("admin_active_subscriptions"))
async def admin_active_subscriptions_command(
    message: Message,
    session: AsyncSession,
):
    if message.from_user is None:
        return

    if not _is_admin(message.from_user.id):
        await message.answer("Нет доступа.")
        return

    items = await AdminActiveSubscriptionsService(session).get_active_subscriptions(
        limit=50,
    )

    if not items:
        await message.answer("Активных подписок пока нет.")
        return

    blocks: list[str] = [
        "<b>Активные подписки</b>\n"
        "Ближайшие к окончанию первые.\n"
        f"Найдено: {len(items)}\n\n"
    ]

    for item in items:
        username_text = f"@{item.username}" if item.username else "—"

        block = (
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
            f"Команды:\n"
            f"<code>/admin_order {_clean(item.order_id)}</code>\n"
            f"<code>/admin_resend_config {_clean(item.order_id)}</code>\n"
            "\n"
        )

        blocks.append(block)

    messages = _split_messages(blocks)

    for text in messages:
        await message.answer(
            text,
            parse_mode="HTML",
        )