from typing import Any

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import get_settings
from app.services.subscription_expiration_service import SubscriptionExpirationService

router = Router()


def _is_admin(telegram_id: int) -> bool:
    settings = get_settings()
    return telegram_id in settings.admin_ids


def _format_datetime(value: Any) -> str:
    if value is None:
        return "—"

    return value.strftime("%d.%m.%Y %H:%M:%S")


@router.message(Command("admin_expire_subscriptions"))
async def admin_expire_subscriptions_command(
    message: Message,
    session: AsyncSession,
):
    if message.from_user is None:
        return

    if not _is_admin(message.from_user.id):
        await message.answer("Нет доступа.")
        return

    result = await SubscriptionExpirationService(session).expire_due_subscriptions(
        sync_metadata=True,
    )

    if result.status == "no_expired_subscriptions":
        await message.answer(
            "<b>Просроченных active-подписок нет</b>\n\n"
            f"Checked at: {_format_datetime(result.checked_at)}",
            parse_mode="HTML",
        )
        return

    if result.status != "expired":
        await message.answer(
            "<b>Не удалось обработать истечение подписок</b>\n\n"
            f"Status: {result.status}\n"
            f"Message: {result.message or '—'}",
            parse_mode="HTML",
        )
        return

    lines = [
        "<b>Истечение подписок обработано</b>",
        "",
        f"Checked at: {_format_datetime(result.checked_at)}",
        f"Expired count: {result.expired_count}",
        f"Sync status: {result.sync_status or '—'}",
    ]

    if result.sync_error:
        lines.append(f"Sync error: <code>{result.sync_error}</code>")

    if result.expired_items:
        lines.append("")
        lines.append("<b>Expired subscriptions</b>")

        for item in result.expired_items[:20]:
            lines.append(
                f"#{item.subscription_id} | user_id={item.user_id} | "
                f"{item.old_status} → {item.new_status} | "
                f"expires={_format_datetime(item.expires_at)} | "
                f"uuid=<code>{item.uuid}</code>"
            )

        if len(result.expired_items) > 20:
            lines.append(f"...и ещё {len(result.expired_items) - 20}")

    await message.answer(
        "\n".join(lines),
        parse_mode="HTML",
    )
