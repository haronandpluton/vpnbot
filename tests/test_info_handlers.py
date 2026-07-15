from __future__ import annotations

from types import SimpleNamespace

import pytest

import app.bot.handlers.info as info_module
from app.bot.handlers.info import (
    HAPP_ANDROID_URL,
    HAPP_DESKTOP_RELEASES_URL,
    HAPP_IOS_URL,
    download_platform_keyboard,
    download_vpn_android_callback,
    download_vpn_callback,
    download_vpn_installed_callback,
    download_vpn_ios_callback,
    download_vpn_macos_callback,
    download_vpn_windows_callback,
    faq_callback,
    installed_continue_keyboard,
    platform_download_keyboard,
    support_back_keyboard,
    support_callback,
    support_keyboard,
    support_payment_callback,
    support_vpn_callback,
    paysupport_command,
)


class FakeTelegramBadRequest(Exception):
    pass


class FakeMessage:
    def __init__(self, *, edit_error: Exception | None = None) -> None:
        self.edit_error = edit_error
        self.edit_text_calls: list[dict] = []
        self.answer_calls: list[dict] = []

    async def answer(self, text: str, **kwargs) -> None:
        self.answer_calls.append(
            {
                "text": text,
                **kwargs,
            }
        )

    async def edit_text(self, text: str, **kwargs) -> None:
        if self.edit_error is not None:
            raise self.edit_error

        self.edit_text_calls.append({"text": text, **kwargs})


class FakeCallback:
    def __init__(self, *, edit_error: Exception | None = None) -> None:
        self.message = FakeMessage(edit_error=edit_error)
        self.answer_calls: list[dict] = []

    async def answer(self, text: str | None = None, **kwargs) -> None:
        self.answer_calls.append({"text": text, **kwargs})


def row_texts(markup):
    return [[button.text for button in row] for row in markup.inline_keyboard]


def row_callbacks(markup):
    return [[button.callback_data for button in row] for row in markup.inline_keyboard]


def row_urls(markup):
    return [[button.url for button in row] for row in markup.inline_keyboard]


def test_download_platform_keyboard_has_stable_platform_callbacks():
    markup = download_platform_keyboard()

    assert row_texts(markup) == [
        ["iPhone / iOS", "Android"],
        ["Windows", "macOS"],
        ["Back to Menu"],
    ]
    assert row_callbacks(markup) == [
        ["download_vpn:ios", "download_vpn:android"],
        ["download_vpn:windows", "download_vpn:macos"],
        ["back_to_main_menu"],
    ]


def test_platform_download_keyboard_contains_download_url_installed_and_back_callbacks():
    markup = platform_download_keyboard("https://download.example/app")

    assert row_texts(markup) == [
        ["Download Happ"],
        ["I Have Installed It"],
        ["Back to Platforms"],
        ["Back to Menu"],
    ]
    assert row_urls(markup) == [
        ["https://download.example/app"],
        [None],
        [None],
        [None],
    ]
    assert row_callbacks(markup) == [
        [None],
        ["download_vpn:installed"],
        ["download_vpn"],
        ["back_to_main_menu"],
    ]


def test_installed_continue_keyboard_routes_to_buy_subscription_and_platforms():
    markup = installed_continue_keyboard()

    assert row_texts(markup) == [
        ["Buy VPN", "My Subscription"],
        ["Back to Platforms"],
        ["Back to Menu"],
    ]
    assert row_callbacks(markup) == [
        ["buy_vpn", "my_subscription"],
        ["download_vpn"],
        ["back_to_main_menu"],
    ]


def test_support_keyboard_without_username_hides_direct_support_url(monkeypatch):
    monkeypatch.setattr(
        info_module,
        "get_settings",
        lambda: SimpleNamespace(support_username="   "),
    )

    markup = support_keyboard()

    assert row_texts(markup) == [
        ["Payment Problem"],
        ["VPN Does Not Connect"],
        ["Back to Menu"],
    ]
    assert row_callbacks(markup) == [
        ["support:payment"],
        ["support:vpn"],
        ["back_to_main_menu"],
    ]
    assert row_urls(markup) == [[None], [None], [None]]


