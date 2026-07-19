from __future__ import annotations

from types import SimpleNamespace

import pytest

import app.bot.handlers.payment_check as payment_check_module
from app.bot.handlers.payment_check import check_payment_callback
from app.payment_adapters.cryptobot import CryptoBotAPIError
from app.services.cryptobot_payment_notification_service import (
    CRYPTOBOT_PAYMENT_CONFIRMED_TEXT,
)


CALL_LOG: list[tuple[str, int]] = []


class FakeMessage:
    def __init__(self) -> None:
        self.answer_calls: list[dict] = []

    async def answer(self, text: str, **kwargs) -> None:
        self.answer_calls.append({"text": text, **kwargs})


class FakeCallback:
    def __init__(self, *, data: str, telegram_id: int = 123) -> None:
        self.data = data
        self.message = FakeMessage()
        self.from_user = SimpleNamespace(id=telegram_id)
        self.answer_calls: list[dict] = []

    async def answer(self, text: str | None = None, **kwargs) -> None:
        self.answer_calls.append({"text": text, **kwargs})


class FakeOrderService:
    instances: list["FakeOrderService"] = []
    order = SimpleNamespace(id=23, user_id=1)

    def __init__(self, session) -> None:
        self.session = session
        self.calls: list[dict] = []
        self.__class__.instances.append(self)

    async def get_order_for_telegram_user(self, **kwargs):
        self.calls.append(kwargs)
        CALL_LOG.append(("owner", kwargs["order_id"]))
        return self.__class__.order


class FakeCryptoBotPaymentService:
    instances: list["FakeCryptoBotPaymentService"] = []
    error: Exception | None = None
    result = None

    def __init__(self, session) -> None:
        self.session = session
        self.order_ids: list[int] = []
        self.__class__.instances.append(self)

    async def sync_paid_invoice_and_activate(self, order_id: int):
        self.order_ids.append(order_id)
        CALL_LOG.append(("sync", order_id))

        if self.__class__.error is not None:
            raise self.__class__.error

        return self.__class__.result


class FakeCryptoBotPaymentNotificationService:
    instances: list["FakeCryptoBotPaymentNotificationService"] = []
    result = SimpleNamespace(
        attempted=True,
        delivered=True,
        persisted=True,
        reason=None,
    )
    error: Exception | None = None

    def __init__(self, session) -> None:
        self.session = session
        self.calls: list[dict] = []
        self.__class__.instances.append(self)

    async def deliver(
        self,
        *,
        event_id: int,
        order_id: int,
        telegram_id: int,
        send_message,
    ):
        self.calls.append(
            {
                "event_id": event_id,
                "order_id": order_id,
                "telegram_id": telegram_id,
            }
        )
        CALL_LOG.append(("notify", event_id))

        if self.__class__.error is not None:
            raise self.__class__.error

        if self.__class__.result.delivered:
            await send_message(CRYPTOBOT_PAYMENT_CONFIRMED_TEXT)

        return self.__class__.result


class FakePaymentCheckService:
    instances: list["FakePaymentCheckService"] = []
    result = SimpleNamespace(status="waiting_payment", error_message=None)

    def __init__(self, session) -> None:
        self.session = session
        self.order_ids: list[int] = []
        self.__class__.instances.append(self)

    async def check_order_payment(self, order_id: int):
        self.order_ids.append(order_id)
        CALL_LOG.append(("check", order_id))
        return self.__class__.result


@pytest.fixture(autouse=True)
def patch_services(monkeypatch):
    CALL_LOG.clear()
    FakeOrderService.instances = []
    FakeOrderService.order = SimpleNamespace(id=23, user_id=1)
    FakeCryptoBotPaymentService.instances = []
    FakeCryptoBotPaymentService.error = None
    FakeCryptoBotPaymentService.result = None
    FakeCryptoBotPaymentNotificationService.instances = []
    FakeCryptoBotPaymentNotificationService.result = SimpleNamespace(
        attempted=True,
        delivered=True,
        persisted=True,
        reason=None,
    )
    FakeCryptoBotPaymentNotificationService.error = None
    FakePaymentCheckService.instances = []
    FakePaymentCheckService.result = SimpleNamespace(
        status="waiting_payment",
        error_message=None,
    )
    monkeypatch.setattr(
        payment_check_module,
        "OrderService",
        FakeOrderService,
    )
    monkeypatch.setattr(
        payment_check_module,
        "CryptoBotPaymentService",
        FakeCryptoBotPaymentService,
    )
    monkeypatch.setattr(
        payment_check_module,
        "CryptoBotPaymentNotificationService",
        FakeCryptoBotPaymentNotificationService,
    )
    monkeypatch.setattr(
        payment_check_module,
        "PaymentCheckService",
        FakePaymentCheckService,
    )


