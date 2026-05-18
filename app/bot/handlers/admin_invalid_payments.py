from decimal import Decimal

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import get_settings
from app.services.admin_invalid_payments_service import AdminInvalidPaymentsService

router = Router()


def _is_admin(telegram_id: int) -> bool:
    settings = get_settings()
    return telegram_id in settings.admin_ids


def _format_decimal(value: Decimal | None) -> str:
    if value is None:
        return "—"

    normalized = value.quantize(Decimal("0.00000001"))
    text = f"{normalized:f}"
    text = text.rstrip("0").rstrip(".")

    return text or "0"


def _format_datetime(value) -> str:
    if value is None:
        return "—"

    return value.strftime("%d.%m.%Y %H:%M")


def _clean(value) -> str:
    if value is None or value == "":
        return "—"

    return str(value)


@router.message(Command("admin_invalid_payments"))
async def admin_invalid_payments_command(
    message: Message,
    session: AsyncSession,
):
    if message.from_user is None:
        return

    if not _is_admin(message.from_user.id):
        await message.answer("Нет доступа.")
        return

    items = await AdminInvalidPaymentsService(session).get_last_invalid_payments(
        limit=10,
    )

    if not items:
        await message.answer(
            "Некорректных платежей пока нет."
        )
        return

    chunks: list[str] = [
        "<b>Некорректные платежи</b>\n"
        "Последние 10 записей:\n"
    ]

    for item in items:
        username_text = (
            f"@{item.username}"
            if item.username
            else "—"
        )

        chunks.append(
            "\n"
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
        )

    text = "\n".join(chunks)

    await message.answer(
        text,
        parse_mode="HTML",
    )