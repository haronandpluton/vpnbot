from __future__ import annotations

from aiogram import Bot
from aiogram.types import BotCommand, BotCommandScopeDefault

USER_COMMANDS: list[BotCommand] = [
    BotCommand(command="start", description="🏠 Главное меню"),
    BotCommand(command="buy", description="🛒 Купить VPN"),
    BotCommand(command="my_subscription", description="📱 Моя подписка и устройства"),
    BotCommand(command="faq", description="📘 FAQ"),
    BotCommand(command="help", description="🆘 Поддержка"),
    BotCommand(command="profile", description="👤 Профиль"),
    BotCommand(command="present", description="🎁 Подарочная программа"),
]


async def setup_bot_commands(bot: Bot) -> None:
    await bot.set_my_commands(
        USER_COMMANDS,
        scope=BotCommandScopeDefault(),
    )