@pytest.mark.asyncio
async def test_check_payment_callback_rejects_malformed_order_id_before_services():
    callback = FakeCallback(data="check_payment:abc")

    await check_payment_callback(callback, session="session")

    assert callback.answer_calls == [{"text": "Invalid order", "show_alert": True}]
    assert callback.message.answer_calls == []
    assert FakeOrderService.instances == []
    assert FakeCryptoBotPaymentService.instances == []
    assert FakePaymentCheckService.instances == []
    assert CALL_LOG == []


@pytest.mark.asyncio
async def test_check_payment_callback_rejects_foreign_order_before_provider_call():
    FakeOrderService.order = None
    callback = FakeCallback(data="check_payment:23", telegram_id=999)

    await check_payment_callback(callback, session="session")

    assert FakeOrderService.instances[0].calls == [{"order_id": 23, "telegram_id": 999}]
    assert FakeCryptoBotPaymentService.instances == []
    assert FakePaymentCheckService.instances == []
    assert CALL_LOG == [("owner", 23)]
    assert callback.answer_calls == [{"text": "Order not found", "show_alert": True}]


@pytest.mark.asyncio
async def test_check_payment_callback_handles_cryptobot_sync_error_without_checking_payment():
    FakeCryptoBotPaymentService.error = CryptoBotAPIError("cryptobot failed")
    callback = FakeCallback(data="check_payment:23")

    await check_payment_callback(callback, session="session")

    assert FakeCryptoBotPaymentService.instances[0].session == "session"
    assert FakeCryptoBotPaymentService.instances[0].order_ids == [23]
    assert FakePaymentCheckService.instances == []
    assert CALL_LOG == [("owner", 23), ("sync", 23)]
    assert callback.message.answer_calls == [
        {
            "text": (
                "Could not check the payment through CryptoBot. "
                "Try again in a few seconds."
            )
        }
    ]
    assert callback.answer_calls == [{"text": None}]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "expected_text"),
    [
        (
            "waiting_payment",
            "Payment has not been found yet. If you have already paid, check again in a few seconds.",
        ),
        (
            "paid_waiting_activation",
            "Payment confirmed. Access is being activated.",
        ),
        (
            "expired",
            "The order has expired. Create a new order.",
        ),
        (
            "late_payment",
            "Payment found, but it arrived after the order expired. Manual review is required.",
        ),
        (
            "activation_failed",
            "Payment found, but access activation was not completed. Manual review is required.",
        ),
        (
            "unknown",
            "Could not determine the order status. Contact support.",
        ),
    ],
)
async def test_check_payment_callback_sends_clear_text_for_payment_statuses(
    status,
    expected_text,
):
    FakePaymentCheckService.result = SimpleNamespace(status=status, error_message=None)
    callback = FakeCallback(data="check_payment:23")

    await check_payment_callback(callback, session="session")

    assert CALL_LOG == [("owner", 23), ("sync", 23), ("check", 23)]
    assert FakeCryptoBotPaymentService.instances[0].session == "session"
    assert FakePaymentCheckService.instances[0].session == "session"
    assert callback.message.answer_calls == [{"text": expected_text}]
    assert callback.answer_calls == [{"text": None}]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("reason", "expected_text"),
    [
        (
            "wrong_amount",
            "Payment found, but the amount does not match the order.",
        ),
        (
            "wrong_network",
            "Payment found, but it was sent through the wrong network.",
        ),
        (
            "wrong_currency",
            "Payment found, but the currency does not match the order.",
        ),
        (
            "other",
            "Payment found, but it is invalid. Contact support.",
        ),
        (
            None,
            "Payment found, but it is invalid. Contact support.",
        ),
    ],
)
async def test_check_payment_callback_sends_specific_invalid_payment_reason(
    reason,
    expected_text,
):
    FakePaymentCheckService.result = SimpleNamespace(
        status="invalid_payment",
        error_message=reason,
    )
    callback = FakeCallback(data="check_payment:23")

    await check_payment_callback(callback, session="session")

    assert CALL_LOG == [("owner", 23), ("sync", 23), ("check", 23)]
    assert callback.message.answer_calls == [{"text": expected_text}]
    assert callback.answer_calls == [{"text": None}]


