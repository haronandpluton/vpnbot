from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest

from app.common.enums import CurrencyCode, NetworkCode, TariffCode
from app.database.models import Order
from app.database.repositories.orders import OrderRepository
from app.payment_core.enums.payment_method import PaymentMethod


class FakeResult:
    def __init__(self, value=None) -> None:
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class FakeSession:
    def __init__(self, result=None) -> None:
        self.result = result
        self.execute_calls = []
        self.add_calls = []
        self.flush_count = 0

    async def execute(self, stmt):
        self.execute_calls.append(stmt)
        return FakeResult(self.result)

    def add(self, obj) -> None:
        self.add_calls.append(obj)

    async def flush(self) -> None:
        self.flush_count += 1
        for obj in self.add_calls:
            if getattr(obj, "id", None) is None:
                obj.id = 900


@pytest.mark.asyncio
async def test_waiting_new_purchase_query_requires_null_target_subscription():
    session = FakeSession()
    repository = OrderRepository(cast(Any, session))

    await repository.get_active_waiting_order_by_user(
        user_id=7,
        tariff_code=TariffCode.PERIOD_1_MONTH,
        payment_option_id=5,
    )

    assert "orders.target_subscription_id IS NULL" in str(session.execute_calls[0])


@pytest.mark.asyncio
async def test_waiting_renewal_query_is_scoped_to_target_subscription():
    session = FakeSession()
    repository = OrderRepository(cast(Any, session))

    await repository.get_active_waiting_order_by_user(
        user_id=7,
        tariff_code=TariffCode.PERIOD_1_MONTH,
        payment_option_id=5,
        target_subscription_id=50,
    )

    stmt = session.execute_calls[0]
    assert "orders.target_subscription_id =" in str(stmt)
    assert 50 in stmt.compile().params.values()


@pytest.mark.asyncio
async def test_create_order_persists_target_and_leaves_activation_result_empty():
    session = FakeSession()
    repository = OrderRepository(cast(Any, session))

    order = await repository.create(
        user_id=7,
        tariff_code=TariffCode.PERIOD_2_MONTHS,
        device_limit=1,
        duration_days=66,
        price_usd=7.50,
        payment_method=PaymentMethod.CRYPTO,
        payment_option_id=5,
        expected_amount=None,
        expected_currency=CurrencyCode.USDT,
        expected_network=NetworkCode.TRC20,
        destination_address=None,
        destination_memo_tag=None,
        expires_at=datetime.now(UTC) + timedelta(minutes=15),
        target_subscription_id=50,
    )

    assert isinstance(order, Order)
    assert order.id == 900
    assert order.target_subscription_id == 50
    assert order.activated_subscription_id is None
    assert session.add_calls == [order]
    assert session.flush_count == 1
