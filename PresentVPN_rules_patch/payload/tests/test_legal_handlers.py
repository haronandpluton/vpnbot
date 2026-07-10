from __future__ import annotations

import pytest

from app.bot.handlers.legal import (
    LEGAL_CHUNK_LIMIT,
    RULES_MENU_TEXT,
    load_legal_text,
    privacy_callback,
    refund_callback,
    rules_callback,
    rules_command,
    rules_keyboard,
    split_telegram_text,
    tariffs_callback,
    terms_callback,
)


class FakeMessage:
    def __init__(self) -> None:
        self.answer_calls: list[dict] = []
        self.edit_text_calls: list[dict] = []

    async def answer(self, text: str, **kwargs) -> None:
        self.answer_calls.append({"text": text, **kwargs})

    async def edit_text(self, text: str, **kwargs) -> None:
        self.edit_text_calls.append({"text": text, **kwargs})


class FakeCallback:
    def __init__(self) -> None:
        self.message = FakeMessage()
        self.answer_calls: list[dict] = []

    async def answer(self, text: str | None = None, **kwargs) -> None:
        self.answer_calls.append({"text": text, **kwargs})


def row_callbacks(markup):
    return [
        [button.callback_data for button in row]
        for row in markup.inline_keyboard
    ]


def test_rules_keyboard_contains_all_sections_and_back_to_menu():
    assert row_callbacks(rules_keyboard()) == [
        ["rules:terms"],
        ["rules:refund"],
        ["rules:privacy"],
        ["rules:tariffs"],
        ["back_to_main_menu"],
    ]


def test_split_telegram_text_keeps_every_chunk_within_limit():
    text = "\n\n".join(f"Раздел {index}: " + "слово " * 300 for index in range(8))

    chunks = split_telegram_text(text)

    assert len(chunks) > 1
    assert all(0 < len(chunk) <= LEGAL_CHUNK_LIMIT for chunk in chunks)


def test_legal_documents_exist_and_are_not_empty():
    assert "Пользовательское соглашение" in load_legal_text("terms.txt")
    assert "Политика конфиденциальности" in load_legal_text("privacy.txt")
    assert "Условия возврата" in load_legal_text("refund_policy.txt")


@pytest.mark.asyncio
async def test_rules_command_sends_rules_menu():
    message = FakeMessage()

    await rules_command(message)

    assert message.answer_calls[0]["text"] == RULES_MENU_TEXT
    assert row_callbacks(message.answer_calls[0]["reply_markup"]) == [
        ["rules:terms"],
        ["rules:refund"],
        ["rules:privacy"],
        ["rules:tariffs"],
        ["back_to_main_menu"],
    ]


@pytest.mark.asyncio
async def test_rules_callback_edits_message_to_rules_menu():
    callback = FakeCallback()

    await rules_callback(callback)

    assert callback.message.edit_text_calls[0]["text"] == RULES_MENU_TEXT
    assert callback.answer_calls == [{"text": None}]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("handler", "expected_title"),
    [
        (terms_callback, "Пользовательское соглашение"),
        (refund_callback, "Условия возврата"),
        (privacy_callback, "Политика конфиденциальности"),
    ],
)
async def test_legal_callbacks_send_document_in_safe_chunks(
    handler,
    expected_title,
):
    callback = FakeCallback()

    await handler(callback)

    assert callback.answer_calls == [{"text": None}]
    assert callback.message.answer_calls
    assert expected_title in callback.message.answer_calls[0]["text"]
    assert all(
        len(call["text"]) <= LEGAL_CHUNK_LIMIT
        for call in callback.message.answer_calls
    )
    assert "reply_markup" in callback.message.answer_calls[-1]


@pytest.mark.asyncio
async def test_tariffs_callback_shows_current_available_tariff():
    callback = FakeCallback()

    await tariffs_callback(callback)

    text = callback.message.edit_text_calls[0]["text"]
    assert "1 устройство — 4 USDT" in text
    assert "30 дней" in text
    assert callback.answer_calls == [{"text": None}]
