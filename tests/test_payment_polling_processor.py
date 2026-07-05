from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.payment_adapters.base import NormalizedTransaction
from app.payment_polling.processor import PaymentPollingProcessor


class FakeExecuteResult:
    def __init__(self, value=None) -> None:
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class FakeSession:
    def __init__(self, values=None) -> None:
        self.values = list(values or [])
        self.execute_calls = []

    async def execute(self, stmt):
        self.execute_calls.append(stmt)

        if not self.values:
            return FakeExecuteResult(None)

        return FakeExecuteResult(self.values.pop(0))


class FakeActivationService:
    def __init__(self, result=None) -> None:
        self.result = result or (
            SimpleNamespace(id="event"),
            SimpleNamespace(id="payment"),
            SimpleNamespace(id="subscription"),
            "config-uri",
        )
        self.calls: list[dict] = []

    async def process_confirmed_payment_event_and_activate(self, **kwargs):
        self.calls.append(kwargs)
        return self.result


class FakePaymentEventService:
    def __init__(self, *, detected_result=None, invalid_result=None) -> None:
        self.detected_result = detected_result or (
            SimpleNamespace(id="late-event"),
            SimpleNamespace(id="late-payment"),
            SimpleNamespace(id="expired-order"),
        )
        self.invalid_result = invalid_result or (
            SimpleNamespace(id="invalid-event"),
            SimpleNamespace(id="invalid-payment"),
            SimpleNamespace(id="invalid-order"),
        )
        self.detected_calls: list[dict] = []
        self.invalid_calls: list[dict] = []

    async def process_detected_event(self, **kwargs):
        self.detected_calls.append(kwargs)
        return self.detected_result

    async def process_invalid_event(self, **kwargs):
        self.invalid_calls.append(kwargs)
        return self.invalid_result


def make_tx(
    *,
    txid: str = "tx-1",
    amount=Decimal("4.00"),
    currency: str = "USDT",
    network: str = "TRC20",
    provider: str | None = "mock",
    raw_payload=None,
):
    return NormalizedTransaction(
        txid=txid,
        amount=amount,
        currency=currency,
        network=network,
        address_from="wallet-from",
        address_to="wallet-to",
        memo_tag="memo-1",
        confirmations=12,
        provider=provider,
        raw_payload=raw_payload if raw_payload is not None else {"raw": True},
    )


def make_order(*, order_id: int = 23):
    return SimpleNamespace(id=order_id)


def make_processor(
    *,
    late_order=None,
    matching_order=None,
    invalid_amount_order=None,
    invalid_network_order=None,
    invalid_currency_order=None,
    activation_service: FakeActivationService | None = None,
    payment_event_service: FakePaymentEventService | None = None,
):
    processor = PaymentPollingProcessor.__new__(PaymentPollingProcessor)
    processor.session = FakeSession()
    processor.activation_service = activation_service or FakeActivationService()
    processor.payment_event_service = payment_event_service or FakePaymentEventService()
    processor.find_calls: list[str] = []

    async def find_late(tx):
        processor.find_calls.append("late")
        return late_order

    async def find_matching(tx):
        processor.find_calls.append("matching")
        return matching_order

    async def find_invalid_amount(tx):
        processor.find_calls.append("invalid_amount")
        return invalid_amount_order

    async def find_invalid_network(tx):
        processor.find_calls.append("invalid_network")
        return invalid_network_order

    async def find_invalid_currency(tx):
        processor.find_calls.append("invalid_currency")
        return invalid_currency_order

    processor._find_late_matching_order = find_late
    processor._find_matching_order = find_matching
    processor._find_invalid_amount_order = find_invalid_amount
    processor._find_invalid_network_order = find_invalid_network
    processor._find_invalid_currency_order = find_invalid_currency
    return processor


@pytest.mark.asyncio
async def test_process_transaction_handles_late_matching_order_before_active_order_lookup():
    tx = make_tx(provider=None)
    order = make_order(order_id=23)
    payment_event_service = FakePaymentEventService()
    activation_service = FakeActivationService()
    processor = make_processor(
        late_order=order,
        matching_order=make_order(order_id=99),
        activation_service=activation_service,
        payment_event_service=payment_event_service,
    )

    result = await processor.process_transaction(tx)

    assert result == (
        payment_event_service.detected_result[0],
        payment_event_service.detected_result[1],
        None,
        None,
    )
    assert processor.find_calls == ["late"]
    assert activation_service.calls == []
    assert payment_event_service.invalid_calls == []
    assert payment_event_service.detected_calls == [
        {
            "order_id": 23,
            "amount": Decimal("4.00"),
            "provider": "unknown",
            "event_type": "payment_late",
            "external_event_id": "tx-1",
            "txid": "tx-1",
            "address_from": "wallet-from",
            "address_to": "wallet-to",
            "memo_tag": "memo-1",
            "confirmations": 12,
            "raw_payload": "{'raw': True}",
        }
    ]


