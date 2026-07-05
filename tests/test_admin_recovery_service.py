from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.payment_core.enums.subscription_status import SubscriptionStatus
from app.services.admin_recovery_service import AdminRecoveryService


class FakeSession:
    def __init__(self) -> None:
        self.commit_count = 0

    async def commit(self) -> None:
        self.commit_count += 1


class FakeVpnAccessService:
    def __init__(self, *, fail_get_config: bool = False) -> None:
        self.fail_get_config = fail_get_config
        self.get_config_calls: list[dict] = []

    async def get_config(self, *, uuid: str, device_limit: int):
        self.get_config_calls.append({"uuid": uuid, "device_limit": device_limit})

        if self.fail_get_config:
            raise RuntimeError("get_config failed")

        return f"https://connect/{uuid}"


def make_order(*, order_id: int = 23, user_id: int = 7):
    return SimpleNamespace(
        id=order_id,
        user_id=user_id,
    )


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


def make_subscription(
    *,
    subscription_id: int = 50,
    status: SubscriptionStatus = SubscriptionStatus.ACTIVE,
    uuid: str = "test-uuid",
    device_limit: int = 2,
    expires_at=None,
):
    return SimpleNamespace(
        id=subscription_id,
        status=status,
        uuid=uuid,
        device_limit=device_limit,
        expires_at=expires_at
        if expires_at is not None
        else datetime.now(timezone.utc) + timedelta(days=10),
        last_access_sent_at=None,
    )


def make_service(
    *,
    order=None,
    user=None,
    subscription=None,
    vpn_access_service: FakeVpnAccessService | None = None,
):
    service = AdminRecoveryService.__new__(AdminRecoveryService)
    service.session = FakeSession()
    service.vpn_access_service = vpn_access_service or FakeVpnAccessService()
    service._get_order = lambda order_id: _return_order(order, order_id)
    service._get_user = lambda user_id: _return_user(user, user_id)
    service._get_latest_subscription_by_order_id = (
        lambda order_id: _return_subscription_by_order_id(subscription, order_id)
    )
    return service


async def _return_order(order, order_id: int):
    if order is None:
        return None

    if order.id != order_id:
        return None

    return order


async def _return_user(user, user_id: int):
    if user is None:
        return None

    if user.id != user_id:
        return None

    return user


async def _return_subscription_by_order_id(subscription, order_id: int):
    return subscription


@pytest.mark.asyncio
async def test_prepare_resend_config_returns_order_not_found_without_commit_or_vpn_call():
    vpn_access = FakeVpnAccessService()
    service = make_service(
        order=None,
        user=make_user(),
        subscription=make_subscription(),
        vpn_access_service=vpn_access,
    )

    result = await service.prepare_resend_config(order_id=404)

    assert result.status == "order_not_found"
    assert result.order_id == 404
    assert result.user_id is None
    assert result.telegram_id is None
    assert result.username is None
    assert result.subscription_id is None
    assert result.config_uri is None
    assert result.message == "Order not found."
    assert vpn_access.get_config_calls == []
    assert service.session.commit_count == 0


@pytest.mark.asyncio
async def test_prepare_resend_config_returns_user_not_found_without_commit_or_vpn_call():
    order = make_order(order_id=23, user_id=7)
    vpn_access = FakeVpnAccessService()
    service = make_service(
        order=order,
        user=None,
        subscription=make_subscription(),
        vpn_access_service=vpn_access,
    )

    result = await service.prepare_resend_config(order_id=23)

    assert result.status == "user_not_found"
    assert result.order_id == 23
    assert result.user_id == 7
    assert result.telegram_id is None
    assert result.username is None
    assert result.subscription_id is None
    assert result.config_uri is None
    assert result.message == "User not found."
    assert vpn_access.get_config_calls == []
    assert service.session.commit_count == 0


@pytest.mark.asyncio
async def test_prepare_resend_config_returns_subscription_not_found_without_commit_or_vpn_call():
    order = make_order(order_id=23, user_id=7)
    user = make_user(user_id=7, telegram_id=123456, username="ivan")
    vpn_access = FakeVpnAccessService()
    service = make_service(
        order=order,
        user=user,
        subscription=None,
        vpn_access_service=vpn_access,
    )

    result = await service.prepare_resend_config(order_id=23)

    assert result.status == "subscription_not_found"
    assert result.order_id == 23
    assert result.user_id == 7
    assert result.telegram_id == 123456
    assert result.username == "ivan"
    assert result.subscription_id is None
    assert result.config_uri is None
    assert result.message == "Subscription not found."
    assert vpn_access.get_config_calls == []
    assert service.session.commit_count == 0


@pytest.mark.asyncio
async def test_prepare_resend_config_rejects_non_active_subscription_without_commit_or_vpn_call():
    order = make_order(order_id=23, user_id=7)
    user = make_user(user_id=7, telegram_id=123456, username="ivan")
    subscription = make_subscription(
        subscription_id=50,
        status=SubscriptionStatus.DISABLED,
        uuid="disabled-uuid",
        expires_at=datetime.now(timezone.utc) + timedelta(days=10),
    )
    vpn_access = FakeVpnAccessService()
    service = make_service(
        order=order,
        user=user,
        subscription=subscription,
        vpn_access_service=vpn_access,
    )

    result = await service.prepare_resend_config(order_id=23)

    assert result.status == "subscription_not_active"
    assert result.order_id == 23
    assert result.user_id == 7
    assert result.telegram_id == 123456
    assert result.username == "ivan"
    assert result.subscription_id == 50
    assert result.subscription_status == "disabled"
    assert result.expires_at == subscription.expires_at
    assert result.config_uri is None
    assert result.message == "Subscription is not active."
    assert vpn_access.get_config_calls == []
    assert service.session.commit_count == 0


