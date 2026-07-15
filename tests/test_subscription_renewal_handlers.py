from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest

import app.bot.handlers.buy as buy_module
from app.bot.handlers.buy import (
    renew_subscription_callback,
    select_payment_callback,
    select_renewal_tariff_callback,
)
from app.bot.keyboards.main_menu import (
    payment_method_keyboard,
    tariff_keyboard,
)
from app.common.enums import TariffCode


class FakeMessage:
    def __init__(self) -> None:
        self.answer_calls: list[dict] = []
        self.edit_text_calls: list[dict] = []

    async def answer(self, text: str, **kwargs) -> None:
        self.answer_calls.append({"text": text, **kwargs})

    async def edit_text(self, text: str, **kwargs) -> None:
        self.edit_text_calls.append({"text": text, **kwargs})


class FakeCallback:
    def __init__(self, *, data: str) -> None:
        self.data = data
        self.from_user = SimpleNamespace(
            id=123,
            username="ivan",
            first_name="Ivan",
            last_name="Redeemer",
            language_code="ru",
        )
        self.message = FakeMessage()
        self.answer_calls: list[dict] = []

    async def answer(
        self,
        text: str | None = None,
        **kwargs,
    ) -> None:
        self.answer_calls.append({"text": text, **kwargs})


class FakeSession:
    def __init__(self) -> None:
        self.rollback_count = 0

    async def rollback(self) -> None:
        self.rollback_count += 1


def callback_rows(markup):
    return [[button.callback_data for button in row] for row in markup.inline_keyboard]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "data",
    [
        "renew_subscription:not-a-number",
        "renew_subscription:0",
        "renew_subscription:-1",
    ],
)
async def test_renew_subscription_rejects_invalid_subscription_id(data):
    callback = FakeCallback(data=data)

    await renew_subscription_callback(callback)

    assert callback.message.edit_text_calls == []
    assert callback.answer_calls == [
        {
            "text": "Invalid subscription.",
            "show_alert": True,
        }
    ]


@pytest.mark.asyncio
async def test_renew_subscription_opens_tariffs_scoped_to_subscription():
    callback = FakeCallback(data="renew_subscription:50")

    await renew_subscription_callback(callback)

    assert callback.message.edit_text_calls[0]["text"] == (
        "Subscription renewal ID: 50\n\nChoose a renewal period:"
    )
    assert callback_rows(callback.message.edit_text_calls[0]["reply_markup"]) == [
        ["renew_tariff:50:period_1_month"],
        ["renew_tariff:50:period_2_months"],
        ["renew_tariff:50:period_3_months"],
        ["my_subscription"],
    ]
    assert callback.answer_calls == [{"text": None}]


@pytest.mark.asyncio
async def test_renewal_tariff_keeps_subscription_id_in_payment_step():
    callback = FakeCallback(data="renew_tariff:50:period_2_months")

    await select_renewal_tariff_callback(callback)

    text = callback.message.edit_text_calls[0]["text"]
    assert "Subscription renewal ID: 50" in text
    assert "Plan: 66 days (60 days + 6 days 🎁)" in text
    assert "Access period: 66 days" in text
    assert callback_rows(
        callback.message.edit_text_calls[0]["reply_markup"]
    ) == [
               [
                   "renew_pay:50:period_2_months:cryptobot_usdt",
                   "renew_pay:50:period_2_months:cryptobot_usdc",
               ],
               [
                   "renew_pay:50:period_2_months:cryptobot_btc",
                   "renew_pay:50:period_2_months:cryptobot_eth",
               ],
               [
                   "renew_pay:50:period_2_months:cryptobot_ton",
                   "renew_pay:50:period_2_months:cryptobot_ltc",
               ],
               [
                   "renew_pay:50:period_2_months:cryptobot_bnb",
                   "renew_pay:50:period_2_months:cryptobot_trx",
               ],
               ["renew_subscription:50"],
           ]
    assert callback.answer_calls == [{"text": None}]

