from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.payment_core.enums.subscription_status import SubscriptionStatus
from app.services.my_subscription_service import MySubscriptionService


class FakeSession:
    def __init__(self) -> None:
        self.commit_count = 0

    async def commit(self) -> None:
        self.commit_count += 1


class FakeUserRepository:
    def __init__(self, user=None) -> None:
        self.user = user
        self.get_calls: list[int] = []

    async def get_by_telegram_id(self, telegram_id: int):
        self.get_calls.append(telegram_id)
        return self.user


class FakeSubscriptionRepository:
    def __init__(
        self,
        *,
        active_subscription=None,
        subscription_by_id=None,
        fail_mark_access_sent: bool = False,
    ) -> None:
        self.active_subscription = active_subscription
        self.subscription_by_id = subscription_by_id
        self.fail_mark_access_sent = fail_mark_access_sent
        self.get_active_calls: list[int] = []
        self.get_by_id_calls: list[int] = []
        self.mark_access_sent_calls: list[int] = []

    async def get_active_subscription_by_user_id(self, user_id: int):
        self.get_active_calls.append(user_id)
        return self.active_subscription

    async def get_by_id(self, subscription_id: int):
        self.get_by_id_calls.append(subscription_id)
        return self.subscription_by_id

    async def mark_access_sent(self, subscription):
        self.mark_access_sent_calls.append(subscription.id)

        if self.fail_mark_access_sent:
            raise RuntimeError("mark_access_sent failed")

        subscription.last_access_sent_at = datetime.now(timezone.utc)
        return subscription


class FakeVpnAccessService:
    def __init__(self, *, fail_get_config: bool = False) -> None:
        self.fail_get_config = fail_get_config
        self.get_config_calls: list[dict] = []

    async def get_config(self, *, uuid: str, device_limit: int):
        self.get_config_calls.append({"uuid": uuid, "device_limit": device_limit})

        if self.fail_get_config:
            raise RuntimeError("get_config failed")

        return f"https://connect/{uuid}"


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
    user_id: int = 7,
    status: SubscriptionStatus = SubscriptionStatus.ACTIVE,
    uuid: str = "test-uuid",
    device_limit: int = 2,
    expires_at=None,
):
    return SimpleNamespace(
        id=subscription_id,
        user_id=user_id,
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
    user=None,
    active_subscription=None,
    subscription_by_id=None,
    subscription_repository: FakeSubscriptionRepository | None = None,
    vpn_access_service: FakeVpnAccessService | None = None,
):
    service = MySubscriptionService.__new__(MySubscriptionService)
    service.session = FakeSession()
    service.user_repository = FakeUserRepository(user)
    service.subscription_repository = subscription_repository or FakeSubscriptionRepository(
        active_subscription=active_subscription,
        subscription_by_id=subscription_by_id,
    )
    service.vpn_access_service = vpn_access_service or FakeVpnAccessService()
    return service


@pytest.mark.asyncio
async def test_get_active_subscription_returns_user_not_found_without_commit_or_vpn_call():
    vpn_access = FakeVpnAccessService()
    service = make_service(
        user=None,
        vpn_access_service=vpn_access,
    )

    result = await service.get_active_subscription_by_telegram_id(123456)

    assert result.status == "user_not_found"
    assert result.user_id is None
    assert result.subscription_id is None
    assert result.config_uri is None
    assert result.message == "Пользователь не найден."
    assert vpn_access.get_config_calls == []
    assert service.session.commit_count == 0


@pytest.mark.asyncio
async def test_get_active_subscription_returns_subscription_not_found_without_commit_or_vpn_call():
    user = make_user(user_id=7, telegram_id=123456)
    vpn_access = FakeVpnAccessService()
    service = make_service(
        user=user,
        active_subscription=None,
        vpn_access_service=vpn_access,
    )

    result = await service.get_active_subscription_by_telegram_id(123456)

    assert result.status == "subscription_not_found"
    assert result.user_id == 7
    assert result.subscription_id is None
    assert result.config_uri is None
    assert result.message == "Активная подписка не найдена."
    assert vpn_access.get_config_calls == []
    assert service.session.commit_count == 0