@pytest.mark.asyncio
async def test_prepare_resend_config_rejects_expired_active_subscription_without_commit_or_vpn_call():
    order = make_order(order_id=23, user_id=7)
    user = make_user(user_id=7, telegram_id=123456, username="ivan")
    subscription = make_subscription(
        subscription_id=50,
        status=SubscriptionStatus.ACTIVE,
        uuid="expired-uuid",
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    )
    vpn_access = FakeVpnAccessService()
    service = make_service(
        order=order,
        user=user,
        subscription=subscription,
        vpn_access_service=vpn_access,
    )

    result = await service.prepare_resend_config(order_id=23)

    assert result.status == "subscription_expired"
    assert result.order_id == 23
    assert result.user_id == 7
    assert result.telegram_id == 123456
    assert result.username == "ivan"
    assert result.subscription_id == 50
    assert result.subscription_status == "active"
    assert result.expires_at == subscription.expires_at
    assert result.config_uri is None
    assert result.message == "Subscription expired."
    assert vpn_access.get_config_calls == []
    assert service.session.commit_count == 0


@pytest.mark.asyncio
async def test_prepare_resend_config_for_active_subscription_returns_config_and_updates_access_sent_time():
    order = make_order(order_id=23, user_id=7)
    user = make_user(user_id=7, telegram_id=123456, username="ivan")
    subscription = make_subscription(
        subscription_id=50,
        status=SubscriptionStatus.ACTIVE,
        uuid="active-uuid",
        device_limit=3,
        expires_at=datetime.now(timezone.utc) + timedelta(days=10),
    )
    vpn_access = FakeVpnAccessService()
    service = make_service(
        order=order,
        user=user,
        subscription=subscription,
        vpn_access_service=vpn_access,
    )

    before_call = datetime.now(timezone.utc)
    result = await service.prepare_resend_config(order_id=23)
    after_call = datetime.now(timezone.utc)

    assert result.status == "ready"
    assert result.order_id == 23
    assert result.user_id == 7
    assert result.telegram_id == 123456
    assert result.username == "ivan"
    assert result.subscription_id == 50
    assert result.subscription_status == "active"
    assert result.expires_at == subscription.expires_at
    assert result.config_uri == "https://connect/active-uuid"
    assert result.message == "Config prepared."

    assert subscription.last_access_sent_at is not None
    assert subscription.last_access_sent_at >= before_call
    assert subscription.last_access_sent_at <= after_call

    assert vpn_access.get_config_calls == [
        {"uuid": "active-uuid", "device_limit": 3}
    ]
    assert service.session.commit_count == 1


@pytest.mark.asyncio
async def test_prepare_resend_config_allows_active_subscription_without_expires_at():
    order = make_order(order_id=23, user_id=7)
    user = make_user(user_id=7, telegram_id=123456, username=None)
    subscription = make_subscription(
        subscription_id=50,
        status=SubscriptionStatus.ACTIVE,
        uuid="no-expiry-uuid",
        device_limit=1,
    )
    subscription.expires_at = None
    vpn_access = FakeVpnAccessService()
    service = make_service(
        order=order,
        user=user,
        subscription=subscription,
        vpn_access_service=vpn_access,
    )

    result = await service.prepare_resend_config(order_id=23)

    assert result.status == "ready"
    assert result.username is None
    assert result.expires_at is None
    assert result.config_uri == "https://connect/no-expiry-uuid"
    assert subscription.last_access_sent_at is not None
    assert vpn_access.get_config_calls == [
        {"uuid": "no-expiry-uuid", "device_limit": 1}
    ]
    assert service.session.commit_count == 1


@pytest.mark.asyncio
async def test_prepare_resend_config_propagates_vpn_error_without_commit_or_access_sent_update():
    order = make_order(order_id=23, user_id=7)
    user = make_user(user_id=7, telegram_id=123456, username="ivan")
    subscription = make_subscription(
        subscription_id=50,
        status=SubscriptionStatus.ACTIVE,
        uuid="fail-uuid",
        device_limit=2,
        expires_at=datetime.now(timezone.utc) + timedelta(days=10),
    )
    vpn_access = FakeVpnAccessService(fail_get_config=True)
    service = make_service(
        order=order,
        user=user,
        subscription=subscription,
        vpn_access_service=vpn_access,
    )

    with pytest.raises(RuntimeError, match="get_config failed"):
        await service.prepare_resend_config(order_id=23)

    assert vpn_access.get_config_calls == [
        {"uuid": "fail-uuid", "device_limit": 2}
    ]
    assert subscription.last_access_sent_at is None
    assert service.session.commit_count == 0


def test_enum_to_str_handles_none_enum_and_plain_string():
    assert AdminRecoveryService._enum_to_str(None) is None
    assert AdminRecoveryService._enum_to_str(SubscriptionStatus.ACTIVE) == "active"
    assert AdminRecoveryService._enum_to_str("custom") == "custom"