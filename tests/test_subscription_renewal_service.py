from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import app.services.subscription_service as subscription_module
from app.payment_core.enums.order_status import OrderStatus
from app.payment_core.enums.subscription_status import SubscriptionStatus
from app.services.subscription_service import SubscriptionService
from app.services.vpn_access_service import VpnAccessResult


class FakeSession:
    def __init__(self) -> None:
        self.flush_count = 0
        self.commit_count = 0
        self.rollback_count = 0
        self.refresh_calls = []

    async def flush(self) -> None:
        self.flush_count += 1

    async def commit(self) -> None:
        self.commit_count += 1

    async def rollback(self) -> None:
        self.rollback_count += 1

    async def refresh(self, obj) -> None:
        self.refresh_calls.append(obj)


class FakeSubscriptionRepository:
    def __init__(self, subscriptions=None, legacy_subscription=None) -> None:
        self.subscriptions = subscriptions or {}
        self.legacy_subscription = legacy_subscription
        self.get_by_id_calls = []
        self.get_by_id_for_update_calls = []
        self.get_by_order_calls = []
        self.create_calls = []
        self.renew_calls = []
        self.activate_calls = []
        self.mark_access_sent_calls = []
        self.next_id = 100

    async def get_by_id(self, subscription_id: int):
        self.get_by_id_calls.append(subscription_id)
        return self.subscriptions.get(subscription_id)

    async def get_by_id_for_update(self, subscription_id: int):
        self.get_by_id_for_update_calls.append(subscription_id)
        return self.subscriptions.get(subscription_id)

    async def get_by_order_id(self, order_id: int):
        self.get_by_order_calls.append(order_id)
        return self.legacy_subscription

    async def create(self, **kwargs):
        self.create_calls.append(kwargs)
        subscription = SimpleNamespace(
            id=self.next_id,
            status=SubscriptionStatus.INACTIVE,
            last_access_sent_at=None,
            error_reason=None,
            disabled_at=None,
            **kwargs,
        )
        self.subscriptions[subscription.id] = subscription
        self.next_id += 1
        return subscription

    async def activate(self, subscription):
        self.activate_calls.append(subscription.id)
        subscription.status = SubscriptionStatus.ACTIVE
        return subscription

    async def renew(
        self,
        *,
        subscription,
        expires_at,
        device_limit,
    ):
        self.renew_calls.append(
            {
                "subscription_id": subscription.id,
                "expires_at": expires_at,
                "device_limit": device_limit,
            }
        )
        subscription.expires_at = expires_at
        subscription.device_limit = device_limit
        subscription.status = SubscriptionStatus.ACTIVE
        subscription.error_reason = None
        subscription.disabled_at = None
        return subscription

    async def mark_access_sent(self, subscription):
        self.mark_access_sent_calls.append(subscription.id)
        subscription.last_access_sent_at = datetime.now(timezone.utc)
        return subscription


class FakeVpnAccessService:
    def __init__(self) -> None:
        self.create_calls = []
        self.extend_calls = []
        self.get_config_calls = []

    async def create_access(self, *, user_id, device_limit):
        self.create_calls.append(
            {"user_id": user_id, "device_limit": device_limit}
        )
        return VpnAccessResult(
            uuid="new-uuid",
            vpn_server_id=3,
            config_uri="https://connect/new-uuid",
        )

    async def extend_access(self, *, uuid, device_limit):
        self.extend_calls.append(
            {"uuid": uuid, "device_limit": device_limit}
        )
        return VpnAccessResult(
            uuid=uuid,
            vpn_server_id=3,
            config_uri=f"https://connect/{uuid}",
        )

    async def get_config(self, *, uuid, device_limit):
        self.get_config_calls.append(
            {"uuid": uuid, "device_limit": device_limit}
        )
        return f"https://connect/{uuid}"


