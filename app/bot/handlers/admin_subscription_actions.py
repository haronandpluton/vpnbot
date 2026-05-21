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


def _parse_disable_args(message: Message) -> tuple[int, str] | None:
    if message.text is None:
        return None

    parts = message.text.strip().split(maxsplit=2)

    if len(parts) != 3:
        return None

    raw_subscription_id = parts[1].strip()
    reason = parts[2].strip()

    if not raw_subscription_id.isdigit():
        return None

    if not reason:
        return None

    return int(raw_subscription_id), reason


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
        admin_telegram_id=message.from_user.id,
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

    if result.status == "admin_user_not_found":
        await message.answer(
            "Не удалось записать admin action.\n"
            "Админ не найден в таблице users."
        )
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
        f"UUID: <code>{_clean(result.uuid)}</code>\n"
        f"Admin action ID: {_clean(result.admin_action_id)}\n\n"
        "Команды:\n"
        f"<code>/admin_subscription {result.subscription_id}</code>\n"
        f"<code>/admin_order {_clean(result.order_id)}</code>\n"
        f"<code>/admin_actions_subscription {result.subscription_id}</code>\n",
        parse_mode="HTML",
    )


@router.message(Command("admin_disable_subscription"))
async def admin_disable_subscription_command(
    message: Message,
    session: AsyncSession,
):
    if message.from_user is None:
        return

    if not _is_admin(message.from_user.id):
        await message.answer("Нет доступа.")
        return

    args = _parse_disable_args(message)

    if args is None:
        await message.answer(
            "Использование:\n"
            "<code>/admin_disable_subscription 14 abuse</code>\n\n"
            "Где:\n"
            "14 — Subscription ID\n"
            "abuse — причина отключения\n\n"
            "Примеры причин:\n"
            "<code>abuse</code>\n"
            "<code>manual_refund</code>\n"
            "<code>chargeback</code>\n"
            "<code>test_cleanup</code>",
            parse_mode="HTML",
        )
        return

    subscription_id, reason = args

    result = await AdminSubscriptionActionsService(session).disable_subscription(
        subscription_id=subscription_id,
        reason=reason,
        admin_telegram_id=message.from_user.id,
    )

    if result.status == "invalid_reason":
        await message.answer("Причина отключения обязательна.")
        return

    if result.status == "subscription_not_found":
        await message.answer(f"Subscription #{subscription_id} не найдена.")
        return

    if result.status == "admin_user_not_found":
        await message.answer(
            "Не удалось записать admin action.\n"
            "Админ не найден в таблице users."
        )
        return

    if result.status != "disabled":
        await message.answer(
            "Не удалось отключить подписку.\n\n"
            f"Status: {result.status}"
        )
        return

    await message.answer(
        "<b>Подписка отключена</b>\n\n"
        f"Subscription ID: {result.subscription_id}\n"
        f"User ID: {_clean(result.user_id)}\n"
        f"Order ID: {_clean(result.order_id)}\n"
        f"Old status: {_clean(result.old_status)}\n"
        f"New status: {_clean(result.new_status)}\n"
        f"Disabled at: {_format_datetime(result.disabled_at)}\n"
        f"Reason: {_clean(result.reason)}\n"
        f"UUID: <code>{_clean(result.uuid)}</code>\n"
        f"Admin action ID: {_clean(result.admin_action_id)}\n\n"
        "Команды:\n"
        f"<code>/admin_subscription {result.subscription_id}</code>\n"
        f"<code>/admin_order {_clean(result.order_id)}</code>\n"
        f"<code>/admin_actions_subscription {result.subscription_id}</code>\n",
        parse_mode="HTML",
    )