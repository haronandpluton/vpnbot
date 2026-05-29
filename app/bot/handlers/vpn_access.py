from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.texts.vpn_access import (
    format_vpn_config_text,
    happ_android_instruction_text,
    happ_fallback_text,
    happ_ios_instruction_text,
)
from app.services.my_subscription_service import MySubscriptionService

router = Router()


@router.callback_query(F.data == "vpn_access:show_config")
async def show_vpn_config_callback(
    callback: CallbackQuery,
    session: AsyncSession,
):
    if callback.from_user is None:
        await callback.answer("Не удалось определить пользователя.", show_alert=True)
        return

    result = await MySubscriptionService(session).get_active_subscription_by_telegram_id(
        telegram_id=callback.from_user.id,
    )

    if result.status != "active" or result.config_uri is None:
        await callback.answer("Активная подписка не найдена.", show_alert=True)
        return

    await callback.message.answer(
        format_vpn_config_text(result.config_uri),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "vpn_access:happ_android")
async def happ_android_callback(callback: CallbackQuery):
    await callback.message.answer(happ_android_instruction_text())
    await callback.answer()


@router.callback_query(F.data == "vpn_access:happ_ios")
async def happ_ios_callback(callback: CallbackQuery):
    await callback.message.answer(happ_ios_instruction_text())
    await callback.answer()


@router.callback_query(F.data == "vpn_access:happ_fallback")
async def happ_fallback_callback(callback: CallbackQuery):
    await callback.message.answer(happ_fallback_text())
    await callback.answer()