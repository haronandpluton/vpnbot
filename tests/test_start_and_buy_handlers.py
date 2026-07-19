from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest

import app.bot.handlers.buy as buy_module
import app.bot.handlers.start as start_module
from app.bot.handlers.buy import (
    buy_command,
    buy_vpn_callback,
    select_payment_callback,
    select_tariff_callback,
)
from app.bot.handlers.start import (
    activate_trial_callback,
    back_to_main_menu_callback,
    main_menu_text,
    start_command,
)
from app.common.enums import TariffCode
from app.payment_adapters.cryptobot import CryptoBotAPIError

from datetime import datetime, timezone

class FakeMessage:
    def __init__(self, *, from_user=None) -> None:
        self.from_user = from_user or SimpleNamespace(
            id=123,
            username="ivan",
            first_name="Ivan",
            last_name="Redeemer",
            language_code="ru",
        )
        self.answer_calls: list[dict] = []
        self.edit_text_calls: list[dict] = []

    async def answer(self, text: str, **kwargs) -> None:
        self.answer_calls.append({"text": text, **kwargs})

    async def edit_text(self, text: str, **kwargs) -> None:
        self.edit_text_calls.append({"text": text, **kwargs})


class FakeCallback:
    def __init__(self, *, data: str, from_user=None) -> None:
        self.data = data
        self.from_user = from_user or SimpleNamespace(
            id=123,
            username="ivan",
            first_name="Ivan",
            last_name="Redeemer",
            language_code="ru",
        )
        self.message = FakeMessage()
        self.answer_calls: list[dict] = []

    async def answer(self, text: str | None = None, **kwargs) -> None:
        self.answer_calls.append({"text": text, **kwargs})


class FakeSession:
    def __init__(self) -> None:
        self.commit_count = 0
        self.rollback_count = 0

    async def commit(self) -> None:
        self.commit_count += 1

    async def rollback(self) -> None:
        self.rollback_count += 1


def assert_callback_rows(markup, expected):
    assert [
        [button.callback_data for button in row] for row in markup.inline_keyboard
    ] == expected


def test_main_menu_text_is_stable_entrypoint_copy():
    assert main_menu_text() == (
        "🎁 Welcome to Present VPN! 🎁\n\n"
        "I am your personal bot and assistant 🤖\n\n"
        "I'll help you connect to VPN in seconds, securely access your "
        "favorite websites and apps, and keep your privacy protected\n\n"
        "🎁 Unique Present Days Program 🎁\n\n"
        "✨ Every subscription already includes a present. Purchase any "
        "plan and automatically receive extra VPN days. The longer your "
        "subscription, the more present days you get ✨"
    )


def test_main_menu_entities_cover_gifts_robot_and_sparkles():
    text = main_menu_text()
    entities = start_module.main_menu_entities(text)

    custom_emoji_ids = [
        entity.custom_emoji_id
        for entity in entities
    ]

    assert len(custom_emoji_ids) == 7
    assert (
        custom_emoji_ids.count(
            start_module.GIFT_CUSTOM_EMOJI_ID
        )
        == 4
    )
    assert (
        custom_emoji_ids.count(
            start_module.ROBOT_CUSTOM_EMOJI_ID
        )
        == 1
    )
    assert (
        custom_emoji_ids.count(
            start_module.SPARKLE_CUSTOM_EMOJI_ID
        )
        == 2
    )

    encoded_text = text.encode("utf-16-le")

    placeholders = [
        encoded_text[
            entity.offset * 2:
            (entity.offset + entity.length) * 2
        ].decode("utf-16-le")
        for entity in entities
    ]

    expected_placeholder_by_id = {
        start_module.GIFT_CUSTOM_EMOJI_ID: "🎁",
        start_module.ROBOT_CUSTOM_EMOJI_ID: "🤖",
        start_module.SPARKLE_CUSTOM_EMOJI_ID: "✨",
    }

    assert placeholders == [
        expected_placeholder_by_id[entity.custom_emoji_id]
        for entity in entities
    ]


