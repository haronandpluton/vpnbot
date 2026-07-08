from __future__ import annotations

import pytest
from aiogram.types import BotCommandScopeDefault

from app.bot.commands import USER_COMMANDS, setup_bot_commands


class FakeBot:
    def __init__(self):
        self.commands = None
        self.scope = None

    async def set_my_commands(self, commands, scope=None):
        self.commands = commands
        self.scope = scope


def test_user_command_menu_contains_expected_public_commands():
    assert [(item.command, item.description) for item in USER_COMMANDS] == [
        ("start", "🏠 Главное меню"),
        ("buy", "🛒 Купить VPN"),
        ("my_subscription", "📱 Моя подписка и устройства"),
        ("faq", "📘 FAQ"),
        ("help", "🆘 Поддержка"),
        ("rules", "📄 Правила сервиса"),
        ("profile", "👤 Профиль"),
        ("present", "🎁 Подарочная программа"),
    ]


def test_user_command_menu_does_not_expose_admin_or_dev_commands():
    commands = {item.command for item in USER_COMMANDS}

    assert not any(command.startswith("admin") for command in commands)
    assert not any(command.startswith("dev") for command in commands)
    assert "test_payment_check" not in commands


@pytest.mark.asyncio
async def test_setup_bot_commands_sets_default_user_menu():
    bot = FakeBot()

    await setup_bot_commands(bot)

    assert bot.commands == USER_COMMANDS
    assert isinstance(bot.scope, BotCommandScopeDefault)