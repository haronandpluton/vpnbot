from __future__ import annotations

from types import SimpleNamespace

import pytest

import app.bot.handlers.payment_check as payment_check_module
from app.bot.handlers.payment_check import check_payment_callback
from app.payment_adapters.cryptobot import CryptoBotAPIError


CALL_LOG: list[tuple[str, int]] = []


class FakeMessage:
    def __init__(self) -> None:
        self.answer_calls: list[dict] = []

    async def answer(self, text: str, **kwargs) -> None:
        self.answer_calls.append({"text": text, **kwargs})


class FakeCallback:
    def __init__(self, *, data: str) -> None:
        self.data = data
        self.message = FakeMessage()
        self.answer_calls: list[dict] = []

    async def answer(self, text: str | None = None, **kwargs) -> None:
        self.answer_calls.append({"text": text, **kwargs})


class FakeCryptoBotPaymentService:
    instances: list["FakeCryptoBotPaymentService"] = []
    error: Exception | None = None

    def __init__(self, session) -> None:
        self.session = session
        self.order_ids: list[int] = []
        self.__class__.instances.append(self)

    async def sync_paid_invoice_and_activate(self, order_id: int) -> None:
        self.order_ids.append(order_id)
        CALL_LOG.append(("sync", order_id))

        if self.__class__.error is not None:
            raise self.__class__.error


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
    FakeCryptoBotPaymentService.instances = []
    FakeCryptoBotPaymentService.error = None
    FakePaymentCheckService.instances = []
    FakePaymentCheckService.result = SimpleNamespace(
        status="waiting_payment",
        error_message=None,
    )
    monkeypatch.setattr(
        payment_check_module,
        "CryptoBotPaymentService",
        FakeCryptoBotPaymentService,
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

    assert callback.answer_calls == [{"text": "Некорректный заказ", "show_alert": True}]
    assert callback.message.answer_calls == []
    assert FakeCryptoBotPaymentService.instances == []
    assert FakePaymentCheckService.instances == []
    assert CALL_LOG == []


@pytest.mark.asyncio
async def test_check_payment_callback_handles_cryptobot_sync_error_without_checking_payment():
    FakeCryptoBotPaymentService.error = CryptoBotAPIError("cryptobot failed")
    callback = FakeCallback(data="check_payment:23")

    await check_payment_callback(callback, session="session")

    assert FakeCryptoBotPaymentService.instances[0].session == "session"
    assert FakeCryptoBotPaymentService.instances[0].order_ids == [23]
    assert FakePaymentCheckService.instances == []
    assert CALL_LOG == [("sync", 23)]
    assert callback.message.answer_calls == [
        {
            "text": (
                "Не удалось проверить оплату через CryptoBot. "
                "Попробуй еще раз через несколько секунд."
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
            "Платеж пока не найден. Если ты уже оплатил, проверь еще раз через несколько секунд.",
        ),
        (
            "activated",
            "Оплата подтверждена. VPN-доступ активирован. Открой раздел «Моя подписка» и нажми «Подключить VPN».",
        ),
        (
            "paid_waiting_activation",
            "Оплата подтверждена. Доступ активируется.",
        ),
        (
            "expired",
            "Срок действия заказа истек. Создай новый заказ.",
        ),
        (
            "late_payment",
            "Платеж найден, но пришел после истечения срока заказа. Нужна ручная проверка.",
        ),
        (
            "activation_failed",
            "Оплата найдена, но активация доступа не завершилась. Нужна ручная проверка.",
        ),
        (
            "unknown",
            "Статус заказа не удалось определить. Обратись в поддержку.",
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

    assert CALL_LOG == [("sync", 23), ("check", 23)]
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
            "Платеж найден, но сумма не совпадает с заказом.",
        ),
        (
            "wrong_network",
            "Платеж найден, но отправлен не в той сети.",
        ),
        (
            "wrong_currency",
            "Платеж найден, но валюта не совпадает с заказом.",
        ),
        (
            "other",
            "Платеж найден, но он некорректный. Обратись в поддержку.",
        ),
        (
            None,
            "Платеж найден, но он некорректный. Обратись в поддержку.",
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

    assert CALL_LOG == [("sync", 23), ("check", 23)]
    assert callback.message.answer_calls == [{"text": expected_text}]
    assert callback.answer_calls == [{"text": None}]