from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.my_subscription_service import MySubscriptionService

router = Router()


@router.message(Command("my_subscription"))
async def my_subscription_command(
    message: Message,
    session: AsyncSession,
):
    result = await MySubscriptionService(session).get_active_subscription_by_telegram_id(
        telegram_id=message.from_user.id,
    )

    if result.status == "active":
        expires_at_text = (
            result.expires_at.strftime("%d.%m.%Y %H:%M")
            if result.expires_at is not None
            else "не указано"
        )

        text = (
            "Твоя VPN-подписка активна.\n\n"
            f"Устройств: {result.device_limit}\n"
            f"Активна до: {expires_at_text}\n\n"
            "Конфиг для подключения:\n"
            f"<code>{result.config_uri}</code>"
        )

        await message.answer(text, parse_mode="HTML")
        return

    if result.status == "user_not_found":
        await message.answer(
            "Я пока не нашел твой профиль.\n\n"
            "Сначала создай заказ или запусти бота через /start."
        )
        return

    if result.status == "subscription_not_found":
        await message.answer(
            "Активная подписка не найдена.\n\n"
            "Если ты уже оплатил заказ, нажми «Проверить оплату» в сообщении с заказом."
        )
        return

    if result.status == "subscription_expired":
        await message.answer(
            "Срок подписки истек.\n\n"
            "Создай новый заказ, чтобы продлить доступ."
        )
        return

    if result.status == "subscription_not_active":
        await message.answer(
            "Подписка найдена, но сейчас она не активна.\n\n"
            "Если считаешь, что это ошибка — обратись в поддержку."
        )
        return

    await message.answer(
        "Не удалось определить состояние подписки.\n\n"
        "Обратись в поддержку."
    )