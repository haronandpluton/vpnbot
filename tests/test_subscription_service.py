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
        self.refresh_calls: list[object] = []

    async def flush(self) -> None:
        self.flush_count += 1

    async def commit(self) -> None:
        self.commit_count += 1

    async def rollback(self) -> None:
        self.rollback_count += 1

    async def refresh(self, obj) -> None:
        self.refresh_calls.append(obj)


class FakeSubscriptionRepository:
    def __init__(
        self,
        *,
        active_subscription=None,
        subscription_by_order=None,
    ) -> None:
        self.active_subscription = active_subscription
        self.subscription_by_order = subscription_by_order
        self.created_subscriptions: list[SimpleNamespace] = []
        self.get_by_order_calls: list[int] = []
        self.get_active_calls: list[int] = []
        self.create_calls: list[dict] = []
        self.activate_calls: list[int] = []
        self.extend_calls: list[dict] = []
        self.mark_access_sent_calls: list[int] = []
        self.next_id = 100

    async def get_by_order_id(self, order_id: int):
        self.get_by_order_calls.append(order_id)
        return self.subscription_by_order

    async def get_active_subscription_by_user_id(self, user_id: int):
        self.get_active_calls.append(user_id)
        return self.active_subscription

    async def create(
        self,
        *,
        user_id: int,
        order_id: int | None,
        vpn_server_id: int | None,
        uuid: str,
        device_limit: int,
        starts_at: datetime,
        expires_at: datetime,
    ):
        self.create_calls.append(
            {
                "user_id": user_id,
                "order_id": order_id,
                "vpn_server_id": vpn_server_id,
                "uuid": uuid,
                "device_limit": device_limit,
                "starts_at": starts_at,
                "expires_at": expires_at,
            }
        )

        subscription = SimpleNamespace(
            id=self.next_id,
            user_id=user_id,
            order_id=order_id,
            vpn_server_id=vpn_server_id,
            status=SubscriptionStatus.INACTIVE,
            uuid=uuid,
            device_limit=device_limit,
            starts_at=starts_at,
            expires_at=expires_at,
            last_access_sent_at=None,
            error_reason=None,
        )
        self.next_id += 1
        self.created_subscriptions.append(subscription)
        return subscription

    async def activate(self, subscription):
        self.activate_calls.append(subscription.id)
        subscription.status = SubscriptionStatus.ACTIVE
        subscription.error_reason = None
        return subscription

    async def extend(
        self,
        *,
        subscription,
        order_id: int | None,
        expires_at: datetime,
        device_limit: int | None = None,
    ):
        self.extend_calls.append(
            {
                "subscription_id": subscription.id,
                "order_id": order_id,
                "expires_at": expires_at,
                "device_limit": device_limit,
            }
        )

        subscription.order_id = order_id
        subscription.expires_at = expires_at

        if device_limit is not None:
            subscription.device_limit = device_limit

        subscription.status = SubscriptionStatus.ACTIVE
        subscription.error_reason = None
        return subscription

    async def mark_access_sent(self, subscription):
        self.mark_access_sent_calls.append(subscription.id)
        subscription.last_access_sent_at = datetime.now(timezone.utc)
        return subscription


class FakeVpnAccessService:
    def __init__(self, *, fail_create: bool = False, fail_extend: bool = False) -> None:
        self.fail_create = fail_create
        self.fail_extend = fail_extend
        self.create_calls: list[dict] = []
        self.extend_calls: list[dict] = []
        self.get_config_calls: list[dict] = []

    async def create_access(self, *, user_id: int, device_limit: int):
        self.create_calls.append({"user_id": user_id, "device_limit": device_limit})

        if self.fail_create:
            raise RuntimeError("create_access failed")

        return VpnAccessResult(
            uuid="new-vpn-uuid",
            vpn_server_id=11,
            config_uri="https://connect/new-vpn-uuid",
        )

    async def extend_access(self, *, uuid: str, device_limit: int):
        self.extend_calls.append({"uuid": uuid, "device_limit": device_limit})

        if self.fail_extend:
            raise RuntimeError("extend_access failed")

        return VpnAccessResult(
            uuid=uuid,
            vpn_server_id=11,
            config_uri=f"https://connect/{uuid}",
        )

    async def get_config(self, *, uuid: str, device_limit: int):
        self.get_config_calls.append({"uuid": uuid, "device_limit": device_limit})
        return f"https://connect/{uuid}"


class FakeSubscriptionMetaSyncService:
    calls: list[dict] = []
    result = SimpleNamespace(ok=True, error=None)

    def __init__(self, session) -> None:
        self.session = session

    async def sync_safely(self, **kwargs):
        self.__class__.calls.append(kwargs)
        return self.__class__.result


