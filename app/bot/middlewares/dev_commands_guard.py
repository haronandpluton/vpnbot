from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from app.bot.utils.access import is_admin, is_dev_mode_enabled


DEV_COMMANDS = {
    "/dev_create_active_subscription",
    "/dev_payment",
    "/dev_confirm_payment",
    "/dev_create_payment",
    "/test_payment_check",
}


class DevCommandsGuardMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, Message):
            return await handler(event, data)

        if event.text is None:
            return await handler(event, data)

        command = event.text.strip().split(maxsplit=1)[0]

        if command not in DEV_COMMANDS:
            return await handler(event, data)

        if event.from_user is None:
            return None

        telegram_id = event.from_user.id

        if not is_admin(telegram_id):
            await event.answer("Нет доступа.")
            return None

        if not is_dev_mode_enabled():
            await event.answer(
                "Dev-команды отключены.\n\n"
                "Для локальной разработки установи в .env:\n"
                "<code>DEV_MODE=true</code>",
                parse_mode="HTML",
            )
            return None

        return await handler(event, data)