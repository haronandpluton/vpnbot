from decimal import Decimal

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import get_settings
from app.services.admin_stats_service import AdminStatsService

router = Router()


def _format_decimal(value: Decimal) -> str:
    normalized = value.quantize(Decimal("0.00000001"))
    text = f"{normalized:f}"
    text = text.rstrip("0").rstrip(".")

    if not text:
        return "0"

    return text


def _is_admin(telegram_id: int) -> bool:
    settings = get_settings()
    return telegram_id in settings.admin_ids


@router.message(Command("admin"))
@router.message(Command("admin_stats"))
async def admin_stats_command(
    message: Message,
    session: AsyncSession,
):
    if message.from_user is None:
        return

    if not _is_admin(message.from_user.id):
        await message.answer("Нет доступа.")
        return

    stats = await AdminStatsService(session).get_stats()

    text = (
        "<b>Админ-панель</b>\n\n"
        "<b>Пользователи</b>\n"
        f"Всего: {stats.users_total}\n\n"

        "<b>Заказы</b>\n"
        f"Всего: {stats.orders_total}\n"
        f"Ожидают оплату: {stats.orders_waiting_payment}\n"
        f"Оплачены: {stats.orders_paid}\n"
        f"Активированы: {stats.orders_activated}\n"
        f"Истекли: {stats.orders_expired}\n"
        f"Ошибочные: {stats.orders_failed}\n"
        f"Отменены: {stats.orders_cancelled}\n\n"

        "<b>Платежи</b>\n"
        f"Всего: {stats.payments_total}\n"
        f"Подтверждены: {stats.payments_confirmed}\n"
        f"Некорректные: {stats.payments_invalid}\n"
        f"Дубликаты: {stats.payments_duplicate}\n"
        f"Ошибки: {stats.payments_error}\n\n"

        "<b>Подписки</b>\n"
        f"Всего: {stats.subscriptions_total}\n"
        f"Активные: {stats.subscriptions_active}\n"
        f"Истекшие: {stats.subscriptions_expired}\n"
        f"Отключенные: {stats.subscriptions_disabled}\n\n"

        "<b>Выручка</b>\n"
        f"Confirmed payments: {_format_decimal(stats.confirmed_revenue_total)}"
    )

    await message.answer(text, parse_mode="HTML")