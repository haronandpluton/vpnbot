from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.vpn_access import vpn_access_keyboard
from app.bot.texts.vpn_access import format_vpn_access_text
from app.services.my_subscription_service import MySubscriptionService

router = Router()

async def send_my_subscriptions(
    message: Message,
    session: AsyncSession,
    telegram_id: int,
) -> None:
    result = (
        await MySubscriptionService(
            session
        ).get_active_subscriptions_by_telegram_id(
            telegram_id=telegram_id,
        )
    )

    if result.status == "active":
        for position, subscription in enumerate(result.subscriptions, start=1):
            await message.answer(
                (
                    f"Подписка №{position}\n"
                    f"ID подписки: {subscription.subscription_id}\n\n"
                    f"{format_vpn_access_text(
                        device_limit=subscription.device_limit,
                        expires_at=subscription.expires_at,
                    )}"
                ),
                reply_markup=vpn_access_keyboard(
                    subscription_id=subscription.subscription_id,
                ),
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
            "Активные подписки не найдены.\n\n"
            "Если ты уже оплатил заказ, нажми «Проверить оплату» "
            "в сообщении с заказом."
        )
        return

    if result.status == "subscription_expired":
        await message.answer(
            "Срок всех подписок истек.\n\n"
            "Создай новый заказ, чтобы получить новый доступ."
        )
        return

    await message.answer(
        "Не удалось определить состояние подписок.\n\n"
        "Обратись в поддержку."
    )

@router.message(Command("my_subscription"))
async def my_subscription_command(
    message: Message,
    session: AsyncSession,
):
    await send_my_subscriptions(
        message=message,
        session=session,
        telegram_id=message.from_user.id,
    )
