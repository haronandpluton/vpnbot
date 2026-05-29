from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.vpn_access import vpn_access_keyboard
from app.bot.texts.vpn_access import format_vpn_access_text
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
        await message.answer(
            format_vpn_access_text(
                device_limit=result.device_limit,
                expires_at=result.expires_at,
            ),
            reply_markup=vpn_access_keyboard(),
        )
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