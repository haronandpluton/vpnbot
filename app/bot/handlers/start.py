from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.handlers.my_subscription import send_my_subscriptions
from app.bot.keyboards.main_menu import main_menu_keyboard

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
        await callback.answer(
            "Не удалось определить пользователя.",
            show_alert=True,
        )
        return

    await send_my_subscriptions(
        message=callback.message,
        session=session,
        telegram_id=callback.from_user.id,
    )

    await callback.answer()