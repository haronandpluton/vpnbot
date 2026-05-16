from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.main_menu import main_menu_keyboard
from app.services.my_subscription_service import MySubscriptionService

router = Router()


@router.message(Command("start"))
async def start_command(message: Message):
    text = (
        "VPNFOR\n\n"
        "Выбери действие:"
    )

    await message.answer(
        text,
        reply_markup=main_menu_keyboard(),
    )


@router.callback_query(F.data == "back_to_main_menu")
async def back_to_main_menu_callback(callback: CallbackQuery):
    text = (
        "VPNFOR\n\n"
        "Выбери действие:"
    )

    await callback.message.edit_text(
        text,
        reply_markup=main_menu_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "my_subscription")
async def my_subscription_callback(
    callback: CallbackQuery,
    session: AsyncSession,
):
    result = await MySubscriptionService(session).get_active_subscription_by_telegram_id(
        telegram_id=callback.from_user.id,
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

        await callback.message.answer(text, parse_mode="HTML")
        await callback.answer()
        return

    if result.status == "subscription_not_found":
        await callback.message.answer(
            "Активная подписка не найдена.\n\n"
            "Если ты уже оплатил заказ, нажми «Проверить оплату» в сообщении с заказом."
        )
        await callback.answer()
        return

    if result.status == "user_not_found":
        await callback.message.answer(
            "Профиль пока не найден.\n\n"
            "Создай заказ через меню покупки."
        )
        await callback.answer()
        return

    if result.status == "subscription_expired":
        await callback.message.answer(
            "Срок подписки истек.\n\n"
            "Создай новый заказ, чтобы продлить доступ."
        )
        await callback.answer()
        return

    await callback.message.answer(
        "Не удалось определить состояние подписки.\n\n"
        "Обратись в поддержку."
    )
    await callback.answer()