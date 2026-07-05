from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, cast

import pytest

from app.common.enums import CurrencyCode, NetworkCode
from app.database.models import PaymentOption, Subscription, User
from app.database.repositories.payment_options import PaymentOptionRepository
from app.database.repositories.subscriptions import SubscriptionRepository
from app.database.repositories.users import UserRepository
from app.payment_core.enums.payment_method import PaymentMethod
from app.payment_core.enums.subscription_status import SubscriptionStatus


class FakeScalarResult:
    def __init__(self, items) -> None:
        self.items = items

    def all(self):
        return self.items


class FakeExecuteResult:
    def __init__(self, *, scalar_value=None, items=None) -> None:
        self.scalar_value = scalar_value
        self.items = items or []

    def scalar_one_or_none(self):
        return self.scalar_value

    def scalars(self):
        return FakeScalarResult(self.items)


class FakeSession:
    def __init__(self, *, scalar_value=None, items=None, fail_flush: bool = False) -> None:
        self.scalar_value = scalar_value
        self.items = items or []
        self.fail_flush = fail_flush
        self.execute_calls = []
        self.add_calls = []
        self.flush_count = 0
        self.next_id = 900

    async def execute(self, stmt):
        self.execute_calls.append(stmt)
        return FakeExecuteResult(scalar_value=self.scalar_value, items=self.items)

    def add(self, obj) -> None:
        self.add_calls.append(obj)

    async def flush(self) -> None:
        self.flush_count += 1

        if self.fail_flush:
            raise RuntimeError("flush failed")

        for obj in self.add_calls:
            if getattr(obj, "id", None) is None:
                obj.id = self.next_id
                self.next_id += 1


def make_user(*, user_id: int = 7):
    return SimpleNamespace(
        id=user_id,
        telegram_id=123456,
        username="old_username",
        first_name="Old",
        last_name="Name",
        language_code="ru",
        is_admin=False,
    )


def make_payment_option(*, payment_option_id: int = 5):
    return SimpleNamespace(
        id=payment_option_id,
        code="usdt_trc20",
        payment_method=PaymentMethod.CRYPTO,
        currency=CurrencyCode.USDT,
        network=NetworkCode.TRC20,
        display_name="USDT TRC20",
        is_active=True,
        sort_order=10,
    )


def make_subscription(
    *,
    subscription_id: int = 50,
    status: SubscriptionStatus = SubscriptionStatus.INACTIVE,
):
    return SimpleNamespace(
        id=subscription_id,
        user_id=7,
        order_id=23,
        vpn_server_id=3,
        status=status,
        uuid="uuid-1",
        device_limit=2,
        starts_at=datetime(2026, 7, 1, 12, 0, tzinfo=UTC),
        expires_at=datetime(2026, 8, 1, 12, 0, tzinfo=UTC),
        last_access_sent_at=None,
        disabled_at=None,
        error_reason="old_error",
    )


@pytest.mark.asyncio
async def test_user_repository_get_by_id_returns_scalar_user():
    user = make_user(user_id=7)
    session = FakeSession(scalar_value=user)
    repository = UserRepository(cast(Any, session))

    result = await repository.get_by_id(7)

    assert result is user
    assert len(session.execute_calls) == 1


@pytest.mark.asyncio
async def test_user_repository_get_by_telegram_id_returns_scalar_user():
    user = make_user(user_id=7)
    session = FakeSession(scalar_value=user)
    repository = UserRepository(cast(Any, session))

    result = await repository.get_by_telegram_id(123456)

    assert result is user
    assert len(session.execute_calls) == 1


@pytest.mark.asyncio
async def test_user_repository_create_adds_user_flushes_and_returns_user():
    session = FakeSession()
    repository = UserRepository(cast(Any, session))

    user = await repository.create(
        telegram_id=123456,
        username="ivan",
        first_name="Ivan",
        last_name="Redeemer",
        language_code="ru",
        is_admin=True,
    )

    assert isinstance(user, User)
    assert user.id == 900
    assert user.telegram_id == 123456
    assert user.username == "ivan"
    assert user.first_name == "Ivan"
    assert user.last_name == "Redeemer"
    assert user.language_code == "ru"
    assert user.is_admin is True
    assert session.add_calls == [user]
    assert session.flush_count == 1


