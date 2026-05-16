import asyncio
import logging

from aiogram import Bot, Dispatcher

from app.bot.handlers.dev_subscription import router as dev_subscription_router
from app.bot.handlers.my_subscription import router as my_subscription_router
from app.bot.handlers.payment_check import router as payment_check_router
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

    dp.include_router(test_payment_check_router)
    dp.include_router(dev_subscription_router)
    dp.include_router(my_subscription_router)
    dp.include_router(payment_check_router)

    print("BOT ROUTERS LOADED:")
    print("- test_payment_check")
    print("- dev_subscription")
    print("- my_subscription")
    print("- payment_check")

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())