def make_order(
    *,
    order_id: int = 23,
    user_id: int = 7,
    status: OrderStatus = OrderStatus.PAID,
    device_limit: int = 1,
):
    return SimpleNamespace(
        id=order_id,
        user_id=user_id,
        status=status,
        device_limit=device_limit,
        activated_at=None,
    )


def make_subscription(
    *,
    subscription_id: int = 50,
    user_id: int = 7,
    order_id: int | None = None,
    status: SubscriptionStatus = SubscriptionStatus.ACTIVE,
    uuid: str = "existing-uuid",
    device_limit: int = 1,
    expires_at: datetime | None = None,
):
    now = datetime.now(timezone.utc)

    return SimpleNamespace(
        id=subscription_id,
        user_id=user_id,
        order_id=order_id,
        vpn_server_id=11,
        status=status,
        uuid=uuid,
        device_limit=device_limit,
        starts_at=now - timedelta(days=1),
        expires_at=expires_at or now + timedelta(days=10),
        last_access_sent_at=None,
        error_reason=None,
    )


def make_service(
    *,
    order,
    subscription_repository: FakeSubscriptionRepository | None = None,
    vpn_access_service: FakeVpnAccessService | None = None,
):
    service = SubscriptionService.__new__(SubscriptionService)
    service.session = FakeSession()
    service.subscription_repository = subscription_repository or FakeSubscriptionRepository()
    service.vpn_access_service = vpn_access_service or FakeVpnAccessService()
    service._get_order_for_activation = lambda order_id: _return_order(order, order_id)
    return service


async def _return_order(order, order_id: int):
    if order is None:
        return None

    if order.id != order_id:
        return None

    return order


@pytest.fixture(autouse=True)
def patch_meta_sync(monkeypatch):
    FakeSubscriptionMetaSyncService.calls = []
    FakeSubscriptionMetaSyncService.result = SimpleNamespace(ok=True, error=None)

    monkeypatch.setattr(
        subscription_module,
        "SubscriptionMetaSyncService",
        FakeSubscriptionMetaSyncService,
    )


@pytest.mark.asyncio
async def test_paid_order_without_active_subscription_creates_new_subscription_and_activates_order():
    order = make_order(order_id=23, user_id=7, status=OrderStatus.PAID, device_limit=2)
    repository = FakeSubscriptionRepository(active_subscription=None)
    vpn_access = FakeVpnAccessService()
    service = make_service(
        order=order,
        subscription_repository=repository,
        vpn_access_service=vpn_access,
    )

    subscription, config_uri = await service.activate_or_extend_by_order(order.id)

    assert subscription.uuid == "new-vpn-uuid"
    assert subscription.status == SubscriptionStatus.ACTIVE
    assert subscription.user_id == 7
    assert subscription.order_id == 23
    assert subscription.device_limit == 2
    assert subscription.vpn_server_id == 11
    assert subscription.last_access_sent_at is not None
    assert config_uri == "https://connect/new-vpn-uuid"

    assert order.status == OrderStatus.ACTIVATED
    assert order.activated_at is not None
    assert vpn_access.create_calls == [{"user_id": 7, "device_limit": 2}]
    assert vpn_access.extend_calls == []
    assert vpn_access.get_config_calls == []
    assert len(repository.create_calls) == 1
    assert repository.activate_calls == [subscription.id]
    assert repository.mark_access_sent_calls == [subscription.id]
    assert service.session.commit_count == 1
    assert service.session.rollback_count == 0
    assert service.session.refresh_calls == [subscription]
    assert FakeSubscriptionMetaSyncService.calls[0]["reason"] == "post_payment_subscription_change"


@pytest.mark.asyncio
async def test_reprocessing_same_order_reuses_existing_subscription_without_create_or_extend():
    order = make_order(order_id=23, status=OrderStatus.PAID, device_limit=3)
    existing_subscription = make_subscription(
        subscription_id=77,
        user_id=7,
        order_id=23,
        uuid="same-order-uuid",
        device_limit=3,
    )
    repository = FakeSubscriptionRepository(
        active_subscription=None,
        subscription_by_order=existing_subscription,
    )
    vpn_access = FakeVpnAccessService()
    service = make_service(
        order=order,
        subscription_repository=repository,
        vpn_access_service=vpn_access,
    )

    subscription, config_uri = await service.activate_or_extend_by_order(order.id)

    assert subscription is existing_subscription
    assert config_uri == "https://connect/same-order-uuid"
    assert order.status == OrderStatus.ACTIVATED
    assert order.activated_at is not None
    assert repository.create_calls == []
    assert repository.extend_calls == []
    assert repository.mark_access_sent_calls == []
    assert vpn_access.create_calls == []
    assert vpn_access.extend_calls == []
    assert vpn_access.get_config_calls == [
        {"uuid": "same-order-uuid", "device_limit": 3}
    ]
    assert service.session.commit_count == 1
    assert FakeSubscriptionMetaSyncService.calls[0]["reason"] == "idempotent_order_activation_reuse"


