from typing import Any

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import get_settings
from app.services.admin_action_log_service import AdminActionLookupService

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


def _format_datetime(value: Any) -> str:
    if value is None:
        return "—"

    return value.strftime("%d.%m.%Y %H:%M:%S")


def _format_actions(title: str, items) -> str:
    if not items:
        return f"<b>{title}</b>\n\nЗаписей нет."

    parts: list[str] = [
        f"<b>{title}</b>\n"
        f"Найдено: {len(items)}\n\n"
    ]

    for item in items:
        admin_username = f"@{item.admin_username}" if item.admin_username else "—"

        parts.append(
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
            f"Created: {_format_datetime(item.created_at)}\n\n"
        )

    return "".join(parts)


@router.message(Command("admin_actions"))
async def admin_actions_command(
    message: Message,
    session: AsyncSession,
):
    if message.from_user is None:
        return

    if not _is_admin(message.from_user.id):
        await message.answer("Нет доступа.")
        return

    items = await AdminActionLookupService(session).get_last_actions(limit=20)

    await message.answer(
        _format_actions("Admin actions — последние 20", items),
        parse_mode="HTML",
    )


@router.message(Command("admin_actions_subscription"))
async def admin_actions_subscription_command(
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
            "<code>/admin_actions_subscription 14</code>",
            parse_mode="HTML",
        )
        return

    items = await AdminActionLookupService(session).get_actions_by_subscription_id(
        subscription_id=subscription_id,
        limit=20,
    )

    await message.answer(
        _format_actions(
            f"Admin actions по Subscription #{subscription_id}",
            items,
        ),
        parse_mode="HTML",
    )


@router.message(Command("admin_actions_user"))
async def admin_actions_user_command(
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
            "<code>/admin_actions_user 1</code>",
            parse_mode="HTML",
        )
        return

    items = await AdminActionLookupService(session).get_actions_by_target_user_id(
        target_user_id=user_id,
        limit=20,
    )

    await message.answer(
        _format_actions(
            f"Admin actions по User #{user_id}",
            items,
        ),
        parse_mode="HTML",
    )