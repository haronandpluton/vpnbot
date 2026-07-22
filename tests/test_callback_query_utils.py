from __future__ import annotations

import pytest

import app.bot.utils.callback_query as callback_query_module
from app.bot.utils.callback_query import edit_callback_message


class FakeTelegramBadRequest(Exception):
    pass


class FailingMessage:
    def __init__(self, error: Exception) -> None:
        self.error = error

    async def edit_text(self, text: str, **kwargs) -> None:
        raise self.error


@pytest.mark.asyncio
async def test_edit_callback_message_ignores_message_not_modified(monkeypatch):
    monkeypatch.setattr(
        callback_query_module,
        "TelegramBadRequest",
        FakeTelegramBadRequest,
    )
    message = FailingMessage(
        FakeTelegramBadRequest("message is not modified")
    )

    await edit_callback_message(message, "Same text")


@pytest.mark.asyncio
async def test_edit_callback_message_reraises_other_bad_request(monkeypatch):
    monkeypatch.setattr(
        callback_query_module,
        "TelegramBadRequest",
        FakeTelegramBadRequest,
    )
    message = FailingMessage(
        FakeTelegramBadRequest("message to edit not found")
    )

    with pytest.raises(
        FakeTelegramBadRequest,
        match="message to edit not found",
    ):
        await edit_callback_message(message, "New text")