@pytest.mark.asyncio
async def test_activated_order_without_subscription_by_order_reuses_active_subscription():
    order = make_order(order_id=23, status=OrderStatus.ACTIVATED, device_limit=1)
    active_subscription = make_subscription(
        subscription_id=88,
        user_id=7,
        order_id=10,
        uuid="active-uuid",
        device_limit=1,
    )
    repository = FakeSubscriptionRepository(active_subscription=active_subscription)
    vpn_access = FakeVpnAccessService()
    service = make_service(
        order=order,
        subscription_repository=repository,
        vpn_access_service=vpn_access,
    )

    subscription, config_uri = await service.activate_or_extend_by_order(order.id)

    assert subscription is active_subscription
    assert config_uri == "https://connect/active-uuid"
    assert order.status == OrderStatus.ACTIVATED
    assert repository.create_calls == []
    assert repository.extend_calls == []
    assert vpn_access.create_calls == []
    assert vpn_access.extend_calls == []
    assert vpn_access.get_config_calls == [{"uuid": "active-uuid", "device_limit": 1}]
    assert service.session.commit_count == 1
    assert FakeSubscriptionMetaSyncService.calls[0]["reason"] == "activated_order_resync"


@pytest.mark.asyncio
async def test_non_paid_order_does_not_create_subscription_and_rolls_back():
    order = make_order(order_id=23, status=OrderStatus.WAITING_PAYMENT, device_limit=1)
    repository = FakeSubscriptionRepository(active_subscription=None)
    vpn_access = FakeVpnAccessService()
    service = make_service(
        order=order,
        subscription_repository=repository,
        vpn_access_service=vpn_access,
    )

    with pytest.raises(ValueError, match="Order must be paid before subscription activation"):
        await service.activate_or_extend_by_order(order.id)

    assert order.status == OrderStatus.WAITING_PAYMENT
    assert repository.create_calls == []
    assert repository.extend_calls == []
    assert vpn_access.create_calls == []
    assert vpn_access.extend_calls == []
    assert service.session.commit_count == 0
    assert service.session.rollback_count == 1
    assert FakeSubscriptionMetaSyncService.calls == []


@pytest.mark.asyncio
async def test_paid_order_with_active_subscription_extends_existing_uuid_from_current_expiry():
    current_expires_at = datetime.now(timezone.utc) + timedelta(days=10)
    order = make_order(order_id=24, status=OrderStatus.PAID, device_limit=3)
    active_subscription = make_subscription(
        subscription_id=90,
        user_id=7,
        order_id=10,
        uuid="renewed-uuid",
        device_limit=1,
        expires_at=current_expires_at,
    )
    repository = FakeSubscriptionRepository(active_subscription=active_subscription)
    vpn_access = FakeVpnAccessService()
    service = make_service(
        order=order,
        subscription_repository=repository,
        vpn_access_service=vpn_access,
    )

    subscription, config_uri = await service.activate_or_extend_by_order(order.id)

    assert subscription is active_subscription
    assert subscription.uuid == "renewed-uuid"
    assert subscription.order_id == 24
    assert subscription.device_limit == 3
    assert subscription.expires_at == current_expires_at + timedelta(days=30)
    assert config_uri == "https://connect/renewed-uuid"
    assert order.status == OrderStatus.ACTIVATED
    assert vpn_access.create_calls == []
    assert vpn_access.extend_calls == [{"uuid": "renewed-uuid", "device_limit": 3}]
    assert repository.create_calls == []
    assert repository.extend_calls == [
        {
            "subscription_id": 90,
            "order_id": 24,
            "expires_at": current_expires_at + timedelta(days=30),
            "device_limit": 3,
        }
    ]
    assert service.session.commit_count == 1