@pytest.mark.asyncio
async def test_user_repository_create_propagates_flush_error_without_fake_success():
    session = FakeSession(fail_flush=True)
    repository = UserRepository(cast(Any, session))

    with pytest.raises(RuntimeError, match="flush failed"):
        await repository.create(telegram_id=123456, username="ivan")

    assert len(session.add_calls) == 1
    assert session.flush_count == 1


@pytest.mark.asyncio
async def test_user_repository_update_basic_info_overwrites_public_profile_fields():
    user = make_user(user_id=7)
    session = FakeSession()
    repository = UserRepository(cast(Any, session))

    result = await repository.update_basic_info(
        user,
        username="new_username",
        first_name="New",
        last_name="User",
        language_code="en",
    )

    assert result is user
    assert user.username == "new_username"
    assert user.first_name == "New"
    assert user.last_name == "User"
    assert user.language_code == "en"
    assert user.is_admin is False
    assert session.flush_count == 1


@pytest.mark.asyncio
async def test_payment_option_repository_get_by_id_returns_scalar_option():
    option = make_payment_option(payment_option_id=5)
    session = FakeSession(scalar_value=option)
    repository = PaymentOptionRepository(cast(Any, session))

    result = await repository.get_by_id(5)

    assert result is option
    assert len(session.execute_calls) == 1


@pytest.mark.asyncio
async def test_payment_option_repository_get_by_code_returns_scalar_option():
    option = make_payment_option(payment_option_id=5)
    session = FakeSession(scalar_value=option)
    repository = PaymentOptionRepository(cast(Any, session))

    result = await repository.get_by_code("usdt_trc20")

    assert result is option
    assert len(session.execute_calls) == 1


@pytest.mark.asyncio
async def test_payment_option_repository_get_active_returns_scalar_list():
    options = [
        make_payment_option(payment_option_id=1),
        make_payment_option(payment_option_id=2),
    ]
    session = FakeSession(items=options)
    repository = PaymentOptionRepository(cast(Any, session))

    result = await repository.get_active()

    assert result == options
    assert len(session.execute_calls) == 1


@pytest.mark.asyncio
async def test_payment_option_repository_create_adds_option_and_flushes():
    session = FakeSession()
    repository = PaymentOptionRepository(cast(Any, session))

    option = await repository.create(
        code="usdt_trc20",
        payment_method=PaymentMethod.CRYPTO,
        currency=CurrencyCode.USDT,
        network=NetworkCode.TRC20,
        display_name="USDT TRC20",
        is_active=True,
        sort_order=10,
    )

    assert isinstance(option, PaymentOption)
    assert option.id == 900
    assert option.code == "usdt_trc20"
    assert option.payment_method == PaymentMethod.CRYPTO
    assert option.currency == CurrencyCode.USDT
    assert option.network == NetworkCode.TRC20
    assert option.display_name == "USDT TRC20"
    assert option.is_active is True
    assert option.sort_order == 10
    assert session.add_calls == [option]
    assert session.flush_count == 1


@pytest.mark.asyncio
async def test_payment_option_repository_create_allows_stars_without_currency_or_network():
    session = FakeSession()
    repository = PaymentOptionRepository(cast(Any, session))

    option = await repository.create(
        code="telegram_stars",
        payment_method=PaymentMethod.TELEGRAM_STARS,
        currency=None,
        network=None,
        display_name="Telegram Stars",
        is_active=False,
        sort_order=99,
    )

    assert option.code == "telegram_stars"
    assert option.payment_method == PaymentMethod.TELEGRAM_STARS
    assert option.currency is None
    assert option.network is None
    assert option.is_active is False
    assert option.sort_order == 99
    assert session.flush_count == 1


@pytest.mark.asyncio
async def test_payment_option_repository_update_from_config_overwrites_option_fields():
    option = make_payment_option(payment_option_id=5)
    session = FakeSession()
    repository = PaymentOptionRepository(cast(Any, session))

    result = await repository.update_from_config(
        option,
        payment_method=PaymentMethod.TELEGRAM_STARS,
        currency=None,
        network=None,
        display_name="Telegram Stars",
        is_active=False,
        sort_order=1,
    )

    assert result is option
    assert option.payment_method == PaymentMethod.TELEGRAM_STARS
    assert option.currency is None
    assert option.network is None
    assert option.display_name == "Telegram Stars"
    assert option.is_active is False
    assert option.sort_order == 1
    assert session.flush_count == 1


