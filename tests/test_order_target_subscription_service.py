from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.common.enums import CurrencyCode, NetworkCode, TariffCode
from app.payment_core.enums.order_status import OrderStatus
from app.payment_core.enums.payment_method import PaymentMethod
from app.payment_core.enums.subscription_status import SubscriptionStatus
from app.services.order_service import OrderService


class FakeSession:
    def __init__(self) -> None:
        self.commit_count = 0
        self.rollback_count = 0

    async def commit(self) -> None:
        self.commit_count += 1

    async def rollback(self) -> None:
        self.rollback_count += 1


class FakeUserRepository:
    def __init__(self, user) -> None:
        self.user = user

    async def get_by_telegram_id(self, telegram_id: int):
        return self.user

    async def update_basic_info(
        self,
        *,
        user,
        username,
        first_name,
        last_name,
        language_code,
    ):
        return user


class FakePaymentOptionRepository:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def get_by_code(self, code: str):
        self.calls.append(code)
        return SimpleNamespace(
            id=5,
            code=code,
            payment_method=PaymentMethod.CRYPTO,
            currency=CurrencyCode.USDT,
            network=NetworkCode.TRC20,
        )


class FakeSubscriptionRepository:
    def __init__(self, subscriptions=None) -> None:
        self.subscriptions = subscriptions or {}
        self.calls: list[int] = []

    async def get_by_id(self, subscription_id: int):
        self.calls.append(subscription_id)
        return self.subscriptions.get(subscription_id)


class FakeOrderRepository:
    def __init__(self, waiting_orders=None) -> None:
        self.waiting_orders = waiting_orders or {}
        self.lookup_calls: list[dict] = []
        self.create_calls: list[dict] = []
        self.next_id = 100

    async def get_active_waiting_order_by_user(self, **kwargs):
        self.lookup_calls.append(kwargs)
        return self.waiting_orders.get(kwargs.get("target_subscription_id"))

    async def create(self, **kwargs):
        self.create_calls.append(kwargs)
        order = SimpleNamespace(
            id=self.next_id,
            status=OrderStatus.WAITING_PAYMENT,
            activated_subscription_id=None,
            **kwargs,
        )
        self.next_id += 1
        return order


def make_user(*, user_id: int = 7, telegram_id: int = 123):
    return SimpleNamespace(
        id=user_id,
        telegram_id=telegram_id,
        username="ivan",
        first_name="Ivan",
        last_name="Redeemer",
        language_code="ru",
    )


def make_subscription(
    *,
    subscription_id: int = 50,
    user_id: int = 7,
    status: SubscriptionStatus = SubscriptionStatus.ACTIVE,
    device_limit: int = 1,
):
    return SimpleNamespace(
        id=subscription_id,
        user_id=user_id,
        status=status,
        device_limit=device_limit,
    )


def make_service(*, subscriptions=None, waiting_orders=None):
    service = OrderService.__new__(OrderService)
    service.session = FakeSession()
    service.settings = SimpleNamespace(order_ttl_minutes=15, admin_ids=[])
    service.user_repository = FakeUserRepository(make_user())
    service.payment_option_repository = FakePaymentOptionRepository()
    service.subscription_repository = FakeSubscriptionRepository(subscriptions)
    service.order_repository = FakeOrderRepository(waiting_orders)
    return service


