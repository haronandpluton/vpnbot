from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.common.enums import CurrencyCode
from app.payment_core.enums.payment_status import PaymentStatus
from app.services.admin_lookup_service import (
    AdminLookupService,
    clean,
    datetime_to_str,
    decimal_to_str,
    enum_to_str,
)
from app.services.admin_subscription_lookup_service import AdminSubscriptionLookupService
from app.services.admin_user_lookup_service import AdminUserLookupService


class FakeScalarResult:
    def __init__(self, items) -> None:
        self.items = items

    def all(self):
        return self.items


class FakeExecuteResult:
    def __init__(self, *, scalar_value=None, scalar_one_value=None, items=None) -> None:
        self.scalar_value = scalar_value
        self.scalar_one_value = scalar_one_value
        self.items = items or []

    def scalar_one_or_none(self):
        return self.scalar_value

    def scalar_one(self):
        return self.scalar_one_value

    def scalars(self):
        return FakeScalarResult(self.items)


class FakeSession:
    def __init__(self, results) -> None:
        self.results = list(results)
        self.execute_calls = []

    async def execute(self, stmt):
        self.execute_calls.append(stmt)

        if not self.results:
            raise AssertionError("Unexpected execute call")

        return self.results.pop(0)


def scalar(value):
    return FakeExecuteResult(scalar_value=value)


def scalar_one(value):
    return FakeExecuteResult(scalar_one_value=value)


def items(values):
    return FakeExecuteResult(items=values)


def make_user(
    *,
    user_id: int = 7,
    telegram_id: int = 123456,
    username: str = "ivan",
):
    return SimpleNamespace(
        id=user_id,
        telegram_id=telegram_id,
        username=username,
    )


def make_order(*, order_id: int = 23, user_id: int = 7):
    return SimpleNamespace(
        id=order_id,
        user_id=user_id,
        created_at=datetime.now(timezone.utc),
    )


def make_payment(
    *,
    payment_id: int = 50,
    order_id: int | None = 23,
    user_id: int | None = 7,
):
    return SimpleNamespace(
        id=payment_id,
        order_id=order_id,
        user_id=user_id,
        status=PaymentStatus.CONFIRMED,
        created_at=datetime.now(timezone.utc),
    )


def make_event(*, event_id: int = 70, order_id: int = 23):
    return SimpleNamespace(
        id=event_id,
        order_id=order_id,
        created_at=datetime.now(timezone.utc),
    )


