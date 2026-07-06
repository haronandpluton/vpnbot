from html import escape
from typing import Any

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import get_settings
from app.services.admin_action_log_service import AdminActionLookupService

router = Router()

TELEGRAM_SAFE_MESSAGE_LIMIT = 3500
MAX_ADMIN_ACTION_PAYLOAD_LENGTH = 700
MAX_ADMIN_ACTION_REASON_LENGTH = 500


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


def _clean(value: Any, *, max_length: int | None = None) -> str:
    if value is None or value == "":
        return "—"

    text = str(value)

    if max_length is not None and len(text) > max_length:
        text = f"{text[:max_length]}…"

    return escape(text, quote=False)


def _format_datetime(value: Any) -> str:
    if value is None:
        return "—"

    return value.strftime("%d.%m.%Y %H:%M:%S")

def _split_text(text: str, *, limit: int = TELEGRAM_SAFE_MESSAGE_LIMIT) -> list[str]:
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    current = ""

    for block in text.split("\n\n"):
        candidate = f"{current}\n\n{block}" if current else block

        if len(candidate) <= limit:
            current = candidate
            continue

        if current:
            chunks.append(current)

        if len(block) <= limit:
            current = block
            continue

        chunks.extend(
            block[index : index + limit]
            for index in range(0, len(block), limit)
        )
        current = ""

    if current:
        chunks.append(current)

    return chunks


async def _answer_long_html(message: Message, text: str) -> None:
    for chunk in _split_text(text):
        await message.answer(chunk, parse_mode="HTML")


def _format_actions(title: str, items) -> str:
    if not items:
        return f"<b>{title}</b>\n\nЗаписей нет."

    parts: list[str] = [
        f"<b>{title}</b>\n"
        f"Найдено: {len(items)}\n\n"
    ]

    for item in items:
        admin_username = f"@{_clean(item.admin_username)}" if item.admin_username else "—"

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
            f"Reason: {_clean(item.reason, max_length=MAX_ADMIN_ACTION_REASON_LENGTH)}\n"
            f"Payload: <code>{_clean(item.payload, max_length=MAX_ADMIN_ACTION_PAYLOAD_LENGTH)}</code>\n"
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

    await _answer_long_html(
        message,
        _format_actions("Admin actions — последние 20", items),
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

    await _answer_long_html(
        message,
        _format_actions(
            f"Admin actions по Subscription #{subscription_id}",
            items,
        ),
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

    await _answer_long_html(
        message,
        _format_actions(
            f"Admin actions по User #{user_id}",
            items,
        ),
    )