class FakeMetaSyncService:
    calls = []

    def __init__(self, session) -> None:
        self.session = session

    async def sync_safely(self, **kwargs):
        self.__class__.calls.append(kwargs)
        return SimpleNamespace(ok=True)


def make_order(
    *,
    order_id=23,
    user_id=7,
    status=OrderStatus.PAID,
    target_subscription_id=None,
    activated_subscription_id=None,
    device_limit=1,
    duration_days=33,
):
    return SimpleNamespace(
        id=order_id,
        user_id=user_id,
        status=status,
        target_subscription_id=target_subscription_id,
        activated_subscription_id=activated_subscription_id,
        device_limit=device_limit,
        duration_days=duration_days,
        activated_at=None,
    )


def make_subscription(
    *,
    subscription_id=50,
    user_id=7,
    order_id=10,
    status=SubscriptionStatus.ACTIVE,
    uuid="existing-uuid",
    device_limit=1,
    expires_at=None,
):
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        id=subscription_id,
        user_id=user_id,
        order_id=order_id,
        vpn_server_id=3,
        status=status,
        uuid=uuid,
        device_limit=device_limit,
        starts_at=now - timedelta(days=10),
        expires_at=expires_at or now + timedelta(days=10),
        last_access_sent_at=None,
        disabled_at=None,
        error_reason=None,
    )


def make_service(order, repository, vpn_access=None):
    service = SubscriptionService.__new__(SubscriptionService)
    service.session = FakeSession()
    service.subscription_repository = repository
    service.vpn_access_service = vpn_access or FakeVpnAccessService()

    async def get_order(order_id):
        return order if order is not None and order.id == order_id else None

    service._get_order_for_activation = get_order
    return service


@pytest.fixture(autouse=True)
def patch_sync(monkeypatch):
    FakeMetaSyncService.calls = []
    monkeypatch.setattr(
        subscription_module,
        "SubscriptionMetaSyncService",
        FakeMetaSyncService,
    )


@pytest.mark.asyncio
async def test_new_purchase_records_activated_subscription_id():
    order = make_order(target_subscription_id=None)
    repository = FakeSubscriptionRepository()
    vpn_access = FakeVpnAccessService()
    service = make_service(order, repository, vpn_access)

    subscription, _ = await service.activate_or_extend_by_order(order.id)

    assert order.activated_subscription_id == subscription.id
    assert order.status == OrderStatus.ACTIVATED
    assert repository.get_by_order_calls == [order.id]
    assert len(repository.create_calls) == 1
    assert repository.renew_calls == []
    assert vpn_access.create_calls == [{"user_id": 7, "device_limit": 1}]
    assert service.session.commit_count == 1


@pytest.mark.asyncio
async def test_active_subscription_renewal_preserves_uuid_and_origin_order():
    old_expires_at = datetime.now(timezone.utc) + timedelta(days=10)
    subscription = make_subscription(
        subscription_id=50,
        order_id=10,
        expires_at=old_expires_at,
    )
    order = make_order(
        target_subscription_id=50,
        duration_days=66,
    )
    repository = FakeSubscriptionRepository({50: subscription})
    vpn_access = FakeVpnAccessService()
    service = make_service(order, repository, vpn_access)

    result, config_uri = await service.activate_or_extend_by_order(order.id)

    assert result is subscription
    assert subscription.uuid == "existing-uuid"
    assert subscription.order_id == 10
    assert subscription.status == SubscriptionStatus.ACTIVE
    assert subscription.expires_at == old_expires_at + timedelta(days=66)
    assert order.activated_subscription_id == 50
    assert order.status == OrderStatus.ACTIVATED
    assert repository.get_by_id_for_update_calls == [50]
    assert repository.get_by_order_calls == []
    assert len(repository.renew_calls) == 1
    assert vpn_access.extend_calls == [
        {"uuid": "existing-uuid", "device_limit": 1}
    ]
    assert config_uri == "https://connect/existing-uuid"


