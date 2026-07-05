from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest

import app.bot.handlers.dev_payment as dev_payment_module
from app.bot.handlers.dev_payment import dev_confirm_payment_callback
from app.common.enums import CurrencyCode, NetworkCode
from app.payment_core.enums.order_status import OrderStatus


class FakeExecuteResult:
    def __init__(self, value=None) -> None:
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class FakeSession:
    def __init__(self, *, order=None) -> None:
        self.order = order
        self.execute_calls = []
        self.commit_count = 0

    async def execute(self, stmt):
        self.execute_calls.append(stmt)
        return FakeExecuteResult(self.order)

    async def commit(self) -> None:
        self.commit_count += 1


class FakeMessage:
    def __init__(self) -> None:
        self.answer_calls: list[dict] = []

    async def answer(self, text: str, **kwargs) -> None:
        self.answer_calls.append({"text": text, **kwargs})


class FakeCallback:
    def __init__(self, *, data: str, telegram_id: int = 123) -> None:
        self.data = data
        self.from_user = SimpleNamespace(id=telegram_id)
        self.message = FakeMessage()
        self.answer_calls: list[dict] = []

    async def answer(self, text: str | None = None, **kwargs) -> None:
        self.answer_calls.append({"text": text, **kwargs})


class FakeProcessor:
    instances: list["FakeProcessor"] = []
    result = None

    def __init__(self, session) -> None:
        self.session = session
        self.transactions = []
        self.__class__.instances.append(self)

    async def process_transaction(self, tx):
        self.transactions.append(tx)
        return self.__class__.result


