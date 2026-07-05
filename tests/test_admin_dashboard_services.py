from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.common.enums import TariffCode
from app.database.models import User
from app.payment_core.enums.order_status import OrderStatus
from app.payment_core.enums.payment_status import PaymentStatus
from app.payment_core.enums.subscription_status import SubscriptionStatus
from app.services.admin_active_subscriptions_service import (
    AdminActiveSubscriptionItem,
    AdminActiveSubscriptionsService,
)
from app.services.admin_stats_service import AdminStatsResult, AdminStatsService


class FakeActiveExecuteResult:
    def __init__(self, rows) -> None:
        self.rows = rows

    def all(self):
        return self.rows


class FakeStatsExecuteResult:
    def __init__(self, value) -> None:
        self.value = value

    def scalar_one(self):
        return self.value


class FakeActiveSession:
    def __init__(self, *, rows=None) -> None:
        self.rows = rows or []
        self.execute_calls = []

    async def execute(self, stmt):
        self.execute_calls.append(stmt)
        return FakeActiveExecuteResult(self.rows)


class FakeStatsSession:
    def __init__(self, values) -> None:
        self.values = list(values)
        self.execute_calls = []

    async def execute(self, stmt):
        self.execute_calls.append(stmt)

        if not self.values:
            raise AssertionError("Unexpected execute call")

        return FakeStatsExecuteResult(self.values.pop(0))


def make_subscription(
    *,
    subscription_id: int = 50,
    order_id: int | None = 23,
    user_id: int | None = 7,
    status: SubscriptionStatus = SubscriptionStatus.ACTIVE,
    uuid: str | None = "uuid-1",
    device_limit: int | None = 2,
    starts_at=None,
    expires_at=None,
    last_access_sent_at=None,
    vpn_server_id: int | None = 3,
):
    return SimpleNamespace(
        id=subscription_id,
        order_id=order_id,
        user_id=user_id,
        status=status,
        uuid=uuid,
        device_limit=device_limit,
        starts_at=starts_at,
        expires_at=expires_at,
        last_access_sent_at=last_access_sent_at,
        vpn_server_id=vpn_server_id,
    )


def make_user(
    *,
    telegram_id: int = 123456,
    username: str | None = "ivan",
):
    return SimpleNamespace(
        telegram_id=telegram_id,
        username=username,
    )


def make_order(
    *,
    status: OrderStatus = OrderStatus.ACTIVATED,
    tariff_code: TariffCode = TariffCode.DEVICES_2,
):
    return SimpleNamespace(
        status=status,
        tariff_code=tariff_code,
    )


@pytest.mark.asyncio
async def test_get_active_subscriptions_returns_empty_list_when_no_rows():
    session = FakeActiveSession(rows=[])
    service = AdminActiveSubscriptionsService(session)

    result = await service.get_active_subscriptions(limit=20)

    assert result == []
    assert len(session.execute_calls) == 1


@pytest.mark.asyncio
async def test_get_active_subscriptions_maps_subscription_user_and_order_context():
    starts_at = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    expires_at = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
    last_access_sent_at = datetime(2026, 7, 5, 12, 0, tzinfo=timezone.utc)
    subscription = make_subscription(
        subscription_id=50,
        order_id=23,
        user_id=7,
        status=SubscriptionStatus.ACTIVE,
        uuid="active-uuid",
        device_limit=3,
        starts_at=starts_at,
        expires_at=expires_at,
        last_access_sent_at=last_access_sent_at,
        vpn_server_id=5,
    )
    user = make_user(telegram_id=123456, username="ivan")
    order = make_order(
        status=OrderStatus.ACTIVATED,
        tariff_code=TariffCode.DEVICES_3,
    )
    session = FakeActiveSession(rows=[(subscription, user, order)])
    service = AdminActiveSubscriptionsService(session)

    result = await service.get_active_subscriptions(limit=10)

    assert result == [
        AdminActiveSubscriptionItem(
            subscription_id=50,
            order_id=23,
            user_id=7,
            telegram_id=123456,
            username="ivan",
            status="active",
            uuid="active-uuid",
            device_limit=3,
            starts_at=starts_at,
            expires_at=expires_at,
            last_access_sent_at=last_access_sent_at,
            vpn_server_id=5,
            order_status="activated",
            order_tariff_code="devices_3",
        )
    ]
    assert len(session.execute_calls) == 1