@pytest.mark.asyncio
async def test_payment_option_repository_update_from_config_propagates_flush_error_after_field_change():
    option = make_payment_option(payment_option_id=5)
    session = FakeSession(fail_flush=True)
    repository = PaymentOptionRepository(cast(Any, session))

    with pytest.raises(RuntimeError, match="flush failed"):
        await repository.update_from_config(
            option,
            payment_method=PaymentMethod.CRYPTO,
            currency=CurrencyCode.USDC,
            network=NetworkCode.POLYGON,
            display_name="USDC Polygon",
            is_active=True,
            sort_order=2,
        )

    assert option.currency == CurrencyCode.USDC
    assert option.network == NetworkCode.POLYGON
    assert option.display_name == "USDC Polygon"
    assert session.flush_count == 1


@pytest.mark.asyncio
async def test_subscription_repository_get_by_id_returns_scalar_subscription():
    subscription = make_subscription(subscription_id=50)
    session = FakeSession(scalar_value=subscription)
    repository = SubscriptionRepository(cast(Any, session))

    result = await repository.get_by_id(50)

    assert result is subscription
    assert len(session.execute_calls) == 1


@pytest.mark.asyncio
async def test_subscription_repository_get_by_order_id_returns_latest_scalar_subscription():
    subscription = make_subscription(subscription_id=50)
    session = FakeSession(scalar_value=subscription)
    repository = SubscriptionRepository(cast(Any, session))

    result = await repository.get_by_order_id(23)

    assert result is subscription
    assert len(session.execute_calls) == 1


@pytest.mark.asyncio
async def test_subscription_repository_get_active_by_user_returns_scalar_list():
    subscriptions = [
        make_subscription(subscription_id=1, status=SubscriptionStatus.ACTIVE),
        make_subscription(subscription_id=2, status=SubscriptionStatus.ACTIVE),
    ]
    session = FakeSession(items=subscriptions)
    repository = SubscriptionRepository(cast(Any, session))

    result = await repository.get_active_by_user(7)

    assert result == subscriptions
    assert len(session.execute_calls) == 1


@pytest.mark.asyncio
async def test_subscription_repository_get_active_subscription_by_user_id_returns_scalar_subscription():
    subscription = make_subscription(subscription_id=50, status=SubscriptionStatus.ACTIVE)
    session = FakeSession(scalar_value=subscription)
    repository = SubscriptionRepository(cast(Any, session))

    result = await repository.get_active_subscription_by_user_id(7)

    assert result is subscription
    assert len(session.execute_calls) == 1


@pytest.mark.asyncio
async def test_subscription_repository_create_adds_inactive_subscription_and_flushes():
    starts_at = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
    expires_at = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
    session = FakeSession()
    repository = SubscriptionRepository(cast(Any, session))

    subscription = await repository.create(
        user_id=7,
        order_id=23,
        vpn_server_id=3,
        uuid="uuid-1",
        device_limit=2,
        starts_at=starts_at,
        expires_at=expires_at,
    )

    assert isinstance(subscription, Subscription)
    assert subscription.id == 900
    assert subscription.user_id == 7
    assert subscription.order_id == 23
    assert subscription.vpn_server_id == 3
    assert subscription.status == SubscriptionStatus.INACTIVE
    assert subscription.uuid == "uuid-1"
    assert subscription.device_limit == 2
    assert subscription.starts_at == starts_at
    assert subscription.expires_at == expires_at
    assert session.add_calls == [subscription]
    assert session.flush_count == 1


@pytest.mark.asyncio
async def test_subscription_repository_create_propagates_flush_error_without_fake_success():
    session = FakeSession(fail_flush=True)
    repository = SubscriptionRepository(cast(Any, session))

    with pytest.raises(RuntimeError, match="flush failed"):
        await repository.create(
            user_id=7,
            order_id=23,
            vpn_server_id=None,
            uuid="uuid-1",
            device_limit=1,
            starts_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(days=30),
        )

    assert len(session.add_calls) == 1
    assert session.flush_count == 1