@pytest.mark.asyncio
async def test_start_command_sends_buy_menu_for_ineligible_user(
    monkeypatch,
):
    session = FakeSession()
    service_calls = []

    class FakeOrderService:
        def __init__(self, session_arg) -> None:
            assert session_arg is session

        async def get_or_create_user(self, **kwargs):
            service_calls.append(kwargs)
            return SimpleNamespace(
                id=7,
                trial_eligible=False,
            )

    monkeypatch.setattr(
        start_module,
        "OrderService",
        FakeOrderService,
    )

    message = FakeMessage()

    await start_command(
        message,
        session=session,
    )

    assert service_calls == [
        {
            "telegram_id": 123,
            "username": "ivan",
            "first_name": "Ivan",
            "last_name": "Redeemer",
            "language_code": "ru",
        }
    ]
    assert session.commit_count == 1
    assert session.rollback_count == 0

    assert message.answer_calls[0]["text"] == main_menu_text()
    assert (
        message.answer_calls[0]["entities"]
        == start_module.main_menu_entities(
            main_menu_text()
        )
    )
    assert_callback_rows(
        message.answer_calls[0]["reply_markup"],
        [
            ["buy_vpn"],
            ["my_subscription"],
            ["download_vpn"],
            ["faq", "support"],
        ],
    )

@pytest.mark.asyncio
async def test_start_command_sends_trial_menu_for_eligible_user(
    monkeypatch,
):
    session = FakeSession()

    class FakeOrderService:
        def __init__(self, session_arg) -> None:
            assert session_arg is session

        async def get_or_create_user(self, **kwargs):
            return SimpleNamespace(
                id=7,
                trial_eligible=True,
            )

    monkeypatch.setattr(
        start_module,
        "OrderService",
        FakeOrderService,
    )

    message = FakeMessage()

    await start_command(
        message,
        session=session,
    )

    assert session.commit_count == 1
    assert_callback_rows(
        message.answer_calls[0]["reply_markup"],
        [
            ["activate_trial"],
            ["my_subscription"],
            ["download_vpn"],
            ["faq", "support"],
        ],
    )


@pytest.mark.asyncio
async def test_back_to_main_menu_callback_uses_current_trial_state(
    monkeypatch,
):
    session = FakeSession()

    class FakeOrderService:
        def __init__(self, session_arg) -> None:
            assert session_arg is session

        async def get_or_create_user(self, **kwargs):
            return SimpleNamespace(
                id=7,
                trial_eligible=True,
            )

    monkeypatch.setattr(
        start_module,
        "OrderService",
        FakeOrderService,
    )

    callback = FakeCallback(data="back_to_main_menu")

    await back_to_main_menu_callback(
        callback,
        session=session,
    )

    assert session.commit_count == 1
    assert callback.message.edit_text_calls[0]["text"] == main_menu_text()
    assert (
        callback.message.edit_text_calls[0]["entities"]
        == start_module.main_menu_entities(
            main_menu_text()
        )
    )
    assert_callback_rows(
        callback.message.edit_text_calls[0]["reply_markup"],
        [
            ["activate_trial"],
            ["my_subscription"],
            ["download_vpn"],
            ["faq", "support"],
        ],
    )
    assert callback.answer_calls == [{"text": None}]


@pytest.mark.asyncio
async def test_buy_command_sends_tariff_keyboard():
    message = FakeMessage()

    await buy_command(message)

    assert message.answer_calls[0]["text"] == "Choose a plan 🎁"
    assert_callback_rows(
        message.answer_calls[0]["reply_markup"],
        [
            ["select_tariff:period_1_month"],
            ["select_tariff:period_2_months"],
            ["select_tariff:period_3_months"],
            ["back_to_main_menu"],
        ],
    )


@pytest.mark.asyncio
async def test_buy_vpn_callback_edits_to_tariff_keyboard_and_answers_callback():
    callback = FakeCallback(data="buy_vpn")

    await buy_vpn_callback(callback)

    assert callback.message.edit_text_calls[0]["text"] == "Choose a plan 🎁"
    assert_callback_rows(
        callback.message.edit_text_calls[0]["reply_markup"],
        [
            ["select_tariff:period_1_month"],
            ["select_tariff:period_2_months"],
            ["select_tariff:period_3_months"],
            ["back_to_main_menu"],
        ],
    )
    assert callback.answer_calls == [{"text": None}]


@pytest.mark.asyncio
async def test_select_tariff_blocks_unavailable_tariff_without_editing_message():
    callback = FakeCallback(data="select_tariff:devices_2")

    await select_tariff_callback(callback)

    assert callback.message.edit_text_calls == []
    assert callback.answer_calls == [
        {
            "text": "This plan is unavailable.",
            "show_alert": True,
        }
    ]