def test_support_keyboard_with_username_adds_telegram_url_and_strips_at(monkeypatch):
    monkeypatch.setattr(
        info_module,
        "get_settings",
        lambda: SimpleNamespace(support_username=" @support_bot "),
    )

    markup = support_keyboard()

    assert row_texts(markup) == [
        ["Payment Problem"],
        ["VPN Does Not Connect"],
        ["Contact Support"],
        ["Back to Menu"],
    ]
    assert row_urls(markup) == [[None], [None], ["https://t.me/support_bot"], [None]]


def test_support_back_keyboard_returns_to_support_or_main_menu():
    markup = support_back_keyboard()

    assert row_texts(markup) == [["Back to Support"], ["Back to Menu"]]
    assert row_callbacks(markup) == [["support"], ["back_to_main_menu"]]


@pytest.mark.asyncio
async def test_download_vpn_callback_edits_to_platform_selection_and_answers():
    callback = FakeCallback()

    await download_vpn_callback(callback)

    assert "Download VPN" in callback.message.edit_text_calls[0]["text"]
    assert "Choose your platform:" in callback.message.edit_text_calls[0]["text"]
    assert row_callbacks(callback.message.edit_text_calls[0]["reply_markup"]) == [
        ["download_vpn:ios", "download_vpn:android"],
        ["download_vpn:windows", "download_vpn:macos"],
        ["back_to_main_menu"],
    ]
    assert callback.answer_calls == [{"text": None}]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("handler", "title", "download_url"),
    [
        (download_vpn_ios_callback, "Happ for iPhone / iOS", HAPP_IOS_URL),
        (download_vpn_android_callback, "Happ for Android", HAPP_ANDROID_URL),
        (download_vpn_windows_callback, "Happ for Windows", HAPP_DESKTOP_RELEASES_URL),
        (download_vpn_macos_callback, "Happ for macOS", HAPP_DESKTOP_RELEASES_URL),
    ],
)
async def test_platform_download_callbacks_show_platform_text_url_and_answer(
    handler,
    title,
    download_url,
):
    callback = FakeCallback()

    await handler(callback)

    assert title in callback.message.edit_text_calls[0]["text"]
    assert row_urls(callback.message.edit_text_calls[0]["reply_markup"])[0] == [
        download_url
    ]
    assert row_callbacks(callback.message.edit_text_calls[0]["reply_markup"])[1:] == [
        ["download_vpn:installed"],
        ["download_vpn"],
        ["back_to_main_menu"],
    ]
    assert callback.answer_calls == [{"text": None}]


@pytest.mark.asyncio
async def test_download_vpn_installed_callback_edits_to_continue_actions():
    callback = FakeCallback()

    await download_vpn_installed_callback(callback)

    assert "Client Installed" in callback.message.edit_text_calls[0]["text"]
    assert row_callbacks(callback.message.edit_text_calls[0]["reply_markup"]) == [
        ["buy_vpn", "my_subscription"],
        ["download_vpn"],
        ["back_to_main_menu"],
    ]
    assert callback.answer_calls == [{"text": None}]


@pytest.mark.asyncio
async def test_download_vpn_installed_callback_ignores_message_not_modified(monkeypatch):
    monkeypatch.setattr(info_module, "TelegramBadRequest", FakeTelegramBadRequest)
    callback = FakeCallback(edit_error=FakeTelegramBadRequest("message is not modified"))

    await download_vpn_installed_callback(callback)

    assert callback.message.edit_text_calls == []
    assert callback.answer_calls == [{"text": None}]


@pytest.mark.asyncio
async def test_download_vpn_installed_callback_reraises_other_telegram_bad_request(
    monkeypatch,
):
    monkeypatch.setattr(info_module, "TelegramBadRequest", FakeTelegramBadRequest)
    callback = FakeCallback(edit_error=FakeTelegramBadRequest("message to edit not found"))

    with pytest.raises(FakeTelegramBadRequest, match="message to edit not found"):
        await download_vpn_installed_callback(callback)

    assert callback.answer_calls == []


