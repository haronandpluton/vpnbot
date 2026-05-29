from aiogram import Bot, Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import get_settings
from app.services.admin_action_log_service import AdminActionLogService
from app.services.admin_recovery_service import AdminRecoveryService

from app.bot.keyboards.vpn_access import vpn_access_keyboard
from app.bot.texts.vpn_access import format_vpn_access_text

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


def _format_datetime(value) -> str:
    if value is None:
        return "—"

    return value.strftime("%d.%m.%Y %H:%M")


@router.message(Command("admin_resend_config"))
async def admin_resend_config_command(
    message: Message,
    session: AsyncSession,
    bot: Bot,
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
            "<code>/admin_resend_config 62</code>",
            parse_mode="HTML",
        )
        return

    result = await AdminRecoveryService(session).prepare_resend_config(order_id)

    if result.status == "order_not_found":
        await message.answer(f"Order #{order_id} не найден.")
        return

    if result.status == "user_not_found":
        await message.answer(
            f"Order #{result.order_id} найден, но пользователь не найден."
        )
        return

    if result.status == "subscription_not_found":
        await message.answer(
            "Нельзя отправить конфиг.\n\n"
            f"Order ID: {result.order_id}\n"
            "Подписка по этому заказу не найдена."
        )
        return

    if result.status == "subscription_not_active":
        await message.answer(
            "Нельзя отправить конфиг.\n\n"
            f"Order ID: {result.order_id}\n"
            f"Subscription ID: {result.subscription_id}\n"
            f"Status: {result.subscription_status}"
        )
        return

    if result.status == "subscription_expired":
        await message.answer(
            "Нельзя отправить конфиг.\n\n"
            f"Order ID: {result.order_id}\n"
            f"Subscription ID: {result.subscription_id}\n"
            f"Истекла: {_format_datetime(result.expires_at)}"
        )
        return

    if result.status != "ready" or result.config_uri is None or result.telegram_id is None:
        await message.answer(
            "Не удалось подготовить конфиг для отправки.\n\n"
            f"Order ID: {result.order_id}\n"
            f"Status: {result.status}"
        )
        return

    user_text = (
            "Твой VPN-доступ повторно отправлен администратором.\n\n"
            + format_vpn_access_text(
        device_limit=None,
        expires_at=result.expires_at,
        )
    )

    try:
        await bot.send_message(
            chat_id=result.telegram_id,
            text=user_text,
            parse_mode="HTML",
            reply_markup=vpn_access_keyboard(),
        )
    except Exception as exc:
        await message.answer(
            "Конфиг подготовлен, но не удалось отправить пользователю в Telegram.\n\n"
            f"Order ID: {result.order_id}\n"
            f"Telegram ID: {result.telegram_id}\n"
            f"Ошибка: <code>{type(exc).__name__}: {exc}</code>",
            parse_mode="HTML",
        )
        return

    action_result = await AdminActionLogService(
        session,
    ).create_action_by_admin_telegram_id(
        admin_telegram_id=message.from_user.id,
        action_type="admin_resend_config",
        target_user_id=result.user_id,
        order_id=result.order_id,
        subscription_id=result.subscription_id,
        reason="manual_resend_config",
        payload=(
            f"telegram_id={result.telegram_id}; "
            f"expires_at={result.expires_at}"
        ),
        commit=True,
    )

    username_text = f"@{result.username}" if result.username else "—"

    admin_text = (
        "Конфиг повторно отправлен пользователю.\n\n"
        f"Order ID: {result.order_id}\n"
        f"User ID: {result.user_id}\n"
        f"Telegram ID: {result.telegram_id}\n"
        f"Username: {username_text}\n"
        f"Subscription ID: {result.subscription_id}\n"
        f"Активна до: {_format_datetime(result.expires_at)}\n"
        f"Admin action ID: {action_result.action_id if action_result.status == 'created' else '—'}"
    )

    await message.answer(admin_text)