@pytest.mark.asyncio
async def test_get_active_subscription_returns_subscription_not_active_without_commit_or_vpn_call():
    user = make_user(user_id=7, telegram_id=123456)
    subscription = make_subscription(
        subscription_id=50,
        user_id=7,
        status=SubscriptionStatus.DISABLED,
        uuid="disabled-uuid",
    )
    vpn_access = FakeVpnAccessService()
    service = make_service(
        user=user,
        active_subscription=subscription,
        vpn_access_service=vpn_access,
    )

    result = await service.get_active_subscription_by_telegram_id(123456)

    assert result.status == "subscription_not_active"
    assert result.user_id == 7
    assert result.subscription_id == 50
    assert result.subscription_status == "disabled"
    assert result.expires_at == subscription.expires_at
    assert result.device_limit == 2
    assert result.config_uri is None
    assert result.message == "Подписка не активна."
    assert vpn_access.get_config_calls == []
    assert service.session.commit_count == 0


@pytest.mark.asyncio
async def test_get_active_subscription_returns_subscription_expired_without_commit_or_vpn_call():
    user = make_user(user_id=7, telegram_id=123456)
    subscription = make_subscription(
        subscription_id=50,
        user_id=7,
        status=SubscriptionStatus.ACTIVE,
        uuid="expired-uuid",
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    )
    vpn_access = FakeVpnAccessService()
    service = make_service(
        user=user,
        active_subscription=subscription,
        vpn_access_service=vpn_access,
    )

    result = await service.get_active_subscription_by_telegram_id(123456)

    assert result.status == "subscription_expired"
    assert result.user_id == 7
    assert result.subscription_id == 50
    assert result.subscription_status == "active"
    assert result.expires_at == subscription.expires_at
    assert result.device_limit == 2
    assert result.config_uri is None
    assert result.message == "Срок подписки истек."
    assert vpn_access.get_config_calls == []
    assert service.session.commit_count == 0


@pytest.mark.asyncio
async def test_get_active_subscription_view_does_not_generate_config_or_commit():
    user = make_user(user_id=7, telegram_id=123456)
    subscription = make_subscription(
        subscription_id=50,
        user_id=7,
        status=SubscriptionStatus.ACTIVE,
        uuid="active-uuid",
        device_limit=3,
    )
    vpn_access = FakeVpnAccessService()
    service = make_service(
        user=user,
        active_subscription=subscription,
        vpn_access_service=vpn_access,
    )

    result = await service.get_active_subscription_by_telegram_id(123456)

    assert result.status == "active"
    assert result.user_id == 7
    assert result.subscription_id == 50
    assert result.subscription_status == "active"
    assert result.expires_at == subscription.expires_at
    assert result.device_limit == 3
    assert result.config_uri is None
    assert result.message == "Активная подписка найдена."
    assert subscription.last_access_sent_at is None
    assert vpn_access.get_config_calls == []
    assert service.session.commit_count == 0


@pytest.mark.asyncio
async def test_get_access_returns_inactive_result_without_requery_or_commit():
    user = make_user(user_id=7, telegram_id=123456)
    subscription = make_subscription(
        subscription_id=50,
        user_id=7,
        status=SubscriptionStatus.DISABLED,
        uuid="disabled-uuid",
    )
    subscription_repository = FakeSubscriptionRepository(
        active_subscription=subscription,
        subscription_by_id=subscription,
    )
    vpn_access = FakeVpnAccessService()
    service = make_service(
        user=user,
        subscription_repository=subscription_repository,
        vpn_access_service=vpn_access,
    )

    result = await service.get_access_by_telegram_id(123456)

    assert result.status == "subscription_not_active"
    assert result.subscription_id == 50
    assert result.config_uri is None
    assert subscription_repository.get_by_id_calls == []
    assert subscription_repository.mark_access_sent_calls == []
    assert vpn_access.get_config_calls == []
    assert service.session.commit_count == 0


@pytest.mark.asyncio
async def test_get_access_returns_subscription_not_found_if_subscription_disappeared_after_validation():
    user = make_user(user_id=7, telegram_id=123456)
    active_subscription = make_subscription(
        subscription_id=50,
        user_id=7,
        status=SubscriptionStatus.ACTIVE,
        uuid="active-uuid",
    )
    subscription_repository = FakeSubscriptionRepository(
        active_subscription=active_subscription,
        subscription_by_id=None,
    )
    vpn_access = FakeVpnAccessService()
    service = make_service(
        user=user,
        subscription_repository=subscription_repository,
        vpn_access_service=vpn_access,
    )

    result = await service.get_access_by_telegram_id(123456)

    assert result.status == "subscription_not_found"
    assert result.user_id == 7
    assert result.subscription_id is None
    assert result.config_uri is None
    assert result.message == "Активная подписка не найдена."
    assert subscription_repository.get_by_id_calls == [50]
    assert subscription_repository.mark_access_sent_calls == []
    assert vpn_access.get_config_calls == []
    assert service.session.commit_count == 0