@pytest.mark.asyncio
async def test_select_tariff_period_1_month_edits_to_payment_method_keyboard():
    callback = FakeCallback(data="select_tariff:period_1_month")

    await select_tariff_callback(callback)

    text = callback.message.edit_text_calls[0]["text"]
    assert "Plan: 33 days (30 days + 3 days 🎁)" in text
    assert "Devices: 1" in text
    assert "Access period: 33 days" in text
    assert "Price: 4 USD" in text
    assert_callback_rows(
        callback.message.edit_text_calls[0]["reply_markup"],
        [
            [
                "select_payment:period_1_month:cryptobot_usdt",
                "select_payment:period_1_month:cryptobot_usdc",
            ],
            [
                "select_payment:period_1_month:cryptobot_btc",
                "select_payment:period_1_month:cryptobot_eth",
            ],
            [
                "select_payment:period_1_month:cryptobot_ton",
                "select_payment:period_1_month:cryptobot_ltc",
            ],
            [
                "select_payment:period_1_month:cryptobot_bnb",
                "select_payment:period_1_month:cryptobot_trx",
            ],
            ["buy_vpn"],
        ],
    )
    assert callback.answer_calls == [{"text": None}]


@pytest.mark.asyncio
async def test_select_payment_rejects_malformed_callback_data():
    callback = FakeCallback(data="select_payment:broken")

    await select_payment_callback(callback, session=FakeSession())

    assert callback.answer_calls == [
        {"text": "Invalid payment selection", "show_alert": True}
    ]
    assert callback.message.edit_text_calls == []


@pytest.mark.asyncio
async def test_select_payment_rejects_unavailable_tariff_before_order_creation(
    monkeypatch,
):
    order_service_calls = []

    class FakeOrderService:
        def __init__(self, session) -> None:
            order_service_calls.append(session)

    monkeypatch.setattr(buy_module, "OrderService", FakeOrderService)
    callback = FakeCallback(data="select_payment:devices_2:cryptobot_usdt")

    await select_payment_callback(callback, session=FakeSession())

    assert callback.answer_calls == [
        {"text": "This plan is unavailable", "show_alert": True}
    ]
    assert order_service_calls == []


@pytest.mark.asyncio
async def test_select_payment_rejects_unsupported_payment_option_before_order_creation(
    monkeypatch,
):
    order_service_calls = []

    class FakeOrderService:
        def __init__(self, session) -> None:
            order_service_calls.append(session)

    monkeypatch.setattr(buy_module, "OrderService", FakeOrderService)
    callback = FakeCallback(data="select_payment:period_1_month:usdt_trc20")

    await select_payment_callback(callback, session=FakeSession())

    assert callback.answer_calls == [
        {"text": "This payment method is currently unavailable", "show_alert": True}
    ]
    assert order_service_calls == []


@pytest.mark.asyncio
async def test_select_payment_rejects_cryptobot_when_disabled_before_order_creation(
    monkeypatch,
):
    order_service_calls = []

    class FakeOrderService:
        def __init__(self, session) -> None:
            order_service_calls.append(session)

    monkeypatch.setattr(
        buy_module,
        "get_settings",
        lambda: SimpleNamespace(cryptobot_enabled=False),
    )
    monkeypatch.setattr(buy_module, "OrderService", FakeOrderService)
    callback = FakeCallback(data="select_payment:period_1_month:cryptobot_usdt")

    await select_payment_callback(callback, session=FakeSession())

    assert callback.answer_calls == [
        {"text": "CryptoBot is currently unavailable", "show_alert": True}
    ]
    assert order_service_calls == []


