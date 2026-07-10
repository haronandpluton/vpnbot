from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.vpn_access import (
    expired_subscription_keyboard,
    vpn_access_keyboard,
)
from app.bot.texts.vpn_access import (
    format_expired_vpn_subscription_text,
    format_vpn_access_text,
)
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
        for position, subscription in enumerate(
            result.subscriptions,
            start=1,
        ):
            subscription_status = getattr(
                subscription,
                "status",
                "active",
            )

            if subscription_status == "subscription_expired":
                text = (
                    f"Subscription #{position}\n"
                    f"Subscription ID: {subscription.subscription_id}\n\n"
                    f"{format_expired_vpn_subscription_text(
                        device_limit=subscription.device_limit,
                        expires_at=subscription.expires_at,
                    )}"
                )
                keyboard = expired_subscription_keyboard(
                    subscription_id=subscription.subscription_id,
                )
            else:
                text = (
                    f"Subscription #{position}\n"
                    f"Subscription ID: {subscription.subscription_id}\n\n"
                    f"{format_vpn_access_text(
                        device_limit=subscription.device_limit,
                        expires_at=subscription.expires_at,
                    )}"
                )
                keyboard = vpn_access_keyboard(
                    subscription_id=subscription.subscription_id,
                )

            await message.answer(
                text,
                reply_markup=keyboard,
            )
        return

    if result.status == "user_not_found":
        await message.answer(
            "I could not find your profile yet.\n\n"
            "Create an order first or start the bot with /start."
        )
        return

    if result.status == "subscription_not_found":
        await message.answer(
            "No active subscriptions found.\n\n"
            "If you have already paid, click “Check Payment” "
            "in the order message."
        )
        return

    if result.status == "subscription_expired":
        await message.answer(
            "All subscriptions have expired.\n\n"
            "Open a subscription and click “Renew Subscription”."
        )
        return

    await message.answer(
        "Could not determine the subscription status.\n\n"
        "Contact support."
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