@pytest.mark.asyncio
async def test_expired_subscription_renewal_starts_from_current_time():
    old_expires_at = datetime.now(timezone.utc) - timedelta(days=3)
    subscription = make_subscription(
        subscription_id=50,
        status=SubscriptionStatus.EXPIRED,
        expires_at=old_expires_at,
    )
    order = make_order(
        target_subscription_id=50,
        duration_days=33,
    )
    repository = FakeSubscriptionRepository({50: subscription})
    service = make_service(order, repository)

    before_call = datetime.now(timezone.utc)
    result, _ = await service.activate_or_extend_by_order(order.id)
    after_call = datetime.now(timezone.utc)

    assert result.status == SubscriptionStatus.ACTIVE
    assert result.expires_at >= before_call + timedelta(days=33)
    assert result.expires_at <= after_call + timedelta(days=33, seconds=1)
    assert result.order_id == 10
    assert order.activated_subscription_id == 50


@pytest.mark.asyncio
async def test_reprocessing_renewal_order_does_not_extend_twice():
    subscription = make_subscription(subscription_id=50)
    original_expires_at = subscription.expires_at
    order = make_order(
        status=OrderStatus.ACTIVATED,
        target_subscription_id=50,
        activated_subscription_id=50,
    )
    repository = FakeSubscriptionRepository({50: subscription})
    vpn_access = FakeVpnAccessService()
    service = make_service(order, repository, vpn_access)

    result, config_uri = await service.activate_or_extend_by_order(order.id)

    assert result is subscription
    assert subscription.expires_at == original_expires_at
    assert repository.get_by_id_calls == [50]
    assert repository.get_by_id_for_update_calls == []
    assert repository.renew_calls == []
    assert vpn_access.extend_calls == []
    assert vpn_access.get_config_calls == [
        {"uuid": "existing-uuid", "device_limit": 1}
    ]
    assert config_uri == "https://connect/existing-uuid"


@pytest.mark.asyncio
async def test_legacy_created_order_backfills_activation_result():
    subscription = make_subscription(
        subscription_id=50,
        order_id=23,
    )
    order = make_order(
        status=OrderStatus.PAID,
        target_subscription_id=None,
        activated_subscription_id=None,
    )
    repository = FakeSubscriptionRepository(
        {50: subscription},
        legacy_subscription=subscription,
    )
    service = make_service(order, repository)

    result, _ = await service.activate_or_extend_by_order(order.id)

    assert result is subscription
    assert order.activated_subscription_id == 50
    assert order.status == OrderStatus.ACTIVATED
    assert repository.get_by_order_calls == [23]
    assert repository.create_calls == []
    assert repository.renew_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "subscription",
    [
        None,
        make_subscription(user_id=999),
        make_subscription(status=SubscriptionStatus.DISABLED),
        make_subscription(status=SubscriptionStatus.INACTIVE),
        make_subscription(device_limit=2),
    ],
)
async def test_invalid_renewal_target_is_rejected(subscription):
    subscriptions = {} if subscription is None else {50: subscription}
    order = make_order(target_subscription_id=50)
    repository = FakeSubscriptionRepository(subscriptions)
    service = make_service(order, repository)

    with pytest.raises(ValueError):
        await service.activate_or_extend_by_order(order.id)

    assert repository.renew_calls == []
    assert order.status == OrderStatus.PAID
    assert order.activated_subscription_id is None
    assert service.session.commit_count == 0
    assert service.session.rollback_count == 1


@pytest.mark.asyncio
async def test_missing_activated_subscription_is_consistency_error():
    order = make_order(
        status=OrderStatus.ACTIVATED,
        activated_subscription_id=999,
    )
    repository = FakeSubscriptionRepository()
    service = make_service(order, repository)

    with pytest.raises(
        ValueError,
        match="references missing activated subscription 999",
    ):
        await service.activate_or_extend_by_order(order.id)

    assert repository.get_by_id_calls == [999]
    assert service.session.rollback_count == 1