@pytest.mark.asyncio
async def test_faq_callback_edits_to_faq_and_back_to_main_menu():
    callback = FakeCallback()

    await faq_callback(callback)

    assert "FAQ" in callback.message.edit_text_calls[0]["text"]
    assert "How do I start using the VPN?" in callback.message.edit_text_calls[0]["text"]
    assert (
        "What if I sent the wrong amount or used the wrong network?"
        in callback.message.edit_text_calls[0]["text"]
    )
    assert row_callbacks(callback.message.edit_text_calls[0]["reply_markup"]) == [
        ["back_to_main_menu"]
    ]
    assert callback.answer_calls == [{"text": None}]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("support_username", "expected_contact"),
    [
        ("@support_bot", "Support contact: @support_bot"),
        ("", "The support contact has not been configured yet."),
    ],
)
async def test_support_callback_shows_contact_state_and_support_keyboard(
    monkeypatch,
    support_username,
    expected_contact,
):
    monkeypatch.setattr(
        info_module,
        "get_settings",
        lambda: SimpleNamespace(support_username=support_username),
    )
    callback = FakeCallback()

    await support_callback(callback)

    assert "Support" in callback.message.edit_text_calls[0]["text"]
    assert expected_contact in callback.message.edit_text_calls[0]["text"]
    assert (
        "Order ID, txid, payment amount, network"
        in callback.message.edit_text_calls[0]["text"]
    )
    assert row_callbacks(callback.message.edit_text_calls[0]["reply_markup"])[0:2] == [
        ["support:payment"],
        ["support:vpn"],
    ]
    assert callback.answer_calls == [{"text": None}]


@pytest.mark.asyncio
async def test_support_payment_callback_edits_to_payment_problem_checklist():
    callback = FakeCallback()

    await support_payment_callback(callback)

    assert "Payment Problem" in callback.message.edit_text_calls[0]["text"]
    assert "Order ID." in callback.message.edit_text_calls[0]["text"]
    assert "Transaction txid." in callback.message.edit_text_calls[0]["text"]
    assert row_callbacks(callback.message.edit_text_calls[0]["reply_markup"]) == [
        ["support"],
        ["back_to_main_menu"],
    ]
    assert callback.answer_calls == [{"text": None}]


@pytest.mark.asyncio
async def test_support_vpn_callback_edits_to_vpn_problem_checklist():
    callback = FakeCallback()

    await support_vpn_callback(callback)

    assert "VPN Does Not Connect" in callback.message.edit_text_calls[0]["text"]
    assert "The subscription is active" in callback.message.edit_text_calls[0]["text"]
    assert (
        "Android / iOS / Windows / macOS"
        in callback.message.edit_text_calls[0]["text"]
    )
    assert row_callbacks(callback.message.edit_text_calls[0]["reply_markup"]) == [
        ["support"],
        ["back_to_main_menu"],
    ]
    assert callback.answer_calls == [{"text": None}]

@pytest.mark.asyncio
async def test_paysupport_command_warns_not_to_pay_again_and_shows_support(
    monkeypatch,
):
    monkeypatch.setattr(
        info_module,
        "get_settings",
        lambda: SimpleNamespace(
            support_username=" @support_bot ",
        ),
    )

    message = FakeMessage()

    await paysupport_command(message)

    assert len(message.answer_calls) == 1

    call = message.answer_calls[0]

    assert "Telegram Stars Payment Support" in call["text"]
    assert "do not make another payment" in call["text"]
    assert "Order ID" in call["text"]
    assert "Number of Stars paid" in call["text"]
    assert "Telegram payment receipt" in call["text"]
    assert "Support contact: @support_bot" in call["text"]

    markup = call["reply_markup"]

    assert row_callbacks(markup) == [
        ["support:payment"],
        ["support:vpn"],
        [None],
        ["back_to_main_menu"],
    ]

    assert row_urls(markup) == [
        [None],
        [None],
        ["https://t.me/support_bot"],
        [None],
    ]