@pytest.mark.asyncio
async def test_subscription_repository_activate_sets_active_and_clears_error_reason():
    subscription = make_subscription(status=SubscriptionStatus.INACTIVE)
    subscription.error_reason = "vpn_create_failed"
    session = FakeSession()
    repository = SubscriptionRepository(cast(Any, session))

    result = await repository.activate(subscription)

    assert result is subscription
    assert subscription.status == SubscriptionStatus.ACTIVE
    assert subscription.error_reason is None
    assert session.flush_count == 1


@pytest.mark.asyncio
async def test_subscription_repository_extend_updates_order_expiry_device_limit_and_reactivates():
    subscription = make_subscription(status=SubscriptionStatus.EXPIRED)
    new_expires_at = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
    session = FakeSession()
    repository = SubscriptionRepository(cast(Any, session))

    result = await repository.extend(
        subscription,
        order_id=99,
        expires_at=new_expires_at,
        device_limit=3,
    )

    assert result is subscription
    assert subscription.order_id == 99
    assert subscription.expires_at == new_expires_at
    assert subscription.device_limit == 3
    assert subscription.status == SubscriptionStatus.ACTIVE
    assert subscription.error_reason is None
    assert session.flush_count == 1


@pytest.mark.asyncio
async def test_subscription_repository_extend_keeps_existing_device_limit_when_not_provided():
    subscription = make_subscription(status=SubscriptionStatus.ACTIVE)
    old_device_limit = subscription.device_limit
    new_expires_at = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
    session = FakeSession()
    repository = SubscriptionRepository(cast(Any, session))

    result = await repository.extend(
        subscription,
        order_id=None,
        expires_at=new_expires_at,
        device_limit=None,
    )

    assert result is subscription
    assert subscription.order_id is None
    assert subscription.expires_at == new_expires_at
    assert subscription.device_limit == old_device_limit
    assert subscription.status == SubscriptionStatus.ACTIVE
    assert session.flush_count == 1


@pytest.mark.asyncio
async def test_subscription_repository_mark_access_sent_with_explicit_timestamp():
    subscription = make_subscription(status=SubscriptionStatus.ACTIVE)
    sent_at = datetime(2026, 7, 5, 12, 0, tzinfo=UTC)
    session = FakeSession()
    repository = SubscriptionRepository(cast(Any, session))

    result = await repository.mark_access_sent(subscription, sent_at=sent_at)

    assert result is subscription
    assert subscription.last_access_sent_at == sent_at
    assert session.flush_count == 1


@pytest.mark.asyncio
async def test_subscription_repository_mark_access_sent_uses_current_utc_time_when_not_provided():
    subscription = make_subscription(status=SubscriptionStatus.ACTIVE)
    session = FakeSession()
    repository = SubscriptionRepository(cast(Any, session))

    before_call = datetime.now(timezone.utc)
    result = await repository.mark_access_sent(subscription)
    after_call = datetime.now(timezone.utc)

    assert result is subscription
    assert subscription.last_access_sent_at >= before_call
    assert subscription.last_access_sent_at <= after_call
    assert session.flush_count == 1


@pytest.mark.asyncio
async def test_subscription_repository_mark_expired_sets_status_expired():
    subscription = make_subscription(status=SubscriptionStatus.ACTIVE)
    session = FakeSession()
    repository = SubscriptionRepository(cast(Any, session))

    result = await repository.mark_expired(subscription)

    assert result is subscription
    assert subscription.status == SubscriptionStatus.EXPIRED
    assert session.flush_count == 1


@pytest.mark.asyncio
async def test_subscription_repository_disable_sets_status_reason_and_disabled_timestamp():
    subscription = make_subscription(status=SubscriptionStatus.ACTIVE)
    session = FakeSession()
    repository = SubscriptionRepository(cast(Any, session))

    before_call = datetime.now(timezone.utc)
    result = await repository.disable(subscription, reason="manual block")
    after_call = datetime.now(timezone.utc)

    assert result is subscription
    assert subscription.status == SubscriptionStatus.DISABLED
    assert subscription.error_reason == "manual block"
    assert subscription.disabled_at >= before_call
    assert subscription.disabled_at <= after_call
    assert session.flush_count == 1
