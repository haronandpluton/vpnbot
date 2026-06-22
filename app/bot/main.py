import asyncio
import logging

from aiogram import Bot, Dispatcher

from app.bot.handlers.admin_subscription_meta_sync import (
    router as admin_subscription_meta_sync_router,
)

from app.bot.handlers.admin import router as admin_router
from app.bot.handlers.admin_actions_lookup import router as admin_actions_lookup_router
from app.bot.handlers.admin_active_subscriptions import (
    router as admin_active_subscriptions_router,
)
from app.bot.handlers.admin_commands_help import router as admin_commands_help_router
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
from app.bot.handlers.admin_order_expiration import router as admin_order_expiration_router
from app.bot.handlers.buy import router as buy_router
from app.bot.handlers.dev_payment import router as dev_payment_router
from app.bot.handlers.dev_subscription import router as dev_subscription_router
from app.bot.handlers.info import router as info_router
from app.bot.handlers.my_subscription import router as my_subscription_router
from app.bot.handlers.payment_check import router as payment_check_router
from app.bot.handlers.start import router as start_router
from app.bot.handlers.test_payment_check import router as test_payment_check_router
from app.bot.middlewares.db_session import DbSessionMiddleware
from app.bot.middlewares.dev_commands_guard import DevCommandsGuardMiddleware
from app.config.settings import get_settings
from app.database.session import SessionLocal
from app.services.subscription_expiration_scheduler import SubscriptionExpirationScheduler
from app.services.order_expiration_scheduler import OrderExpirationScheduler


from app.bot.handlers.vpn_access import router as vpn_access_router
from app.bot.handlers.admin_subscription_expiration import router as admin_subscription_expiration_router

logger = logging.getLogger(__name__)


async def main() -> None:
    settings = get_settings()

    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    bot = Bot(token=settings.bot_token)
    dp = Dispatcher()

    dp.update.middleware(DbSessionMiddleware(SessionLocal))

    # Production safety layer:
    # Dev/test commands are blocked unless:
    # 1) sender is admin;
    # 2) DEV_MODE=true.
    dp.message.middleware(DevCommandsGuardMiddleware())

    dp.include_router(start_router)
    dp.include_router(buy_router)
    dp.include_router(info_router)

    dp.include_router(my_subscription_router)
    dp.include_router(vpn_access_router)
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
    dp.include_router(admin_subscription_meta_sync_router)
    dp.include_router(admin_commands_help_router)
    dp.include_router(admin_subscription_expiration_router)
    dp.include_router(admin_order_expiration_router)

    logger.info("Базовые роутеры загружены")
    logger.info("Защита dev-команд включена")

    if settings.dev_mode:
        # Dev/test routers are available only in local development mode.
        # In production DEV_MODE must be false, so these handlers are not loaded.
        dp.include_router(test_payment_check_router)
        dp.include_router(dev_payment_router)
        dp.include_router(dev_subscription_router)

        logger.warning("DEV_MODE=true: dev/test-роутеры загружены")
    else:
        logger.info("DEV_MODE=false: dev/test-роутеры не загружены")

    expiration_scheduler = SubscriptionExpirationScheduler(SessionLocal)
    expiration_scheduler_task = asyncio.create_task(
        expiration_scheduler.run_forever(),
        name="subscription-expiration-scheduler",
    )

    order_expiration_scheduler = OrderExpirationScheduler(SessionLocal)
    order_expiration_scheduler_task = asyncio.create_task(
        order_expiration_scheduler.run_forever(),
        name="order-expiration-scheduler",
    )

    try:
        await dp.start_polling(bot)

    finally:
        expiration_scheduler_task.cancel()
        order_expiration_scheduler_task.cancel()
        await asyncio.gather(
            expiration_scheduler_task,
            order_expiration_scheduler_task,
            return_exceptions=True,
        )


if __name__ == "__main__":
    asyncio.run(main())