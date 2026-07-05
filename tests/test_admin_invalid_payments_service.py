from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.common.enums import CurrencyCode, NetworkCode
from app.payment_core.enums.payment_status import PaymentStatus
from app.services.admin_invalid_payments_service import (
    AdminInvalidPaymentItem,
    AdminInvalidPaymentsService,
)


class FakeExecuteResult:
    def __init__(self, rows) -> None:
        self.rows = rows

    def all(self):
        return self.rows


class FakeSession:
    def __init__(self, *, rows=None) -> None:
        self.rows = rows or []
        self.execute_calls = []

    async def execute(self, stmt):
        self.execute_calls.append(stmt)
        return FakeExecuteResult(self.rows)


def make_payment(
    *,
    payment_id: int = 50,
    amount=Decimal("4.00"),
    currency=CurrencyCode.USDT,
    network=NetworkCode.TRC20,
    txid: str | None = "tx-1",
    created_at=None,
):
    return SimpleNamespace(
        id=payment_id,
        amount=amount,
        currency=currency,
        network=network,
        txid=txid,
        status=PaymentStatus.INVALID,
        created_at=created_at or datetime(2026, 7, 5, 12, 0, tzinfo=timezone.utc),
    )


def make_order(*, order_id: int = 23):
    return SimpleNamespace(id=order_id)


def make_user(
    *,
    user_id: int = 7,
    telegram_id: int = 123456,
    username: str | None = "ivan",
):
    return SimpleNamespace(
        id=user_id,
        telegram_id=telegram_id,
        username=username,
    )


def make_event(
    *,
    event_id: int = 70,
    error_message: str | None = "wrong_network",
):
    return SimpleNamespace(
        id=event_id,
        error_message=error_message,
    )


@pytest.mark.asyncio
async def test_get_last_invalid_payments_returns_empty_list_when_no_rows():
    session = FakeSession(rows=[])
    service = AdminInvalidPaymentsService(session)

    result = await service.get_last_invalid_payments(limit=10)

    assert result == []
    assert len(session.execute_calls) == 1


@pytest.mark.asyncio
async def test_get_last_invalid_payments_maps_full_payment_order_user_and_event_context():
    created_at = datetime(2026, 7, 5, 12, 34, 56, tzinfo=timezone.utc)
    payment = make_payment(
        payment_id=50,
        amount=Decimal("4.25"),
        currency=CurrencyCode.USDT,
        network=NetworkCode.TRC20,
        txid="tx-full",
        created_at=created_at,
    )
    order = make_order(order_id=23)
    user = make_user(user_id=7, telegram_id=123456, username="ivan")
    event = make_event(event_id=70, error_message="wrong amount")
    session = FakeSession(rows=[(payment, order, user, event)])
    service = AdminInvalidPaymentsService(session)

    result = await service.get_last_invalid_payments(limit=5)

    assert result == [
        AdminInvalidPaymentItem(
            payment_id=50,
            order_id=23,
            user_id=7,
            telegram_id=123456,
            username="ivan",
            amount=Decimal("4.25"),
            currency="USDT",
            network="TRC20",
            txid="tx-full",
            reason="wrong amount",
            event_id=70,
            created_at=created_at,
        )
    ]
    assert len(session.execute_calls) == 1


@pytest.mark.asyncio
async def test_get_last_invalid_payments_allows_missing_order_user_and_event_context():
    created_at = datetime(2026, 7, 5, 12, 34, 56, tzinfo=timezone.utc)
    payment = make_payment(
        payment_id=51,
        amount=None,
        currency=None,
        network=None,
        txid=None,
        created_at=created_at,
    )
    session = FakeSession(rows=[(payment, None, None, None)])
    service = AdminInvalidPaymentsService(session)

    result = await service.get_last_invalid_payments(limit=5)

    assert result == [
        AdminInvalidPaymentItem(
            payment_id=51,
            order_id=None,
            user_id=None,
            telegram_id=None,
            username=None,
            amount=None,
            currency=None,
            network=None,
            txid=None,
            reason=None,
            event_id=None,
            created_at=created_at,
        )
    ]
    assert len(session.execute_calls) == 1


def test_enum_to_str_handles_none_enum_and_plain_value():
    assert AdminInvalidPaymentsService._enum_to_str(None) is None
    assert AdminInvalidPaymentsService._enum_to_str(CurrencyCode.USDT) == "USDT"
    assert AdminInvalidPaymentsService._enum_to_str(NetworkCode.TRC20) == "TRC20"
    assert AdminInvalidPaymentsService._enum_to_str("custom") == "custom"