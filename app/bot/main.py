import asyncio
import logging

from aiogram import Bot, Dispatcher

from app.bot.handlers.admin import router as admin_router
from app.bot.handlers.admin_actions_lookup import router as admin_actions_lookup_router
from app.bot.handlers.admin_active_subscriptions import (
    router as admin_active_subscriptions_router,
)
from app.bot.handlers.admin_invalid_payments import router as admin_invalid_payments_router
from app.bot.handlers.admin_lookup import router as admin_lookup_router
from app.bot.handlers.admin_recovery import router as admin_recovery_router
from app.bot.handlers.admin_subscription_actions import (
    router as admin_subscription_actions_router,
)
from app.bot.handlers.admin_subscription_lookup import (
    router as admin_subscription_lookup_router,
)
from app.bot.handlers.admin_user_lookup import router as admin_user_lookup_router
from app.bot.handlers.buy import router as buy_router
from app.bot.handlers.dev_payment import router as dev_payment_router
from app.bot.handlers.dev_subscription import router as dev_subscription_router
from app.bot.handlers.info import router as info_router
from app.bot.handlers.my_subscription import router as my_subscription_router
from app.bot.handlers.payment_check import router as payment_check_router
from app.bot.handlers.start import router as start_router
from app.bot.handlers.test_payment_check import router as test_payment_check_router
from app.bot.middlewares.db_session import DbSessionMiddleware
from app.config.settings import get_settings
from app.database.session import SessionLocal


async def main() -> None:
    settings = get_settings()

    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    bot = Bot(token=settings.bot_token)
    dp = Dispatcher()

    dp.update.middleware(DbSessionMiddleware(SessionLocal))

    dp.include_router(start_router)
    dp.include_router(buy_router)
    dp.include_router(info_router)

    # Dev/test routers. Later these should be protected by admin access or removed.
    dp.include_router(test_payment_check_router)
    dp.include_router(dev_payment_router)
    dp.include_router(dev_subscription_router)

    dp.include_router(my_subscription_router)
    dp.include_router(payment_check_router)

    dp.include_router(admin_router)
    dp.include_router(admin_invalid_payments_router)
    dp.include_router(admin_lookup_router)
    dp.include_router(admin_recovery_router)
    dp.include_router(admin_active_subscriptions_router)
    dp.include_router(admin_subscription_lookup_router)
    dp.include_router(admin_user_lookup_router)
    dp.include_router(admin_subscription_actions_router)
    dp.include_router(admin_actions_lookup_router)

    print("BOT ROUTERS LOADED:")
    print("- start")
    print("- buy")
    print("- info")
    print("- test_payment_check")
    print("- dev_payment")
    print("- dev_subscription")
    print("- my_subscription")
    print("- payment_check")
    print("- admin")
    print("- admin_invalid_payments")
    print("- admin_lookup")
    print("- admin_recovery")
    print("- admin_active_subscriptions")
    print("- admin_subscription_lookup")
    print("- admin_user_lookup")
    print("- admin_subscription_actions")
    print("- admin_actions_lookup")

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())