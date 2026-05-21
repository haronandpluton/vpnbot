from typing import Any

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import get_settings
from app.services.admin_subscription_actions_service import (
    AdminSubscriptionActionsService,
)

router = Router()


def _is_admin(telegram_id: int) -> bool:
    settings = get_settings()
    return telegram_id in settings.admin_ids


def _clean(value: Any) -> str:
    if value is None or value == "":
        return "—"

    return str(value)


def _format_datetime(value: Any) -> str:
    if value is None:
        return "—"

    return value.strftime("%d.%m.%Y %H:%M:%S")


def _parse_extend_args(message: Message) -> tuple[int, int] | None:
    if message.text is None:
        return None

    parts = message.text.strip().split()

    if len(parts) != 3:
        return None

    raw_subscription_id = parts[1].strip()
    raw_days = parts[2].strip()

    if not raw_subscription_id.isdigit():
        return None

    if not raw_days.isdigit():
        return None

    return int(raw_subscription_id), int(raw_days)


@router.message(Command("admin_extend_subscription"))
async def admin_extend_subscription_command(
    message: Message,
    session: AsyncSession,
):
    if message.from_user is None:
        return

    if not _is_admin(message.from_user.id):
        await message.answer("Нет доступа.")
        return

    args = _parse_extend_args(message)

    if args is None:
        await message.answer(
            "Использование:\n"
            "<code>/admin_extend_subscription 14 30</code>\n\n"
            "Где:\n"
            "14 — Subscription ID\n"
            "30 — количество дней продления",
            parse_mode="HTML",
        )
        return

    subscription_id, days = args

    result = await AdminSubscriptionActionsService(session).extend_subscription(
        subscription_id=subscription_id,
        days=days,
    )

    if result.status == "invalid_days":
        await message.answer(
            "Некорректное количество дней.\n"
            "Количество дней должно быть больше нуля."
        )
        return

    if result.status == "subscription_not_found":
        await message.answer(f"Subscription #{subscription_id} не найдена.")
        return

    if result.status != "extended":
        await message.answer(
            "Не удалось продлить подписку.\n\n"
            f"Status: {result.status}"
        )
        return

    await message.answer(
        "<b>Подписка продлена</b>\n\n"
        f"Subscription ID: {result.subscription_id}\n"
        f"User ID: {_clean(result.user_id)}\n"
        f"Order ID: {_clean(result.order_id)}\n"
        f"Days added: {result.days}\n"
        f"Old expires at: {_format_datetime(result.old_expires_at)}\n"
        f"New expires at: {_format_datetime(result.new_expires_at)}\n"
        f"UUID: <code>{_clean(result.uuid)}</code>\n\n"
        "Команды:\n"
        f"<code>/admin_subscription {result.subscription_id}</code>\n"
        f"<code>/admin_order {_clean(result.order_id)}</code>\n",
        parse_mode="HTML",
    )