def make_subscription(
    *,
    subscription_id: int = 90,
    user_id: int = 7,
    order_id: int | None = 23,
):
    return SimpleNamespace(
        id=subscription_id,
        user_id=user_id,
        order_id=order_id,
        created_at=datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
async def test_admin_lookup_order_card_returns_not_found_without_loading_related_entities():
    session = FakeSession([scalar(None)])
    service = AdminLookupService(session)

    result = await service.get_order_card(404)

    assert result.found is False
    assert result.order is None
    assert result.user is None
    assert result.payments is None
    assert result.events is None
    assert result.subscriptions is None
    assert len(session.execute_calls) == 1


@pytest.mark.asyncio
async def test_admin_lookup_order_card_loads_user_payments_events_and_subscriptions():
    order = make_order(order_id=23, user_id=7)
    user = make_user(user_id=7)
    payments = [make_payment(payment_id=1), make_payment(payment_id=2)]
    events = [make_event(event_id=3), make_event(event_id=4)]
    subscriptions = [make_subscription(subscription_id=5)]
    session = FakeSession(
        [
            scalar(order),
            scalar(user),
            items(payments),
            items(events),
            items(subscriptions),
        ]
    )
    service = AdminLookupService(session)

    result = await service.get_order_card(23)

    assert result.found is True
    assert result.order is order
    assert result.user is user
    assert result.payments == payments
    assert result.events == events
    assert result.subscriptions == subscriptions
    assert len(session.execute_calls) == 5


@pytest.mark.asyncio
async def test_admin_lookup_payment_card_returns_not_found_without_loading_related_entities():
    session = FakeSession([scalar(None)])
    service = AdminLookupService(session)

    result = await service.get_payment_card(404)

    assert result.found is False
    assert result.payment is None
    assert result.order is None
    assert result.user is None
    assert result.events is None
    assert result.subscriptions is None
    assert len(session.execute_calls) == 1


@pytest.mark.asyncio
async def test_admin_lookup_payment_card_loads_order_user_events_and_subscriptions():
    payment = make_payment(payment_id=50, order_id=23, user_id=7)
    order = make_order(order_id=23, user_id=7)
    user = make_user(user_id=7)
    events = [make_event(event_id=70)]
    subscriptions = [make_subscription(subscription_id=90)]
    session = FakeSession(
        [
            scalar(payment),
            scalar(order),
            items(events),
            items(subscriptions),
            scalar(user),
        ]
    )
    service = AdminLookupService(session)

    result = await service.get_payment_card(50)

    assert result.found is True
    assert result.payment is payment
    assert result.order is order
    assert result.user is user
    assert result.events == events
    assert result.subscriptions == subscriptions
    assert len(session.execute_calls) == 5


@pytest.mark.asyncio
async def test_admin_lookup_payment_card_allows_payment_without_order_or_user_links():
    payment = make_payment(payment_id=50, order_id=None, user_id=None)
    session = FakeSession([scalar(payment)])
    service = AdminLookupService(session)

    result = await service.get_payment_card(50)

    assert result.found is True
    assert result.payment is payment
    assert result.order is None
    assert result.user is None
    assert result.events == []
    assert result.subscriptions == []
    assert len(session.execute_calls) == 1


@pytest.mark.asyncio
async def test_admin_subscription_lookup_returns_not_found_without_loading_related_entities():
    session = FakeSession([scalar(None)])
    service = AdminSubscriptionLookupService(session)

    result = await service.get_subscription_card(404)

    assert result.found is False
    assert result.subscription is None
    assert result.user is None
    assert result.order is None
    assert result.payments is None
    assert result.events is None
    assert len(session.execute_calls) == 1


@pytest.mark.asyncio
async def test_admin_subscription_lookup_loads_user_order_payments_and_events():
    subscription = make_subscription(subscription_id=90, user_id=7, order_id=23)
    user = make_user(user_id=7)
    order = make_order(order_id=23, user_id=7)
    payments = [make_payment(payment_id=50)]
    events = [make_event(event_id=70)]
    session = FakeSession(
        [
            scalar(subscription),
            scalar(user),
            scalar(order),
            items(payments),
            items(events),
        ]
    )
    service = AdminSubscriptionLookupService(session)

    result = await service.get_subscription_card(90)

    assert result.found is True
    assert result.subscription is subscription
    assert result.user is user
    assert result.order is order
    assert result.payments == payments
    assert result.events == events
    assert len(session.execute_calls) == 5


@pytest.mark.asyncio
async def test_admin_subscription_lookup_without_order_id_does_not_load_payments_or_events():
    subscription = make_subscription(subscription_id=90, user_id=7, order_id=None)
    user = make_user(user_id=7)
    session = FakeSession([scalar(subscription), scalar(user), scalar(None)])
    service = AdminSubscriptionLookupService(session)

    result = await service.get_subscription_card(90)

    assert result.found is True
    assert result.subscription is subscription
    assert result.user is user
    assert result.order is None
    assert result.payments == []
    assert result.events == []
    assert len(session.execute_calls) == 3


@pytest.mark.asyncio
async def test_admin_user_lookup_by_user_id_returns_not_found_without_loading_related_entities():
    session = FakeSession([scalar(None)])
    service = AdminUserLookupService(session)

    result = await service.get_user_card_by_user_id(404)

    assert result.found is False
    assert result.user is None
    assert result.orders is None
    assert result.payments is None
    assert result.subscriptions is None
    assert result.invalid_payments_count == 0
    assert len(session.execute_calls) == 1


@pytest.mark.asyncio
async def test_admin_user_lookup_by_user_id_loads_orders_payments_subscriptions_and_invalid_count():
    user = make_user(user_id=7)
    orders = [make_order(order_id=1), make_order(order_id=2)]
    payments = [make_payment(payment_id=3), make_payment(payment_id=4)]
    subscriptions = [make_subscription(subscription_id=5)]
    session = FakeSession(
        [
            scalar(user),
            items(orders),
            items(payments),
            items(subscriptions),
            scalar_one(2),
        ]
    )
    service = AdminUserLookupService(session)

    result = await service.get_user_card_by_user_id(7)

    assert result.found is True
    assert result.user is user
    assert result.orders == orders
    assert result.payments == payments
    assert result.subscriptions == subscriptions
    assert result.invalid_payments_count == 2
    assert len(session.execute_calls) == 5


@pytest.mark.asyncio
async def test_admin_user_lookup_by_telegram_id_loads_same_user_card():
    user = make_user(user_id=7, telegram_id=123456)
    session = FakeSession(
        [
            scalar(user),
            items([]),
            items([]),
            items([]),
            scalar_one(0),
        ]
    )
    service = AdminUserLookupService(session)

    result = await service.get_user_card_by_telegram_id(123456)

    assert result.found is True
    assert result.user is user
    assert result.orders == []
    assert result.payments == []
    assert result.subscriptions == []
    assert result.invalid_payments_count == 0
    assert len(session.execute_calls) == 5


def test_enum_to_str_handles_none_enum_and_plain_value():
    assert enum_to_str(None) == "—"
    assert enum_to_str(CurrencyCode.USDT) == "USDT"
    assert enum_to_str("custom") == "custom"


def test_decimal_to_str_handles_none_zero_integers_and_fractional_values():
    assert decimal_to_str(None) == "—"
    assert decimal_to_str(Decimal("0")) == "0"
    assert decimal_to_str(Decimal("4.00000000")) == "4"
    assert decimal_to_str(Decimal("4.25000000")) == "4.25"
    assert decimal_to_str(Decimal("0.12345678")) == "0.12345678"


def test_datetime_to_str_handles_none_and_formats_datetime_without_timezone_suffix():
    value = datetime(2026, 7, 5, 12, 34, 56, tzinfo=timezone.utc)

    assert datetime_to_str(None) == "—"
    assert datetime_to_str(value) == "05.07.2026 12:34:56"


def test_clean_handles_none_empty_string_and_plain_value():
    assert clean(None) == "—"
    assert clean("") == "—"
    assert clean("value") == "value"
    assert clean(123) == "123"