@pytest.mark.asyncio
async def test_new_purchase_does_not_query_target_subscription():
    service = make_service()

    order = await service.create_order(
        telegram_id=123,
        tariff_code=TariffCode.PERIOD_1_MONTH,
        payment_option_code="cryptobot_usdt",
    )

    assert service.subscription_repository.calls == []
    assert service.order_repository.lookup_calls == [
        {
            "user_id": 7,
            "tariff_code": TariffCode.PERIOD_1_MONTH,
            "payment_option_id": 5,
        }
    ]
    assert "target_subscription_id" not in service.order_repository.create_calls[0]
    assert order.activated_subscription_id is None
    assert service.session.commit_count == 1
    assert service.session.rollback_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status",
    [SubscriptionStatus.ACTIVE, SubscriptionStatus.EXPIRED],
)
async def test_renewal_order_allows_owned_active_or_expired_subscription(status):
    subscription = make_subscription(status=status)
    service = make_service(subscriptions={50: subscription})

    order = await service.create_order(
        telegram_id=123,
        tariff_code=TariffCode.PERIOD_2_MONTHS,
        payment_option_code="cryptobot_usdt",
        target_subscription_id=50,
    )

    assert service.subscription_repository.calls == [50]
    assert service.order_repository.lookup_calls == [
        {
            "user_id": 7,
            "tariff_code": TariffCode.PERIOD_2_MONTHS,
            "payment_option_id": 5,
            "target_subscription_id": 50,
        }
    ]
    assert service.order_repository.create_calls[0]["target_subscription_id"] == 50
    assert order.target_subscription_id == 50
    assert order.activated_subscription_id is None
    assert service.session.commit_count == 1
    assert service.session.rollback_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "subscription",
    [None, make_subscription(user_id=999)],
)
async def test_renewal_order_rejects_missing_or_foreign_subscription(subscription):
    subscriptions = {} if subscription is None else {50: subscription}
    service = make_service(subscriptions=subscriptions)

    with pytest.raises(ValueError, match="Target subscription not found: 50"):
        await service.create_order(
            telegram_id=123,
            tariff_code=TariffCode.PERIOD_1_MONTH,
            payment_option_code="cryptobot_usdt",
            target_subscription_id=50,
        )

    assert service.payment_option_repository.calls == []
    assert service.order_repository.lookup_calls == []
    assert service.order_repository.create_calls == []
    assert service.session.commit_count == 0
    assert service.session.rollback_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status",
    [SubscriptionStatus.INACTIVE, SubscriptionStatus.DISABLED],
)
async def test_renewal_order_rejects_non_renewable_status(status):
    service = make_service(subscriptions={50: make_subscription(status=status)})

    with pytest.raises(ValueError, match="Target subscription is not renewable"):
        await service.create_order(
            telegram_id=123,
            tariff_code=TariffCode.PERIOD_1_MONTH,
            payment_option_code="cryptobot_usdt",
            target_subscription_id=50,
        )

    assert service.payment_option_repository.calls == []
    assert service.order_repository.lookup_calls == []
    assert service.order_repository.create_calls == []
    assert service.session.commit_count == 0
    assert service.session.rollback_count == 1


@pytest.mark.asyncio
async def test_renewal_order_rejects_device_limit_mismatch():
    service = make_service(subscriptions={50: make_subscription(device_limit=2)})

    with pytest.raises(
        ValueError,
        match="Target subscription device limit does not match tariff",
    ):
        await service.create_order(
            telegram_id=123,
            tariff_code=TariffCode.PERIOD_1_MONTH,
            payment_option_code="cryptobot_usdt",
            target_subscription_id=50,
        )

    assert service.payment_option_repository.calls == []
    assert service.order_repository.lookup_calls == []
    assert service.order_repository.create_calls == []
    assert service.session.commit_count == 0
    assert service.session.rollback_count == 1


@pytest.mark.asyncio
async def test_waiting_renewal_order_is_reused_only_for_same_target():
    existing_order = SimpleNamespace(
        id=77,
        status=OrderStatus.WAITING_PAYMENT,
        target_subscription_id=50,
    )
    service = make_service(
        subscriptions={50: make_subscription(subscription_id=50)},
        waiting_orders={50: existing_order},
    )

    result = await service.create_order(
        telegram_id=123,
        tariff_code=TariffCode.PERIOD_3_MONTHS,
        payment_option_code="cryptobot_usdt",
        target_subscription_id=50,
    )

    assert result is existing_order
    assert service.order_repository.lookup_calls[0]["target_subscription_id"] == 50
    assert service.order_repository.create_calls == []
    assert service.session.commit_count == 1
    assert service.session.rollback_count == 0