@pytest.mark.asyncio
async def test_paid_order_with_past_active_subscription_extends_from_now_not_old_expiry():
    past_expires_at = datetime.now(timezone.utc) - timedelta(days=5)
    before_call = datetime.now(timezone.utc)
    order = make_order(order_id=25, status=OrderStatus.PAID, device_limit=2)
    active_subscription = make_subscription(
        subscription_id=91,
        user_id=7,
        order_id=10,
        uuid="past-active-uuid",
        device_limit=1,
        expires_at=past_expires_at,
    )
    repository = FakeSubscriptionRepository(active_subscription=active_subscription)
    vpn_access = FakeVpnAccessService()
    service = make_service(
        order=order,
        subscription_repository=repository,
        vpn_access_service=vpn_access,
    )

    subscription, config_uri = await service.activate_or_extend_by_order(order.id)

    after_call = datetime.now(timezone.utc)

    assert subscription is active_subscription
    assert subscription.uuid == "past-active-uuid"
    assert config_uri == "https://connect/past-active-uuid"
    assert subscription.expires_at >= before_call + timedelta(days=30)
    assert subscription.expires_at <= after_call + timedelta(days=30, seconds=1)
    assert subscription.expires_at > past_expires_at + timedelta(days=30)
    assert vpn_access.extend_calls == [{"uuid": "past-active-uuid", "device_limit": 2}]
    assert vpn_access.create_calls == []
    assert service.session.commit_count == 1


@pytest.mark.asyncio
async def test_resend_access_returns_existing_config_without_creating_or_extending_access():
    active_subscription = make_subscription(
        subscription_id=92,
        user_id=7,
        order_id=23,
        uuid="resend-uuid",
        device_limit=2,
    )
    repository = FakeSubscriptionRepository(active_subscription=active_subscription)
    vpn_access = FakeVpnAccessService()
    service = make_service(
        order=make_order(),
        subscription_repository=repository,
        vpn_access_service=vpn_access,
    )

    subscription, config_uri = await service.resend_access(user_id=7)

    assert subscription is active_subscription
    assert config_uri == "https://connect/resend-uuid"
    assert subscription.uuid == "resend-uuid"
    assert subscription.last_access_sent_at is not None
    assert vpn_access.get_config_calls == [{"uuid": "resend-uuid", "device_limit": 2}]
    assert vpn_access.create_calls == []
    assert vpn_access.extend_calls == []
    assert repository.mark_access_sent_calls == [92]
    assert service.session.commit_count == 1
    assert service.session.rollback_count == 0


@pytest.mark.asyncio
async def test_resend_access_without_active_subscription_rolls_back_and_raises():
    repository = FakeSubscriptionRepository(active_subscription=None)
    vpn_access = FakeVpnAccessService()
    service = make_service(
        order=make_order(),
        subscription_repository=repository,
        vpn_access_service=vpn_access,
    )

    with pytest.raises(ValueError, match="Active subscription not found for user_id=7"):
        await service.resend_access(user_id=7)

    assert vpn_access.get_config_calls == []
    assert repository.mark_access_sent_calls == []
    assert service.session.commit_count == 0
    assert service.session.rollback_count == 1


@pytest.mark.asyncio
async def test_vpn_create_error_rolls_back_and_does_not_mark_order_activated():
    order = make_order(order_id=23, status=OrderStatus.PAID, device_limit=1)
    repository = FakeSubscriptionRepository(active_subscription=None)
    vpn_access = FakeVpnAccessService(fail_create=True)
    service = make_service(
        order=order,
        subscription_repository=repository,
        vpn_access_service=vpn_access,
    )

    with pytest.raises(RuntimeError, match="create_access failed"):
        await service.activate_or_extend_by_order(order.id)

    assert order.status == OrderStatus.PAID
    assert order.activated_at is None
    assert repository.create_calls == []
    assert repository.activate_calls == []
    assert repository.mark_access_sent_calls == []
    assert vpn_access.create_calls == [{"user_id": 7, "device_limit": 1}]
    assert service.session.commit_count == 0
    assert service.session.rollback_count == 1
    assert FakeSubscriptionMetaSyncService.calls == []

@pytest.mark.asyncio
async def test_metadata_sync_failure_after_commit_does_not_rollback_paid_activation():
    order = make_order(order_id=23, user_id=7, status=OrderStatus.PAID)
    repository = FakeSubscriptionRepository(active_subscription=None)
    service = make_service(
        order=order,
        subscription_repository=repository,
        vpn_access_service=FakeVpnAccessService(),
    )
    FakeSubscriptionMetaSyncService.result = SimpleNamespace(
        ok=False,
        error="scp unavailable",
    )

    subscription, config_uri = await service.activate_or_extend_by_order(order.id)

    assert subscription.status == SubscriptionStatus.ACTIVE
    assert order.status == OrderStatus.ACTIVATED
    assert config_uri == "https://connect/new-vpn-uuid"
    assert service.session.commit_count == 1
    assert service.session.rollback_count == 0
    assert len(FakeSubscriptionMetaSyncService.calls) == 1