@pytest.mark.asyncio
async def test_activated_payment_uses_idempotent_notification_service():
    FakeCryptoBotPaymentService.result = {
        "event": SimpleNamespace(id=70),
    }
    FakePaymentCheckService.result = SimpleNamespace(
        status="activated",
        error_message=None,
        event_id=999,
    )
    callback = FakeCallback(
        data="check_payment:23",
        telegram_id=123456789,
    )

    await check_payment_callback(callback, session="session")

    assert CALL_LOG == [
        ("owner", 23),
        ("sync", 23),
        ("check", 23),
        ("notify", 70),
    ]

    notification_service = (
        FakeCryptoBotPaymentNotificationService.instances[0]
    )
    assert notification_service.session == "session"
    assert notification_service.calls == [
        {
            "event_id": 70,
            "order_id": 23,
            "telegram_id": 123456789,
        }
    ]

    assert callback.message.answer_calls == [
        {"text": CRYPTOBOT_PAYMENT_CONFIRMED_TEXT}
    ]
    assert callback.answer_calls == [{"text": None}]


@pytest.mark.asyncio
async def test_activated_payment_does_not_duplicate_scheduler_notification():
    FakePaymentCheckService.result = SimpleNamespace(
        status="activated",
        error_message=None,
        event_id=70,
    )
    FakeCryptoBotPaymentNotificationService.result = SimpleNamespace(
        attempted=False,
        delivered=False,
        persisted=False,
        reason="not_claimed",
    )
    callback = FakeCallback(data="check_payment:23")

    await check_payment_callback(callback, session="session")

    assert callback.message.answer_calls == []
    assert callback.answer_calls == [
        {
            "text": "Payment confirmed. VPN access is active.",
            "show_alert": False,
        }
    ]


@pytest.mark.asyncio
async def test_activated_payment_reports_delivery_failure_without_duplicate_message():
    FakePaymentCheckService.result = SimpleNamespace(
        status="activated",
        error_message=None,
        event_id=70,
    )
    FakeCryptoBotPaymentNotificationService.result = SimpleNamespace(
        attempted=True,
        delivered=False,
        persisted=False,
        reason="send_failed",
    )
    callback = FakeCallback(data="check_payment:23")

    await check_payment_callback(callback, session="session")

    assert callback.message.answer_calls == []
    assert callback.answer_calls == [
        {
            "text": "Payment confirmed. VPN access is active.",
            "show_alert": True,
        }
    ]


@pytest.mark.asyncio
async def test_activated_payment_handles_notification_database_error():
    FakePaymentCheckService.result = SimpleNamespace(
        status="activated",
        error_message=None,
        event_id=70,
    )
    FakeCryptoBotPaymentNotificationService.error = RuntimeError(
        "database unavailable"
    )
    callback = FakeCallback(data="check_payment:23")

    await check_payment_callback(callback, session="session")

    assert callback.message.answer_calls == []
    assert callback.answer_calls == [
        {
            "text": "Payment confirmed. VPN access is active.",
            "show_alert": True,
        }
    ]


@pytest.mark.asyncio
async def test_activated_payment_without_event_uses_alert_only():
    FakeCryptoBotPaymentService.result = None
    FakePaymentCheckService.result = SimpleNamespace(
        status="activated",
        error_message=None,
        event_id=None,
    )
    callback = FakeCallback(data="check_payment:23")

    await check_payment_callback(callback, session="session")

    assert FakeCryptoBotPaymentNotificationService.instances == []
    assert callback.message.answer_calls == []
    assert callback.answer_calls == [
        {
            "text": "Payment confirmed. VPN access is active.",
            "show_alert": True,
        }
    ]