@pytest.mark.asyncio
async def test_get_active_subscriptions_allows_missing_user_and_order_context():
    subscription = make_subscription(
        subscription_id=51,
        order_id=None,
        user_id=None,
        status=SubscriptionStatus.ACTIVE,
        uuid=None,
        device_limit=None,
        vpn_server_id=None,
    )
    session = FakeActiveSession(rows=[(subscription, None, None)])
    service = AdminActiveSubscriptionsService(session)

    result = await service.get_active_subscriptions(limit=10)

    assert result == [
        AdminActiveSubscriptionItem(
            subscription_id=51,
            order_id=None,
            user_id=None,
            telegram_id=None,
            username=None,
            status="active",
            uuid=None,
            device_limit=None,
            starts_at=None,
            expires_at=None,
            last_access_sent_at=None,
            vpn_server_id=None,
            order_status=None,
            order_tariff_code=None,
        )
    ]


def test_active_subscriptions_enum_to_str_handles_none_enum_and_plain_value():
    assert AdminActiveSubscriptionsService._enum_to_str(None) is None
    assert AdminActiveSubscriptionsService._enum_to_str(SubscriptionStatus.ACTIVE) == "active"
    assert AdminActiveSubscriptionsService._enum_to_str(TariffCode.DEVICES_1) == "devices_1"
    assert AdminActiveSubscriptionsService._enum_to_str("custom") == "custom"


@pytest.mark.asyncio
async def test_admin_stats_get_stats_queries_all_counters_and_maps_result():
    values = [
        10,
        20,
        1,
        2,
        3,
        4,
        5,
        6,
        30,
        7,
        8,
        9,
        10,
        11,
        12,
        13,
        14,
        Decimal("123.45"),
    ]
    session = FakeStatsSession(values=values)
    service = AdminStatsService(session)

    result = await service.get_stats()

    assert result == AdminStatsResult(
        users_total=10,
        orders_total=20,
        orders_waiting_payment=1,
        orders_paid=2,
        orders_activated=3,
        orders_expired=4,
        orders_failed=5,
        orders_cancelled=6,
        payments_total=30,
        payments_confirmed=7,
        payments_invalid=8,
        payments_duplicate=9,
        payments_error=10,
        subscriptions_total=11,
        subscriptions_active=12,
        subscriptions_expired=13,
        subscriptions_disabled=14,
        confirmed_revenue_total=Decimal("123.45"),
    )
    assert len(session.execute_calls) == 18


@pytest.mark.asyncio
async def test_admin_stats_count_converts_none_to_zero():
    session = FakeStatsSession(values=[None])
    service = AdminStatsService(session)

    result = await service._count(User)

    assert result == 0
    assert len(session.execute_calls) == 1


@pytest.mark.asyncio
async def test_admin_stats_count_status_helpers_convert_none_to_zero():
    session = FakeStatsSession(values=[None, None, None])
    service = AdminStatsService(session)

    orders_count = await service._count_orders_by_status(OrderStatus.WAITING_PAYMENT)
    payments_count = await service._count_payments_by_status(PaymentStatus.CONFIRMED)
    subscriptions_count = await service._count_subscriptions_by_status(
        SubscriptionStatus.ACTIVE,
    )

    assert orders_count == 0
    assert payments_count == 0
    assert subscriptions_count == 0
    assert len(session.execute_calls) == 3


@pytest.mark.asyncio
async def test_admin_stats_confirmed_revenue_total_converts_none_and_numeric_values_to_decimal():
    none_session = FakeStatsSession(values=[None])
    none_service = AdminStatsService(none_session)

    assert await none_service._confirmed_revenue_total() == Decimal("0")

    numeric_session = FakeStatsSession(values=["45.67"])
    numeric_service = AdminStatsService(numeric_session)

    assert await numeric_service._confirmed_revenue_total() == Decimal("45.67")