@pytest.mark.asyncio
async def test_get_access_returns_existing_config_and_updates_last_access_sent_only():
    user = make_user(user_id=7, telegram_id=123456)
    old_expires_at = datetime.now(timezone.utc) + timedelta(days=10)
    subscription = make_subscription(
        subscription_id=50,
        user_id=7,
        status=SubscriptionStatus.ACTIVE,
        uuid="active-uuid",
        device_limit=3,
        expires_at=old_expires_at,
    )
    subscription_repository = FakeSubscriptionRepository(
        active_subscription=subscription,
        subscription_by_id=subscription,
    )
    vpn_access = FakeVpnAccessService()
    service = make_service(
        user=user,
        subscription_repository=subscription_repository,
        vpn_access_service=vpn_access,
    )

    before_call = datetime.now(timezone.utc)
    result = await service.get_access_by_telegram_id(123456)
    after_call = datetime.now(timezone.utc)

    assert result.status == "active"
    assert result.user_id == 7
    assert result.subscription_id == 50
    assert result.subscription_status == "active"
    assert result.expires_at == old_expires_at
    assert result.device_limit == 3
    assert result.config_uri == "https://connect/active-uuid"
    assert result.message == "Доступ отправлен повторно."

    assert subscription.uuid == "active-uuid"
    assert subscription.expires_at == old_expires_at
    assert subscription.last_access_sent_at is not None
    assert subscription.last_access_sent_at >= before_call
    assert subscription.last_access_sent_at <= after_call

    assert subscription_repository.get_by_id_calls == [50]
    assert subscription_repository.mark_access_sent_calls == [50]
    assert vpn_access.get_config_calls == [
        {"uuid": "active-uuid", "device_limit": 3}
    ]
    assert service.session.commit_count == 1


@pytest.mark.asyncio
async def test_get_access_propagates_vpn_error_without_marking_access_sent_or_commit():
    user = make_user(user_id=7, telegram_id=123456)
    subscription = make_subscription(
        subscription_id=50,
        user_id=7,
        status=SubscriptionStatus.ACTIVE,
        uuid="fail-uuid",
        device_limit=2,
    )
    subscription_repository = FakeSubscriptionRepository(
        active_subscription=subscription,
        subscription_by_id=subscription,
    )
    vpn_access = FakeVpnAccessService(fail_get_config=True)
    service = make_service(
        user=user,
        subscription_repository=subscription_repository,
        vpn_access_service=vpn_access,
    )

    with pytest.raises(RuntimeError, match="get_config failed"):
        await service.get_access_by_telegram_id(123456)

    assert subscription.last_access_sent_at is None
    assert subscription_repository.get_by_id_calls == [50]
    assert subscription_repository.mark_access_sent_calls == []
    assert vpn_access.get_config_calls == [{"uuid": "fail-uuid", "device_limit": 2}]
    assert service.session.commit_count == 0


@pytest.mark.asyncio
async def test_get_access_propagates_mark_access_sent_error_without_commit():
    user = make_user(user_id=7, telegram_id=123456)
    subscription = make_subscription(
        subscription_id=50,
        user_id=7,
        status=SubscriptionStatus.ACTIVE,
        uuid="mark-fail-uuid",
        device_limit=2,
    )
    subscription_repository = FakeSubscriptionRepository(
        active_subscription=subscription,
        subscription_by_id=subscription,
        fail_mark_access_sent=True,
    )
    vpn_access = FakeVpnAccessService()
    service = make_service(
        user=user,
        subscription_repository=subscription_repository,
        vpn_access_service=vpn_access,
    )

    with pytest.raises(RuntimeError, match="mark_access_sent failed"):
        await service.get_access_by_telegram_id(123456)

    assert subscription.last_access_sent_at is None
    assert subscription_repository.get_by_id_calls == [50]
    assert subscription_repository.mark_access_sent_calls == [50]
    assert vpn_access.get_config_calls == [
        {"uuid": "mark-fail-uuid", "device_limit": 2}
    ]
    assert service.session.commit_count == 0