def make_order(**overrides):
    values = {
        "id": 23,
        "status": OrderStatus.WAITING_PAYMENT,
        "destination_address": "receiver-wallet",
        "expected_amount": Decimal("4.00"),
        "price_usd": Decimal("4.00"),
        "expected_currency": CurrencyCode.USDT,
        "expected_network": NetworkCode.TRC20,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.fixture(autouse=True)
def patch_processor(monkeypatch):
    FakeProcessor.instances = []
    FakeProcessor.result = (
        SimpleNamespace(id=101),
        SimpleNamespace(id=202),
        SimpleNamespace(id=303),
        "config-uri",
    )
    monkeypatch.setattr(dev_payment_module, "PaymentPollingProcessor", FakeProcessor)
    monkeypatch.setattr(
        dev_payment_module,
        "_model_id",
        lambda obj: None if obj is None else getattr(obj, "id", None),
    )


@pytest.mark.asyncio
async def test_dev_confirm_payment_rejects_malformed_order_id_before_database_query():
    session = FakeSession(order=make_order())
    callback = FakeCallback(data="dev_confirm_payment:abc")

    await dev_confirm_payment_callback(callback, session=session)

    assert callback.answer_calls == [{"text": "Некорректный заказ", "show_alert": True}]
    assert callback.message.answer_calls == []
    assert session.execute_calls == []
    assert FakeProcessor.instances == []


@pytest.mark.asyncio
async def test_dev_confirm_payment_rejects_missing_order_before_processor():
    session = FakeSession(order=None)
    callback = FakeCallback(data="dev_confirm_payment:23")

    await dev_confirm_payment_callback(callback, session=session)

    assert len(session.execute_calls) == 1
    assert callback.answer_calls == [{"text": "Заказ не найден", "show_alert": True}]
    assert callback.message.answer_calls == []
    assert FakeProcessor.instances == []


@pytest.mark.asyncio
async def test_dev_confirm_payment_for_already_activated_order_sends_subscription_hint():
    session = FakeSession(order=make_order(status=OrderStatus.ACTIVATED))
    callback = FakeCallback(data="dev_confirm_payment:23")

    await dev_confirm_payment_callback(callback, session=session)

    assert callback.message.answer_calls == [
        {
            "text": (
                "Заказ уже активирован.\n\n"
                "Отправь команду /my_subscription, чтобы получить конфиг."
            )
        }
    ]
    assert callback.answer_calls == [{"text": None}]
    assert FakeProcessor.instances == []


@pytest.mark.asyncio
async def test_dev_confirm_payment_rejects_non_waiting_order_with_current_status_text():
    session = FakeSession(order=make_order(status=OrderStatus.EXPIRED))
    callback = FakeCallback(data="dev_confirm_payment:23")

    await dev_confirm_payment_callback(callback, session=session)

    assert callback.message.answer_calls == [
        {
            "text": (
                "Mock-подтверждение доступно только для заказа в статусе waiting_payment.\n\n"
                "Текущий статус заказа: expired"
            )
        }
    ]
    assert callback.answer_calls == [{"text": None}]
    assert FakeProcessor.instances == []


@pytest.mark.asyncio
async def test_dev_confirm_payment_sets_mock_destination_when_missing_and_commits_before_processing():
    order = make_order(destination_address=None)
    session = FakeSession(order=order)
    callback = FakeCallback(data="dev_confirm_payment:23", telegram_id=777)

    await dev_confirm_payment_callback(callback, session=session)

    assert order.destination_address == "dev_mock_receiver_order_23"
    assert session.commit_count == 1

    processor = FakeProcessor.instances[0]
    tx = processor.transactions[0]

    assert tx.txid == "dev_confirm_txid_order_23"
    assert tx.amount == Decimal("4.00")
    assert tx.currency == "USDT"
    assert tx.network == "TRC20"
    assert tx.address_from == "dev_mock_sender_wallet"
    assert tx.address_to == "dev_mock_receiver_order_23"
    assert tx.confirmations == 3
    assert tx.provider == "mock"
    assert tx.raw_payload == {
        "source": "dev_confirm_payment_callback",
        "order_id": 23,
        "telegram_id": 777,
        "amount": "4.00",
        "currency": "USDT",
        "network": "TRC20",
    }


@pytest.mark.asyncio
async def test_dev_confirm_payment_uses_price_usd_when_expected_amount_is_missing():
    order = make_order(expected_amount=None, price_usd=Decimal("7.00"))
    session = FakeSession(order=order)
    callback = FakeCallback(data="dev_confirm_payment:23")

    await dev_confirm_payment_callback(callback, session=session)

    tx = FakeProcessor.instances[0].transactions[0]
    assert tx.amount == Decimal("7.00")
    assert tx.raw_payload["amount"] == "7.00"
    assert session.commit_count == 0


@pytest.mark.asyncio
async def test_dev_confirm_payment_reports_when_processor_does_not_match_created_transaction():
    FakeProcessor.result = None
    session = FakeSession(order=make_order())
    callback = FakeCallback(data="dev_confirm_payment:23")

    await dev_confirm_payment_callback(callback, session=session)

    assert callback.message.answer_calls == [
        {
            "text": (
                "Mock-транзакция создана, но заказ не был найден processor-ом.\n\n"
                "Проверь expected_amount / currency / network / destination_address."
            )
        }
    ]
    assert callback.answer_calls == [{"text": None}]


@pytest.mark.asyncio
async def test_dev_confirm_payment_reports_processed_payment_without_subscription_activation():
    FakeProcessor.result = (
        SimpleNamespace(id=101),
        SimpleNamespace(id=202),
        None,
        None,
    )
    session = FakeSession(order=make_order())
    callback = FakeCallback(data="dev_confirm_payment:23")

    await dev_confirm_payment_callback(callback, session=session)

    assert callback.message.answer_calls == [
        {
            "text": (
                "Mock-платеж обработан, но подписка не была активирована.\n\n"
                "Event ID: 101\n"
                "Payment ID: 202\n\n"
                "Проверь логи processor-а."
            )
        }
    ]
    assert callback.answer_calls == [{"text": None}]


@pytest.mark.asyncio
async def test_dev_confirm_payment_success_sends_ids_and_my_subscription_hint():
    session = FakeSession(order=make_order())
    callback = FakeCallback(data="dev_confirm_payment:23")

    await dev_confirm_payment_callback(callback, session=session)

    assert callback.message.answer_calls == [
        {
            "text": (
                "DEV mock-платеж подтвержден.\n\n"
                "Order ID: 23\n"
                "Payment ID: 202\n"
                "Event ID: 101\n"
                "Subscription ID: 303\n\n"
                "VPN-доступ активирован.\n\n"
                "Теперь можно отправить:\n"
                "/my_subscription"
            )
        }
    ]
    assert callback.answer_calls == [{"text": None}]