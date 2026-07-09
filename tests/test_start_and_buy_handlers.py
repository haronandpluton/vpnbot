from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest

import app.bot.handlers.buy as buy_module
from app.bot.handlers.buy import (
    buy_command,
    buy_vpn_callback,
    select_payment_callback,
    select_tariff_callback,
)
from app.bot.handlers.start import (
    back_to_main_menu_callback,
    main_menu_text,
    start_command,
)
from app.common.enums import TariffCode
from app.payment_adapters.cryptobot import CryptoBotAPIError


class FakeMessage:
    def __init__(self) -> None:
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
        self.rollback_count = 0

    async def rollback(self) -> None:
        self.rollback_count += 1


def assert_callback_rows(markup, expected):
    assert [
        [button.callback_data for button in row]
        for row in markup.inline_keyboard
    ] == expected


def test_main_menu_text_is_stable_entrypoint_copy():
    assert main_menu_text() == (
        "VPNFOR\n\n"
        "Быстрый VPN-доступ для стабильного подключения.\n\n"
        "Выбери действие:"
    )


@pytest.mark.asyncio
async def test_start_command_sends_main_menu():
    message = FakeMessage()

    await start_command(message)

    assert message.answer_calls[0]["text"] == main_menu_text()
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
async def test_back_to_main_menu_callback_edits_message_and_answers_callback():
    callback = FakeCallback(data="back_to_main_menu")

    await back_to_main_menu_callback(callback)

    assert callback.message.edit_text_calls[0]["text"] == main_menu_text()
    assert_callback_rows(
        callback.message.edit_text_calls[0]["reply_markup"],
        [
            ["buy_vpn"],
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

    assert message.answer_calls[0]["text"] == "Выбери тариф:"
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

    assert callback.message.edit_text_calls[0]["text"] == "Выбери тариф:"
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
            "text": "Этот тариф недоступен.",
            "show_alert": True,
        }
    ]


@pytest.mark.asyncio
async def test_select_tariff_period_1_month_edits_to_payment_method_keyboard():
    callback = FakeCallback(data="select_tariff:period_1_month")

    await select_tariff_callback(callback)

    text = callback.message.edit_text_calls[0]["text"]
    assert "Тариф: 1 месяц + 3 дня в подарок" in text
    assert "Устройств: 1" in text
    assert "Срок доступа: 33 дня" in text
    assert "Стоимость: 4 USDT" in text
    assert_callback_rows(
        callback.message.edit_text_calls[0]["reply_markup"],
        [["select_payment:period_1_month:cryptobot_usdt"], ["buy_vpn"]],
    )
    assert callback.answer_calls == [{"text": None}]


@pytest.mark.asyncio
async def test_select_payment_rejects_malformed_callback_data():
    callback = FakeCallback(data="select_payment:broken")

    await select_payment_callback(callback, session=FakeSession())

    assert callback.answer_calls == [
        {"text": "Некорректный выбор оплаты", "show_alert": True}
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
        {"text": "Этот тариф недоступен", "show_alert": True}
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
        {"text": "Этот способ оплаты пока недоступен", "show_alert": True}
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
        {"text": "CryptoBot сейчас отключен", "show_alert": True}
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
            return {"pay_url": "https://pay.example/invoice-23"}

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

    callback = FakeCallback(data="select_payment:period_2_months:cryptobot_usdt")

    await select_payment_callback(callback, session=session)

    assert created_order_kwargs == [
        {
            "telegram_id": 123,
            "tariff_code": TariffCode.PERIOD_2_MONTHS,
            "payment_option_code": "cryptobot_usdt",
            "username": "ivan",
            "first_name": "Ivan",
            "last_name": "Redeemer",
            "language_code": "ru",
        }
    ]
    assert invoice_order_ids == [23]
    text = callback.message.edit_text_calls[0]["text"]
    assert "Order ID: 23" in text
    assert "Тариф: 2 месяца + 6 дней в подарок" in text
    assert "Срок доступа: 66 дней" in text
    assert "Сумма: 7.50 USDT" in text
    assert callback.message.edit_text_calls[0]["parse_mode"] == "HTML"
    assert_callback_rows(
        callback.message.edit_text_calls[0]["reply_markup"],
        [[None], ["check_payment:23"], ["dev_confirm_payment:23"]],
    )
    assert (
        callback.message.edit_text_calls[0]["reply_markup"]
        .inline_keyboard[0][0]
        .url
        == "https://pay.example/invoice-23"
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
                "Не удалось создать счёт CryptoBot. "
                "Попробуй позже или обратись в поддержку."
            )
        }
    ]
    assert callback.answer_calls == [
        {"text": "Ошибка создания счёта", "show_alert": True}
    ]
    assert callback.message.edit_text_calls == []