@pytest.mark.asyncio
async def test_process_transaction_activates_exact_matching_order():
    tx = make_tx(txid="tx-confirmed", provider="volet")
    order = make_order(order_id=23)
    activation_service = FakeActivationService()
    payment_event_service = FakePaymentEventService()
    processor = make_processor(
        matching_order=order,
        activation_service=activation_service,
        payment_event_service=payment_event_service,
    )

    result = await processor.process_transaction(tx)

    assert result == activation_service.result
    assert processor.find_calls == ["late", "matching"]
    assert payment_event_service.detected_calls == []
    assert payment_event_service.invalid_calls == []
    assert activation_service.calls == [
        {
            "order_id": 23,
            "amount": Decimal("4.00"),
            "provider": "volet",
            "event_type": "payment_confirmed",
            "external_event_id": "tx-confirmed",
            "txid": "tx-confirmed",
            "address_from": "wallet-from",
            "address_to": "wallet-to",
            "memo_tag": "memo-1",
            "confirmations": 12,
            "raw_payload": "{'raw': True}",
        }
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field_name", "reason"),
    [
        ("invalid_amount_order", "wrong_amount"),
        ("invalid_network_order", "wrong_network"),
        ("invalid_currency_order", "wrong_currency"),
    ],
)
async def test_process_transaction_routes_invalid_transactions_to_payment_event_service(
    field_name,
    reason,
):
    tx = make_tx(txid=f"tx-{reason}", raw_payload={"reason": reason})
    order = make_order(order_id=23)
    payment_event_service = FakePaymentEventService()
    kwargs = {field_name: order}
    processor = make_processor(
        payment_event_service=payment_event_service,
        **kwargs,
    )

    result = await processor.process_transaction(tx)

    assert result == (
        payment_event_service.invalid_result[0],
        payment_event_service.invalid_result[1],
        None,
        None,
    )
    assert payment_event_service.detected_calls == []
    assert payment_event_service.invalid_calls == [
        {
            "order_id": 23,
            "amount": Decimal("4.00"),
            "currency": "USDT",
            "network": "TRC20",
            "provider": "mock",
            "event_type": "payment_invalid",
            "reason": reason,
            "external_event_id": f"tx-{reason}",
            "txid": f"tx-{reason}",
            "address_from": "wallet-from",
            "address_to": "wallet-to",
            "memo_tag": "memo-1",
            "confirmations": 12,
            "raw_payload": "{'reason': '" + reason + "'}",
        }
    ]

    if reason == "wrong_amount":
        assert processor.find_calls == ["late", "matching", "invalid_amount"]
    elif reason == "wrong_network":
        assert processor.find_calls == [
            "late",
            "matching",
            "invalid_amount",
            "invalid_network",
        ]
    else:
        assert processor.find_calls == [
            "late",
            "matching",
            "invalid_amount",
            "invalid_network",
            "invalid_currency",
        ]


@pytest.mark.asyncio
async def test_process_transaction_returns_none_when_order_is_not_found():
    tx = make_tx(txid="tx-no-match")
    activation_service = FakeActivationService()
    payment_event_service = FakePaymentEventService()
    processor = make_processor(
        activation_service=activation_service,
        payment_event_service=payment_event_service,
    )

    result = await processor.process_transaction(tx)

    assert result is None
    assert processor.find_calls == [
        "late",
        "matching",
        "invalid_amount",
        "invalid_network",
        "invalid_currency",
    ]
    assert activation_service.calls == []
    assert payment_event_service.detected_calls == []
    assert payment_event_service.invalid_calls == []


@pytest.mark.asyncio
async def test_process_transactions_filters_none_results_and_keeps_processed_results():
    tx_1 = make_tx(txid="tx-1")
    tx_2 = make_tx(txid="tx-2")
    tx_3 = make_tx(txid="tx-3")
    processor = PaymentPollingProcessor.__new__(PaymentPollingProcessor)
    processor.calls: list[str] = []

    async def fake_process_transaction(tx):
        processor.calls.append(tx.txid)

        if tx.txid == "tx-2":
            return None

        return f"processed-{tx.txid}"

    processor.process_transaction = fake_process_transaction

    result = await processor.process_transactions([tx_1, tx_2, tx_3])

    assert result == ["processed-tx-1", "processed-tx-3"]
    assert processor.calls == ["tx-1", "tx-2", "tx-3"]


@pytest.mark.asyncio
async def test_find_late_matching_order_returns_scalar_order_from_single_query():
    order = make_order(order_id=23)
    session = FakeSession(values=[order])
    processor = PaymentPollingProcessor.__new__(PaymentPollingProcessor)
    processor.session = session

    result = await processor._find_late_matching_order(make_tx())

    assert result is order
    assert len(session.execute_calls) == 1


@pytest.mark.asyncio
async def test_find_matching_order_returns_exact_match_without_fallback_query():
    order = make_order(order_id=23)
    session = FakeSession(values=[order])
    processor = PaymentPollingProcessor.__new__(PaymentPollingProcessor)
    processor.session = session

    result = await processor._find_matching_order(make_tx())

    assert result is order
    assert len(session.execute_calls) == 1


@pytest.mark.asyncio
async def test_find_matching_order_uses_price_fallback_when_expected_amount_is_missing():
    fallback_order = make_order(order_id=24)
    session = FakeSession(values=[None, fallback_order])
    processor = PaymentPollingProcessor.__new__(PaymentPollingProcessor)
    processor.session = session

    result = await processor._find_matching_order(make_tx())

    assert result is fallback_order
    assert len(session.execute_calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method_name",
    [
        "_find_invalid_amount_order",
        "_find_invalid_network_order",
        "_find_invalid_currency_order",
    ],
)
async def test_invalid_order_lookup_helpers_return_scalar_order_from_single_query(method_name):
    order = make_order(order_id=23)
    session = FakeSession(values=[order])
    processor = PaymentPollingProcessor.__new__(PaymentPollingProcessor)
    processor.session = session

    result = await getattr(processor, method_name)(make_tx())

    assert result is order
    assert len(session.execute_calls) == 1