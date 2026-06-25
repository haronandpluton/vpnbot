from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.main_menu import main_menu_keyboard, tariff_keyboard
from app.bot.keyboards.vpn_access import vpn_access_keyboard
from app.bot.texts.vpn_access import format_vpn_access_text
from app.services.my_subscription_service import MySubscriptionService

router = Router()


def main_menu_text() -> str:
    return (
        "VPNFOR\n\n"
        "Быстрый VPN-доступ для стабильного подключения.\n\n"
        "Выбери действие:"
    )


@router.message(Command("start"))
async def start_command(message: Message):
    await message.answer(
        main_menu_text(),
        reply_markup=main_menu_keyboard(),
    )


@router.callback_query(F.data == "back_to_main_menu")
async def back_to_main_menu_callback(callback: CallbackQuery):
    await callback.message.edit_text(
        main_menu_text(),
        reply_markup=main_menu_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "my_subscription")
async def my_subscription_callback(
    callback: CallbackQuery,
    session: AsyncSession,
):
    if callback.from_user is None:
        await callback.answer("Не удалось определить пользователя.", show_alert=True)
        return

    result = await MySubscriptionService(session).get_active_subscription_by_telegram_id(
        telegram_id=callback.from_user.id,
    )

    if result.status == "active":
        await callback.message.answer(
            format_vpn_access_text(
                device_limit=result.device_limit,
                expires_at=result.expires_at,
            ),
            reply_markup=vpn_access_keyboard(),
        )
        await callback.answer()
        return

    if result.status == "subscription_not_found":
        await callback.message.answer(
            "Активная подписка не найдена.\n\n"
            "Ты можешь купить VPN-доступ через меню ниже.",
            reply_markup=tariff_keyboard(),
        )
        await callback.answer()
        return

    if result.status == "user_not_found":
        await callback.message.answer(
            "Профиль пока не найден.\n\n"
            "Создай заказ через меню покупки.",
            reply_markup=tariff_keyboard(),
        )
        await callback.answer()
        return

    if result.status == "subscription_expired":
        await callback.message.answer(
            "Срок подписки истек.\n\n"
            "Выбери тариф, чтобы продлить доступ.",
            reply_markup=tariff_keyboard(),
        )
        await callback.answer()
        return

    if result.status == "subscription_not_active":
        await callback.message.answer(
            "Подписка найдена, но сейчас она не активна.\n\n"
            "Если считаешь, что это ошибка — обратись в поддержку."
        )
        await callback.answer()
        return

    await callback.message.answer(
        "Не удалось определить состояние подписки.\n\n"
        "Обратись в поддержку."
    )
    await callback.answer()