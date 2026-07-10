from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

import app.bot.handlers.dev_subscription as dev_subscription_module
import app.bot.handlers.test_payment_check as test_payment_check_module
from app.bot.handlers.dev_subscription import dev_create_active_subscription_command
from app.bot.handlers.test_payment_check import (
    test_payment_check_command as payment_check_test_command,
)
from app.common.enums import TariffCode


CALL_LOG: list[str] = []


class FakeMessage:
    def __init__(self, *, telegram_id: int = 123) -> None:
        self.from_user = SimpleNamespace(
            id=telegram_id,
            username="ivan",
            first_name="Ivan",
            last_name="Redeemer",
            language_code="ru",
        )
        self.answer_calls: list[dict] = []

    async def answer(self, text: str, **kwargs) -> None:
        self.answer_calls.append({"text": text, **kwargs})
        CALL_LOG.append(f"answer:{text.splitlines()[0] if text else ''}")


class FakeSession:
    def __init__(self) -> None:
        self.commit_count = 0

    async def commit(self) -> None:
        self.commit_count += 1
        CALL_LOG.append("commit")


class FakeOrderService:
    instances: list["FakeOrderService"] = []
    order = None

    def __init__(self, session) -> None:
        self.session = session
        self.create_order_calls: list[dict] = []
        self.__class__.instances.append(self)

    async def create_order(self, **kwargs):
        self.create_order_calls.append(kwargs)
        CALL_LOG.append("create_order")
        return self.__class__.order


class FakePaymentPollingProcessor:
    instances: list["FakePaymentPollingProcessor"] = []
    result = None

    def __init__(self, session) -> None:
        self.session = session
        self.transactions = []
        self.__class__.instances.append(self)

    async def process_transaction(self, tx):
        self.transactions.append(tx)
        CALL_LOG.append("process_transaction")
        return self.__class__.result


def make_order(*, order_id: int = 23):
    return SimpleNamespace(
        id=order_id,
        expected_amount=None,
        expected_currency=None,
        expected_network=None,
        destination_address=None,
    )


def row_callbacks(markup):
    return [[button.callback_data for button in row] for row in markup.inline_keyboard]


@pytest.fixture(autouse=True)
def patch_dependencies(monkeypatch):
    CALL_LOG.clear()
    FakeOrderService.instances = []
    FakeOrderService.order = make_order()
    FakePaymentPollingProcessor.instances = []
    FakePaymentPollingProcessor.result = (
        SimpleNamespace(id=101),
        SimpleNamespace(id=202),
        SimpleNamespace(
            id=303,
            device_limit=1,
            expires_at=datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc),
        ),
        "config-uri",
    )
    monkeypatch.setattr(dev_subscription_module, "OrderService", FakeOrderService)
    monkeypatch.setattr(
        dev_subscription_module,
        "PaymentPollingProcessor",
        FakePaymentPollingProcessor,
    )
    monkeypatch.setattr(test_payment_check_module, "OrderService", FakeOrderService)


@pytest.mark.asyncio
async def test_dev_create_active_subscription_sends_initial_progress_message_before_order_creation():
    session = FakeSession()
    message = FakeMessage(telegram_id=777)

    await dev_create_active_subscription_command(message, session=session)

    assert CALL_LOG[0] == "answer:Dev-команда получена. Создаю подписку..."
    assert CALL_LOG[1] == "create_order"
    assert message.answer_calls[0] == {
        "text": "Dev-команда получена. Создаю подписку..."
    }


@pytest.mark.asyncio
async def test_dev_create_active_subscription_creates_devices_1_usdt_order_for_message_user():
    session = FakeSession()
    message = FakeMessage(telegram_id=777)

    await dev_create_active_subscription_command(message, session=session)

    service = FakeOrderService.instances[0]
    assert service.session is session
    assert service.create_order_calls == [
        {
            "telegram_id": 777,
            "tariff_code": TariffCode.DEVICES_1,
            "payment_option_code": "usdt_trc20",
            "username": "ivan",
            "first_name": "Ivan",
            "last_name": "Redeemer",
            "language_code": "ru",
        }
    ]


