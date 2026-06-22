from __future__ import annotations

from typing import Any

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import get_settings
from app.services.order_expiration_service import OrderExpirationService

router = Router()


def _is_admin(telegram_id: int) -> bool:
    settings = get_settings()
    return telegram_id in settings.admin_ids


def _format_datetime(value: Any) -> str:
    if value is None:
        return "—"

    return value.strftime("%d.%m.%Y %H:%M:%S")


@router.message(Command("admin_expire_orders"))
async def admin_expire_orders_command(
    message: Message,
    session: AsyncSession,
):
    if message.from_user is None:
        return

    if not _is_admin(message.from_user.id):
        await message.answer("Нет доступа.")
        return

    result = await OrderExpirationService(session).expire_due_orders()

    if result.status == "no_expired_orders":
        await message.answer(
            "<b>Просроченных неоплаченных заказов нет</b>\n\n"
            f"Checked at: {_format_datetime(result.checked_at)}",
            parse_mode="HTML",
        )
        return

    if result.status != "expired":
        await message.answer(
            "<b>Не удалось обработать истечение заказов</b>\n\n"
            f"Status: {result.status}\n"
            f"Message: {result.message or '—'}",
            parse_mode="HTML",
        )
        return

    lines = [
        "<b>Истечение неоплаченных заказов обработано</b>",
        "",
        f"Checked at: {_format_datetime(result.checked_at)}",
        f"Expired count: {result.expired_count}",
    ]

    if result.expired_items:
        lines.append("")
        lines.append("<b>Expired orders</b>")

        for item in result.expired_items[:20]:
            lines.append(
                f"#{item.order_id} | user_id={item.user_id} | "
                f"{item.old_status} → {item.new_status} | "
                f"expires={_format_datetime(item.expires_at)} | "
                f"tariff={item.tariff_code} | "
                f"payment={item.payment_method}"
            )

        if len(result.expired_items) > 20:
            lines.append(f"...и ещё {len(result.expired_items) - 20}")

    await message.answer(
        "\n".join(lines),
        parse_mode="HTML",
    )