@pytest.mark.asyncio
async def test_select_payment_happy_path_creates_order_invoice_and_payment_keyboard(
    monkeypatch,
):
    session = FakeSession()
    order = SimpleNamespace(
        id=23,
        destination_address=None,
        device_limit=1,
        duration_days=66,
        price_usd=Decimal("7.50"),
    )
    created_order_kwargs = []
    invoice_order_ids = []

    class FakeOrderService:
        def __init__(self, session_arg) -> None:
            assert session_arg is session

        async def create_order(self, **kwargs):
            created_order_kwargs.append(kwargs)
            return order

    class FakeCryptoBotPaymentService:
        def __init__(self, session_arg) -> None:
            assert session_arg is session

        async def ensure_invoice_for_order(self, order_id: int):
            invoice_order_ids.append(order_id)
            return {
                "bot_invoice_url": "https://bot.example/invoice-23",
                "pay_url": "https://deprecated.example/invoice-23",
            }

    monkeypatch.setattr(
        buy_module,
        "get_settings",
        lambda: SimpleNamespace(cryptobot_enabled=True, dev_mode=True),
    )
    monkeypatch.setattr(buy_module, "OrderService", FakeOrderService)
    monkeypatch.setattr(
        buy_module,
        "CryptoBotPaymentService",
        FakeCryptoBotPaymentService,
    )

    callback = FakeCallback(data="select_payment:period_2_months:cryptobot_btc")

    await select_payment_callback(callback, session=session)

    assert created_order_kwargs == [
        {
            "telegram_id": 123,
            "tariff_code": TariffCode.PERIOD_2_MONTHS,
            "payment_option_code": "cryptobot_btc",
            "username": "ivan",
            "first_name": "Ivan",
            "last_name": "Redeemer",
            "language_code": "ru",
        }
    ]
    assert invoice_order_ids == [23]
    text = callback.message.edit_text_calls[0]["text"]
    assert "Order ID: 23" in text
    assert "Plan: 66 days (60 days + 6 days 🎁)" in text
    assert "Access period: 66 days" in text
    assert "Price: 7.50 USD" in text
    assert "Payment currency: BTC" in text
    edit_call = callback.message.edit_text_calls[0]
    assert "parse_mode" not in edit_call
    assert edit_call["entities"]
    assert_callback_rows(
        callback.message.edit_text_calls[0]["reply_markup"],
        [[None], ["check_payment:23"], ["dev_confirm_payment:23"]],
    )
    assert (
        callback.message.edit_text_calls[0]["reply_markup"].inline_keyboard[0][0].url
        == "https://bot.example/invoice-23"
    )
    assert callback.answer_calls == [{"text": None}]
    assert session.rollback_count == 0


@pytest.mark.asyncio
async def test_select_payment_rolls_back_and_notifies_user_when_cryptobot_invoice_fails(
    monkeypatch,
):
    session = FakeSession()
    order = SimpleNamespace(id=23, destination_address=None)

    class FakeOrderService:
        def __init__(self, session_arg) -> None:
            assert session_arg is session

        async def create_order(self, **kwargs):
            return order

    class FakeCryptoBotPaymentService:
        def __init__(self, session_arg) -> None:
            assert session_arg is session

        async def ensure_invoice_for_order(self, order_id: int):
            raise CryptoBotAPIError("createInvoice failed")

    monkeypatch.setattr(
        buy_module,
        "get_settings",
        lambda: SimpleNamespace(cryptobot_enabled=True, dev_mode=False),
    )
    monkeypatch.setattr(buy_module, "OrderService", FakeOrderService)
    monkeypatch.setattr(
        buy_module,
        "CryptoBotPaymentService",
        FakeCryptoBotPaymentService,
    )

    callback = FakeCallback(data="select_payment:period_1_month:cryptobot_usdt")

    with pytest.raises(CryptoBotAPIError, match="createInvoice failed"):
        await select_payment_callback(callback, session=session)

    assert session.rollback_count == 1
    assert callback.message.answer_calls == [
        {
            "text": (
                "Could not create a CryptoBot invoice. "
                "Try again later or contact support."
            )
        }
    ]
    assert callback.answer_calls == [
        {"text": "Invoice creation error", "show_alert": True}
    ]
    assert callback.message.edit_text_calls == []


@pytest.mark.asyncio
async def test_select_tariff_shows_stars_when_enabled(
    monkeypatch,
):
    monkeypatch.setattr(
        buy_module,
        "get_settings",
        lambda: SimpleNamespace(
            telegram_stars_enabled=True,
        ),
    )

    callback = FakeCallback(
        data="select_tariff:period_1_month"
    )

    await select_tariff_callback(callback)

    assert_callback_rows(
        callback.message.edit_text_calls[0]["reply_markup"],
        [
            [
                "select_payment:period_1_month:cryptobot_usdt",
                "select_payment:period_1_month:cryptobot_usdc",
            ],
            [
                "select_payment:period_1_month:cryptobot_btc",
                "select_payment:period_1_month:cryptobot_eth",
            ],
            [
                "select_payment:period_1_month:cryptobot_ton",
                "select_payment:period_1_month:cryptobot_ltc",
            ],
            [
                "select_payment:period_1_month:cryptobot_bnb",
                "select_payment:period_1_month:cryptobot_trx",
            ],
            ["select_stars:period_1_month"],
            ["buy_vpn"],
        ],
    )

