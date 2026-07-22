import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    Message,
    MessageEntity,
    User as TelegramUser,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.handlers.my_subscription import (
    send_my_subscriptions,
)
from app.bot.keyboards.main_menu import main_menu_keyboard
from app.bot.keyboards.vpn_access import vpn_access_keyboard
from app.bot.texts.vpn_access import format_vpn_access_text
from app.bot.utils.custom_emoji import build_custom_emoji_entities
from app.services.order_service import OrderService
from app.services.trial_activation_service import (
    TrialActivationService,
)


logger = logging.getLogger(__name__)
router = Router()

def main_menu_text() -> str:
    return (
        "🎁 Welcome to Present VPN! 🎁\n\n"
        "I am your personal bot and assistant 🤖\n\n"
        "I'll help you connect to VPN in seconds, securely access your "
        "favorite websites and apps, and keep your privacy protected\n\n"
        "🎁 Unique Present Days Program 🎁\n\n"
        "✨ Every subscription already includes a present. Purchase any "
        "plan and automatically receive extra VPN days. The longer your "
        "subscription, the more present days you get ✨"
    )


def main_menu_entities(
    text: str,
) -> list[MessageEntity]:
    return build_custom_emoji_entities(text)


async def _get_menu_trial_eligibility(
    *,
    session: AsyncSession,
    telegram_user: TelegramUser,
) -> bool:
    try:
        user = await OrderService(session).get_or_create_user(
            telegram_id=telegram_user.id,
            username=telegram_user.username,
            first_name=telegram_user.first_name,
            last_name=telegram_user.last_name,
            language_code=telegram_user.language_code,
        )

        trial_eligible = bool(user.trial_eligible)

        await session.commit()
        return trial_eligible

    except Exception:
        await session.rollback()
        raise

@router.message(Command("start"))
async def start_command(
    message: Message,
    session: AsyncSession,
):
    if message.from_user is None:
        await message.answer("Could not identify the user.")
        return

    trial_eligible = await _get_menu_trial_eligibility(
        session=session,
        telegram_user=message.from_user,
    )

    text = main_menu_text()

    await message.answer(
        text,
        entities=main_menu_entities(text),
        reply_markup=main_menu_keyboard(
            trial_eligible=trial_eligible,
        ),
    )


@router.callback_query(F.data == "back_to_main_menu")
async def back_to_main_menu_callback(
    callback: CallbackQuery,
    session: AsyncSession,
):
    if callback.from_user is None:
        await callback.answer(
            "Could not identify the user.",
            show_alert=True,
        )
        return

    trial_eligible = await _get_menu_trial_eligibility(
        session=session,
        telegram_user=callback.from_user,
    )

    text = main_menu_text()

    await callback.message.edit_text(
        text,
        entities=main_menu_entities(text),
        reply_markup=main_menu_keyboard(
            trial_eligible=trial_eligible,
        ),
    )
    await callback.answer()

@router.callback_query(F.data == "activate_trial")
async def activate_trial_callback(
    callback: CallbackQuery,
    session: AsyncSession,
):
    if callback.from_user is None:
        await callback.answer(
            "Could not identify the user.",
            show_alert=True,
        )
        return

    # Быстро закрываем Telegram spinner до обращения к 3X-UI.
    await callback.answer()

    try:
        result = await TrialActivationService(
            session
        ).activate_trial(
            telegram_id=callback.from_user.id,
        )
    except Exception:
        logger.exception(
            "Trial activation handler failed: "
            "telegram_id=%s",
            callback.from_user.id,
        )

        await callback.message.answer(
            "Could not activate your free VPN access "
            "right now.\n\n"
            "Please try again later or contact support."
        )
        return

    if result.status == "user_not_found":
        await callback.message.answer(
            "Your profile could not be found.\n\n"
            "Start the bot again with /start."
        )
        return

    if result.status == "not_eligible":
        await callback.message.edit_text(
            main_menu_text(),
            reply_markup=main_menu_keyboard(
                trial_eligible=False,
            ),
        )
        await callback.message.answer(
            "Your free 3-day VPN access has already "
            "been claimed."
        )
        return

    if (
        result.status != "activated"
        or result.subscription_id is None
        or result.expires_at is None
    ):
        logger.error(
            "Unexpected trial activation result: "
            "telegram_id=%s status=%s "
            "subscription_id=%s expires_at=%s",
            callback.from_user.id,
            result.status,
            result.subscription_id,
            result.expires_at,
        )

        await callback.message.answer(
            "The free VPN access could not be prepared.\n\n"
            "Please contact support."
        )
        return

    # Сразу заменяем GET 3 VPN DAYS на Buy VPN.
    await callback.message.edit_text(
        main_menu_text(),
        reply_markup=main_menu_keyboard(
            trial_eligible=False,
        ),
    )

    await callback.message.answer(
        "Your free 3-day VPN access has been claimed. Go to My Subscription\n\n"
        + format_vpn_access_text(
            device_limit=1,
            expires_at=result.expires_at,
        ),
        reply_markup=vpn_access_keyboard(
            subscription_id=result.subscription_id,
            renewable=False,
        ),
    )

@router.callback_query(F.data == "my_subscription")
async def my_subscription_callback(
    callback: CallbackQuery,
    session: AsyncSession,
):
    if callback.from_user is None:
        await callback.answer(
            "Could not identify the user.",
            show_alert=True,
        )
        return

    await send_my_subscriptions(
        message=callback.message,
        session=session,
        telegram_id=callback.from_user.id,
    )

    await callback.answer()