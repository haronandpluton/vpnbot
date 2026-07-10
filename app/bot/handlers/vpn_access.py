from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
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
async def legacy_show_vpn_config_callback(callback: CallbackQuery):
    await callback.answer(
        "Open /my_subscription and select the subscription you need.",
        show_alert=True,
    )


@router.callback_query(F.data.startswith("vpn_access:show_config:"))
async def show_vpn_config_callback(
    callback: CallbackQuery,
    session: AsyncSession,
):
    if callback.from_user is None:
        await callback.answer("Could not identify the user.", show_alert=True)
        return

    try:
        subscription_id = int(callback.data.rsplit(":", maxsplit=1)[1])
    except (AttributeError, IndexError, ValueError):
        await callback.answer("Invalid subscription.", show_alert=True)
        return

    if subscription_id <= 0:
        await callback.answer("Invalid subscription.", show_alert=True)
        return

    result = await MySubscriptionService(
        session
    ).get_access_by_subscription_id(
        telegram_id=callback.from_user.id,
        subscription_id=subscription_id,
    )

    if result.status == "subscription_expired":
        await callback.answer("The selected subscription has expired.", show_alert=True)
        return

    if result.status == "subscription_not_active":
        await callback.answer("The selected subscription is not active.", show_alert=True)
        return

    if result.status != "active" or result.config_uri is None:
        await callback.answer("No active subscription found.", show_alert=True)
        return

    await callback.message.answer(
        format_vpn_config_text(result.config_uri),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="Open in Happ VPN",
                        url=result.config_uri,
                    )
                ]
            ]
        ),
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
