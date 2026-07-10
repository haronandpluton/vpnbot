from app.bot.handlers.legal import (
    LEGAL_CHUNK_LIMIT,
    RULES_MENU_TEXT,
    load_legal_text,
    rules_back_keyboard,
    rules_keyboard,
    split_telegram_text,
)


def test_rules_menu_contains_all_sections():
    assert "Terms of Service" in RULES_MENU_TEXT
    assert "Refund and Payment Cancellation Policy" in RULES_MENU_TEXT
    assert "Privacy Policy" in RULES_MENU_TEXT
    assert "Plans" in RULES_MENU_TEXT


def test_rules_keyboard_contains_expected_callbacks():
    keyboard = rules_keyboard()

    callbacks = [
        button.callback_data
        for row in keyboard.inline_keyboard
        for button in row
    ]

    assert callbacks == [
        "rules:terms",
        "rules:refund",
        "rules:privacy",
        "rules:tariffs",
        "back_to_main_menu",
    ]


def test_rules_back_keyboard_contains_navigation_callbacks():
    keyboard = rules_back_keyboard()

    callbacks = [
        button.callback_data
        for row in keyboard.inline_keyboard
        for button in row
    ]

    assert callbacks == [
        "rules",
        "back_to_main_menu",
    ]


def test_legal_documents_are_available():
    terms = load_legal_text("terms.txt")
    privacy = load_legal_text("privacy.txt")
    refund = load_legal_text("refund_policy.txt")

    assert terms.startswith("Terms of Service")
    assert privacy.startswith("Privacy Policy")
    assert refund.startswith("Refund and Payment Cancellation Policy")


def test_long_legal_text_is_split_within_telegram_limit():
    text = "\n\n".join(
        f"Раздел {index}. " + ("Текст документа. " * 100)
        for index in range(20)
    )

    chunks = split_telegram_text(text)

    assert len(chunks) > 1
    assert all(chunks)
    assert all(
        len(chunk) <= LEGAL_CHUNK_LIMIT
        for chunk in chunks
    )


def test_short_legal_text_is_not_split():
    assert split_telegram_text("Короткий текст") == [
        "Короткий текст"
    ]


def test_empty_legal_text_returns_no_messages():
    assert split_telegram_text("   \n\n   ") == []