@pytest.mark.asyncio
async def test_renewal_tariff_shows_stars_when_enabled(
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
        data="renew_tariff:50:period_2_months"
    )

    await select_renewal_tariff_callback(callback)

    assert callback_rows(
        callback.message.edit_text_calls[0]["reply_markup"]
    ) == [
        [
            "renew_pay:50:period_2_months:cryptobot_usdt",
            "renew_pay:50:period_2_months:cryptobot_usdc",
        ],
        [
            "renew_pay:50:period_2_months:cryptobot_btc",
            "renew_pay:50:period_2_months:cryptobot_eth",
        ],
        [
            "renew_pay:50:period_2_months:cryptobot_ton",
            "renew_pay:50:period_2_months:cryptobot_ltc",
        ],
        [
            "renew_pay:50:period_2_months:cryptobot_bnb",
            "renew_pay:50:period_2_months:cryptobot_trx",
        ],
        ["renew_stars:50:period_2_months"],
        ["renew_subscription:50"],
    ]


@pytest.mark.asyncio
async def test_renewal_payment_creates_order_for_selected_subscription(
    monkeypatch,
):
    session = FakeSession()
    created_order_kwargs = []
    invoice_order_ids = []
    order = SimpleNamespace(
        id=23,
        destination_address=None,
        device_limit=1,
        duration_days=66,
        price_usd=Decimal("7.50"),
    )

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
        lambda: SimpleNamespace(
            cryptobot_enabled=True,
            dev_mode=False,
        ),
    )
    monkeypatch.setattr(
        buy_module,
        "OrderService",
        FakeOrderService,
    )
    monkeypatch.setattr(
        buy_module,
        "CryptoBotPaymentService",
        FakeCryptoBotPaymentService,
    )

    callback = FakeCallback(data=("renew_pay:50:period_2_months:cryptobot_usdt"))

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
            "target_subscription_id": 50,
        }
    ]
    assert invoice_order_ids == [23]
    text = callback.message.edit_text_calls[0]["text"]
    assert "Renewal order created." in text
    assert "Subscription ID: 50" in text
    assert "Order ID: 23" in text
    assert callback.answer_calls == [{"text": None}]
    assert session.rollback_count == 0


@pytest.mark.asyncio
async def test_invalid_renewal_target_does_not_create_invoice(
    monkeypatch,
):
    session = FakeSession()
    invoice_service_created = False

    class FakeOrderService:
        def __init__(self, session_arg) -> None:
            assert session_arg is session

        async def create_order(self, **kwargs):
            raise ValueError("Target subscription not found")

    class FakeCryptoBotPaymentService:
        def __init__(self, session_arg) -> None:
            nonlocal invoice_service_created
            invoice_service_created = True

    monkeypatch.setattr(
        buy_module,
        "get_settings",
        lambda: SimpleNamespace(
            cryptobot_enabled=True,
            dev_mode=False,
        ),
    )
    monkeypatch.setattr(
        buy_module,
        "OrderService",
        FakeOrderService,
    )
    monkeypatch.setattr(
        buy_module,
        "CryptoBotPaymentService",
        FakeCryptoBotPaymentService,
    )

    callback = FakeCallback(data=("renew_pay:50:period_1_month:cryptobot_usdt"))

    await select_payment_callback(callback, session=session)

    assert invoice_service_created is False
    assert callback.message.edit_text_calls == []
    assert callback.answer_calls == [
        {
            "text": "This subscription cannot be renewed.",
            "show_alert": True,
        }
    ]


def test_renewal_callback_data_fits_telegram_limit():
    max_subscription_id = 2_147_483_647

    tariff_markup = tariff_keyboard(
        target_subscription_id=max_subscription_id,
    )
    payment_markup = payment_method_keyboard(
        "period_3_months",
        target_subscription_id=max_subscription_id,
    )

    callback_values = [
        button.callback_data
        for markup in (tariff_markup, payment_markup)
        for row in markup.inline_keyboard
        for button in row
        if button.callback_data is not None
    ]

    assert callback_values
    assert all(len(value.encode("utf-8")) <= 64 for value in callback_values)