@pytest.mark.asyncio
async def test_activate_trial_callback_replaces_trial_button_and_sends_access(
    monkeypatch,
):
    session = FakeSession()
    expires_at = datetime(
        2030,
        1,
        4,
        12,
        0,
        tzinfo=timezone.utc,
    )
    activation_calls = []

    class FakeTrialActivationService:
        def __init__(self, session_arg) -> None:
            assert session_arg is session

        async def activate_trial(self, **kwargs):
            activation_calls.append(kwargs)
            return SimpleNamespace(
                status="activated",
                subscription_id=77,
                expires_at=expires_at,
                config_uri=(
                    "https://connect.example/trial"
                ),
            )

    monkeypatch.setattr(
        start_module,
        "TrialActivationService",
        FakeTrialActivationService,
    )

    callback = FakeCallback(data="activate_trial")

    await activate_trial_callback(
        callback,
        session=session,
    )

    assert activation_calls == [
        {"telegram_id": 123}
    ]
    assert callback.answer_calls == [{"text": None}]

    assert_callback_rows(
        callback.message.edit_text_calls[0][
            "reply_markup"
        ],
        [
            ["buy_vpn"],
            ["my_subscription"],
            ["download_vpn"],
            ["faq", "support"],
        ],
    )

    access_message = callback.message.answer_calls[0]

    assert "Your 3 free VPN days are active." in (
        access_message["text"]
    )
    assert "Active until: 04.01.2030 12:00" in (
        access_message["text"]
    )
    assert_callback_rows(
        access_message["reply_markup"],
        [
            ["vpn_access:show_config:77"],
            ["vpn_access:show_config:77"],
            ["buy_vpn"],
            [
                "vpn_access:happ_android",
                "vpn_access:happ_ios",
            ],
            ["vpn_access:happ_fallback"],
        ],
    )

@pytest.mark.asyncio
async def test_activate_trial_callback_handles_already_claimed_trial(
    monkeypatch,
):
    session = FakeSession()

    class FakeTrialActivationService:
        def __init__(self, session_arg) -> None:
            assert session_arg is session

        async def activate_trial(self, **kwargs):
            return SimpleNamespace(
                status="not_eligible",
                subscription_id=None,
                expires_at=None,
                config_uri=None,
            )

    monkeypatch.setattr(
        start_module,
        "TrialActivationService",
        FakeTrialActivationService,
    )

    callback = FakeCallback(data="activate_trial")

    await activate_trial_callback(
        callback,
        session=session,
    )

    assert callback.answer_calls == [{"text": None}]
    assert_callback_rows(
        callback.message.edit_text_calls[0][
            "reply_markup"
        ],
        [
            ["buy_vpn"],
            ["my_subscription"],
            ["download_vpn"],
            ["faq", "support"],
        ],
    )
    assert callback.message.answer_calls == [
        {
            "text": (
                "Your free 3-day VPN access has already "
                "been claimed."
            )
        }
    ]

@pytest.mark.asyncio
async def test_activate_trial_callback_reports_infrastructure_failure(
    monkeypatch,
):
    session = FakeSession()

    class FakeTrialActivationService:
        def __init__(self, session_arg) -> None:
            assert session_arg is session

        async def activate_trial(self, **kwargs):
            raise RuntimeError("3x-ui unavailable")

    monkeypatch.setattr(
        start_module,
        "TrialActivationService",
        FakeTrialActivationService,
    )

    callback = FakeCallback(data="activate_trial")

    await activate_trial_callback(
        callback,
        session=session,
    )

    assert callback.answer_calls == [{"text": None}]
    assert callback.message.edit_text_calls == []
    assert callback.message.answer_calls == [
        {
            "text": (
                "Could not activate your free VPN access "
                "right now.\n\n"
                "Please try again later or contact support."
            )
        }
    ]
