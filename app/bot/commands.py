from __future__ import annotations

from aiogram import Bot
from aiogram.types import BotCommand, BotCommandScopeDefault

USER_COMMANDS: list[BotCommand] = [
    BotCommand(command="start", description="🏠 Main Menu"),
    BotCommand(command="buy", description="🛒 Buy VPN"),
    BotCommand(command="my_subscription", description="📱 My Subscription and Devices"),
    BotCommand(command="faq", description="📘 FAQ"),
    BotCommand(command="help", description="🆘 Support"),
    BotCommand(
        command="paysupport",
        description="⭐ Stars Payment Support",
    ),
    BotCommand(command="rules", description="📄 Service Rules"),
    BotCommand(command="profile", description="👤 Profile"),
    BotCommand(command="present", description="🎁 Present Program"),
]


async def setup_bot_commands(bot: Bot) -> None:
    await bot.set_my_commands(
        USER_COMMANDS,
        scope=BotCommandScopeDefault(),
    )