from types import SimpleNamespace

import pytest

import app.bot.handlers.payment_stars as stars_handler
from app.services.telegram_stars_payment_service import (
    PreCheckoutDecision,
    StarsInvoice,
)


class FakeMessage:
    def __init__(self, successful_payment=None) -> None:
        self.successful_payment = successful_payment
        self.from_user = SimpleNamespace(id=123)

        self.invoice_calls: list[dict] = []
        self.answer_calls: list[dict] = []

    async def answer_invoice(self, **kwargs):
        self.invoice_calls.append(kwargs)

    async def answer(self, text: str, **kwargs):
        self.answer_calls.append(
            {
                "text": text,
                **kwargs,
            }
        )


class FakeCallback:
    def __init__(self, data: str) -> None:
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

    async def answer(self, text=None, **kwargs):
        self.answer_calls.append(
            {
                "text": text,
                **kwargs,
            }
        )


class FakePreCheckoutQuery:
    def __init__(self) -> None:
        self.from_user = SimpleNamespace(id=123)
        self.invoice_payload = (
            "vpn_stars:41:123:test-signature"
        )
        self.currency = "XTR"
        self.total_amount = 300
        self.answer_calls: list[dict] = []

    async def answer(self, **kwargs):
        self.answer_calls.append(kwargs)

class FakeSuccessfulPayment:
    currency = "XTR"
    total_amount = 300
    invoice_payload = "vpn_stars:41:123:test-signature"
    telegram_payment_charge_id = "charge-123"

    def model_dump(self, **kwargs):
        return {
            "currency": self.currency,
            "total_amount": self.total_amount,
            "invoice_payload": self.invoice_payload,
            "telegram_payment_charge_id": (
                self.telegram_payment_charge_id
            ),
        }

class FakeSuccessfulPaymentService:
    calls: list[dict] = []

    def __init__(self, session) -> None:
        self.session = session

    async def process_successful_payment(self, **kwargs):
        self.__class__.calls.append(kwargs)

        return (
            SimpleNamespace(id=1),
            SimpleNamespace(id=2),
            SimpleNamespace(id=77),
            "https://connect.example/uuid",
        )

@pytest.mark.asyncio
async def test_successful_payment_activates_subscription(
    monkeypatch,
):
    FakeSuccessfulPaymentService.calls = []

    monkeypatch.setattr(
        stars_handler,
        "TelegramStarsPaymentService",
        FakeSuccessfulPaymentService,
    )

    message = FakeMessage(
        successful_payment=FakeSuccessfulPayment(),
    )

    await stars_handler.telegram_stars_successful_payment(
        message,
        object(),
    )

    assert FakeSuccessfulPaymentService.calls == [
        {
            "telegram_id": 123,
            "invoice_payload": (
                "vpn_stars:41:123:test-signature"
            ),
            "currency": "XTR",
            "total_amount": 300,
            "telegram_payment_charge_id": "charge-123",
            "raw_payload": (
                '{"currency": "XTR", '
                '"invoice_payload": '
                '"vpn_stars:41:123:test-signature", '
                '"telegram_payment_charge_id": "charge-123", '
                '"total_amount": 300}'
            ),
        }
    ]

    assert len(message.answer_calls) == 1
    assert "Payment confirmed" in (
        message.answer_calls[0]["text"]
    )

    keyboard = message.answer_calls[0]["reply_markup"]

    assert (
        keyboard.inline_keyboard[0][0].callback_data
        == "vpn_access:show_config:77"
    )

class FailingSuccessfulPaymentService:
    def __init__(self, session) -> None:
        self.session = session

    async def process_successful_payment(self, **kwargs):
        raise RuntimeError("VPN server unavailable")

@pytest.mark.asyncio
async def test_successful_payment_failure_tells_user_not_to_pay_again(
    monkeypatch,
):
    monkeypatch.setattr(
        stars_handler,
        "TelegramStarsPaymentService",
        FailingSuccessfulPaymentService,
    )

    message = FakeMessage(
        successful_payment=FakeSuccessfulPayment(),
    )

    await stars_handler.telegram_stars_successful_payment(
        message,
        object(),
    )

    assert len(message.answer_calls) == 1
    assert "Do not pay again" in (
        message.answer_calls[0]["text"]
    )


class FakeOrderService:
    def __init__(self, session) -> None:
        self.session = session

    async def create_order(self, **kwargs):
        return SimpleNamespace(
            id=41,
            duration_days=33,
        )


class FakeStarsPaymentService:
    def __init__(self, session) -> None:
        self.session = session

    async def create_invoice(self, **kwargs):
        return StarsInvoice(
            order_id=41,
            payload="vpn_stars:41:123:test-signature",
            title="VPN — 33 days",
            description="33 days (30 days + 3 days 🎁)",
            label="VPN access for 33 days",
            amount=300,
        )

    async def validate_pre_checkout(self, **kwargs):
        return PreCheckoutDecision(ok=True)


@pytest.mark.asyncio
async def test_select_stars_sends_300_xtr_invoice(
    monkeypatch,
):
    monkeypatch.setattr(
        stars_handler,
        "OrderService",
        FakeOrderService,
    )
    monkeypatch.setattr(
        stars_handler,
        "TelegramStarsPaymentService",
        FakeStarsPaymentService,
    )
    monkeypatch.setattr(
        stars_handler,
        "get_payment_option",
        lambda code: SimpleNamespace(
            code=code,
            is_active=True,
        ),
    )
    monkeypatch.setattr(
        stars_handler,
        "get_settings",
        lambda: SimpleNamespace(
            telegram_stars_enabled=True,
        ),
    )

    callback = FakeCallback(
        "select_stars:period_1_month"
    )

    await stars_handler.select_stars_payment_callback(
        callback,
        object(),
    )

    assert len(callback.message.invoice_calls) == 1

    invoice_call = callback.message.invoice_calls[0]

    assert invoice_call["title"] == "VPN — 33 days"
    assert invoice_call["currency"] == "XTR"
    assert invoice_call["payload"] == (
        "vpn_stars:41:123:test-signature"
    )
    assert len(invoice_call["prices"]) == 1
    assert invoice_call["prices"][0].amount == 300

    assert callback.answer_calls == [
        {
            "text": None,
        }
    ]


@pytest.mark.asyncio
async def test_pre_checkout_accepts_valid_query(
    monkeypatch,
):
    monkeypatch.setattr(
        stars_handler,
        "TelegramStarsPaymentService",
        FakeStarsPaymentService,
    )

    query = FakePreCheckoutQuery()

    await stars_handler.telegram_stars_pre_checkout(
        query,
        object(),
    )

    assert query.answer_calls == [
        {
            "ok": True,
            "error_message": None,
        }
    ]


@pytest.mark.asyncio
async def test_select_stars_does_not_create_invoice_when_disabled(
    monkeypatch,
):
    monkeypatch.setattr(
        stars_handler,
        "get_payment_option",
        lambda code: SimpleNamespace(
            code=code,
            is_active=False,
        ),
    )
    monkeypatch.setattr(
        stars_handler,
        "get_settings",
        lambda: SimpleNamespace(
            telegram_stars_enabled=False,
        ),
    )

    callback = FakeCallback(
        "select_stars:period_1_month"
    )

    await stars_handler.select_stars_payment_callback(
        callback,
        object(),
    )

    assert callback.message.invoice_calls == []

    assert callback.answer_calls == [
        {
            "text": (
                "Telegram Stars payments are currently disabled."
            ),
            "show_alert": True,
        }
    ]