@pytest.mark.asyncio
async def test_dev_create_active_subscription_mutates_order_commits_and_processes_mock_transaction():
    order = make_order(order_id=23)
    FakeOrderService.order = order
    session = FakeSession()
    message = FakeMessage(telegram_id=777)

    await dev_create_active_subscription_command(message, session=session)

    assert order.expected_amount == Decimal("4.00")
    assert order.expected_currency == "USDT"
    assert order.expected_network == "TRC20"
    assert order.destination_address == "dev_active_receiver_23"
    assert session.commit_count == 1
    assert CALL_LOG.index("commit") < CALL_LOG.index("process_transaction")

    processor = FakePaymentPollingProcessor.instances[0]
    assert processor.session is session
    tx = processor.transactions[0]
    assert tx.txid == "dev_active_txid_23"
    assert tx.amount == Decimal("4.00")
    assert tx.currency == "USDT"
    assert tx.network == "TRC20"
    assert tx.address_from == "dev_mock_sender_wallet"
    assert tx.address_to == "dev_active_receiver_23"
    assert tx.confirmations == 3
    assert tx.provider == "mock"
    assert tx.raw_payload == {
        "source": "dev_create_active_subscription",
        "order_id": 23,
        "telegram_id": 777,
    }


@pytest.mark.asyncio
async def test_dev_create_active_subscription_sends_activation_summary_and_vpn_keyboard():
    session = FakeSession()
    message = FakeMessage(telegram_id=777)

    await dev_create_active_subscription_command(message, session=session)

    assert message.answer_calls[1] == {
        "text": (
            "Dev-подписка создана и активирована.\n\n"
            "Order ID: 23\n"
            "Payment ID: 202\n"
            "Event ID: 101\n"
            "Subscription ID: 303\n\n"
            "Теперь отправь команду:\n"
            "/my_subscription"
        )
    }
    assert "Your VPN subscription is active." in message.answer_calls[2]["text"]
    assert "Devices: 1" in message.answer_calls[2]["text"]
    assert "Active until: 01.08.2026 12:00" in message.answer_calls[2]["text"]
    assert row_callbacks(message.answer_calls[2]["reply_markup"]) == [
        ["vpn_access:show_config:303"],
        ["vpn_access:show_config:303"],
        ["renew_subscription:303"],
        ["buy_vpn"],
        ["vpn_access:happ_android", "vpn_access:happ_ios"],
        ["vpn_access:happ_fallback"],
    ]


@pytest.mark.asyncio
async def test_test_payment_check_command_creates_test_order_and_commits():
    order = make_order(order_id=55)
    FakeOrderService.order = order
    session = FakeSession()
    message = FakeMessage(telegram_id=777)

    await payment_check_test_command(message, session=session)

    service = FakeOrderService.instances[0]
    assert service.session is session
    assert service.create_order_calls == [
        {
            "telegram_id": 777,
            "tariff_code": TariffCode.DEVICES_1,
            "payment_option_code": "usdt_trc20",
            "username": "ivan",
            "first_name": "Ivan",
            "last_name": "Redeemer",
            "language_code": "ru",
        }
    ]
    assert order.expected_amount == Decimal("4.00")
    assert order.expected_currency == "USDT"
    assert order.expected_network == "TRC20"
    assert order.destination_address == "test_receiver_order_55"
    assert session.commit_count == 1


@pytest.mark.asyncio
async def test_test_payment_check_command_sends_payment_check_keyboard():
    order = make_order(order_id=55)
    FakeOrderService.order = order
    session = FakeSession()
    message = FakeMessage(telegram_id=777)

    await payment_check_test_command(message, session=session)

    assert message.answer_calls[0]["text"] == (
        "Тестовый заказ создан.\n\n"
        "Order ID: 55\n"
        "Сумма: 4.00 USDT\n"
        "Сеть: TRC20\n\n"
        "Нажми кнопку ниже, чтобы проверить payment check handler."
    )
    assert row_callbacks(message.answer_calls[0]["reply_markup"]) == [
        ["check_payment:55"],
        ["dev_confirm_payment:55"],
    ]
