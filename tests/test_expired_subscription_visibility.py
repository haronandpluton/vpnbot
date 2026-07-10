from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, cast

import pytest
from sqlalchemy.dialects import postgresql

import app.bot.handlers.my_subscription as handler_module
from app.bot.handlers.my_subscription import my_subscription_command
from app.bot.keyboards.vpn_access import expired_subscription_keyboard
from app.bot.texts.vpn_access import (
    format_expired_vpn_subscription_text,
)
from app.database.repositories.subscriptions import SubscriptionRepository
from app.payment_core.enums.subscription_status import SubscriptionStatus
from app.services.my_subscription_service import MySubscriptionService


class FakeExecuteResult:
    def __init__(self, *, items=None) -> None:
        self.items = items or []

    def scalars(self):
        return SimpleNamespace(all=lambda: self.items)


class FakeRepositorySession:
    def __init__(self) -> None:
        self.execute_calls = []

    async def execute(self, statement):
        self.execute_calls.append(statement)
        return FakeExecuteResult()


class FakeSession:
    def __init__(self) -> None:
        self.commit_count = 0

    async def commit(self) -> None:
        self.commit_count += 1


class FakeUserRepository:
    def __init__(self, user) -> None:
        self.user = user

    async def get_by_telegram_id(self, telegram_id: int):
        return self.user


class FakeSubscriptionRepository:
    def __init__(self, subscriptions) -> None:
        self.subscriptions = subscriptions
        self.renewable_calls = []

    async def get_renewable_by_user(self, user_id: int):
        self.renewable_calls.append(user_id)
        return self.subscriptions


class FakeVpnAccessService:
    def __init__(self) -> None:
        self.get_config_calls = []

    async def get_config(self, **kwargs):
        self.get_config_calls.append(kwargs)
        raise AssertionError("Listing subscriptions must not get config")


class FakeMessage:
    def __init__(self) -> None:
        self.from_user = SimpleNamespace(id=777)
        self.answer_calls = []

    async def answer(self, text: str, **kwargs) -> None:
        self.answer_calls.append({"text": text, **kwargs})


class FakeHandlerService:
    result = None

    def __init__(self, session) -> None:
        self.session = session

    async def get_active_subscriptions_by_telegram_id(
        self,
        *,
        telegram_id: int,
    ):
        assert telegram_id == 777
        return self.__class__.result


def make_subscription(
    *,
    subscription_id: int,
    status: SubscriptionStatus,
    expires_at: datetime,
):
    return SimpleNamespace(
        id=subscription_id,
        user_id=7,
        status=status,
        expires_at=expires_at,
        device_limit=1,
    )


def make_service(subscriptions):
    service = MySubscriptionService.__new__(MySubscriptionService)
    service.session = FakeSession()
    service.user_repository = FakeUserRepository(
        SimpleNamespace(id=7, telegram_id=777)
    )
    service.subscription_repository = FakeSubscriptionRepository(
        subscriptions
    )
    service.vpn_access_service = FakeVpnAccessService()
    return service


def row_callbacks(markup):
    return [
        [button.callback_data for button in row]
        for row in markup.inline_keyboard
    ]


@pytest.mark.asyncio
async def test_repository_renewable_query_includes_only_active_and_expired():
    session = FakeRepositorySession()
    repository = SubscriptionRepository(cast(Any, session))

    await repository.get_renewable_by_user(7)

    statement = session.execute_calls[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    sql = str(compiled)
    params = compiled.params

    assert "subscriptions.user_id =" in sql
    assert "subscriptions.status IN" in sql

    status_values = next(
        value
        for value in params.values()
        if isinstance(value, list)
    )
    assert set(status_values) == {
        SubscriptionStatus.ACTIVE,
        SubscriptionStatus.EXPIRED,
    }


@pytest.mark.asyncio
async def test_subscription_list_contains_active_and_expired_but_not_disabled():
    now = datetime.now(timezone.utc)
    active = make_subscription(
        subscription_id=10,
        status=SubscriptionStatus.ACTIVE,
        expires_at=now + timedelta(days=5),
    )
    expired = make_subscription(
        subscription_id=20,
        status=SubscriptionStatus.EXPIRED,
        expires_at=now - timedelta(days=1),
    )
    disabled = make_subscription(
        subscription_id=30,
        status=SubscriptionStatus.DISABLED,
        expires_at=now + timedelta(days=30),
    )
    service = make_service([expired, disabled, active])

    result = await service.get_active_subscriptions_by_telegram_id(777)

    assert result.status == "active"
    assert [
        (item.subscription_id, item.status)
        for item in result.subscriptions
    ] == [
        (10, "active"),
        (20, "subscription_expired"),
    ]
    assert service.subscription_repository.renewable_calls == [7]
    assert service.vpn_access_service.get_config_calls == []
    assert service.session.commit_count == 0


@pytest.mark.asyncio
async def test_active_row_with_past_expiry_is_shown_as_expired():
    now = datetime.now(timezone.utc)
    stale_active = make_subscription(
        subscription_id=40,
        status=SubscriptionStatus.ACTIVE,
        expires_at=now - timedelta(seconds=1),
    )
    service = make_service([stale_active])

    result = await service.get_active_subscriptions_by_telegram_id(777)

    assert result.status == "active"
    assert len(result.subscriptions) == 1
    assert result.subscriptions[0].status == "subscription_expired"
    assert result.subscriptions[0].subscription_id == 40


@pytest.mark.asyncio
async def test_only_disabled_or_inactive_rows_are_not_displayed():
    now = datetime.now(timezone.utc)
    service = make_service(
        [
            make_subscription(
                subscription_id=50,
                status=SubscriptionStatus.DISABLED,
                expires_at=now,
            ),
            make_subscription(
                subscription_id=60,
                status=SubscriptionStatus.INACTIVE,
                expires_at=now,
            ),
        ]
    )

    result = await service.get_active_subscriptions_by_telegram_id(777)

    assert result.status == "subscription_not_found"
    assert result.subscriptions == ()


@pytest.mark.asyncio
async def test_handler_renders_expired_card_without_access_buttons(
    monkeypatch,
):
    expires_at = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    FakeHandlerService.result = SimpleNamespace(
        status="active",
        subscriptions=(
            SimpleNamespace(
                status="subscription_expired",
                subscription_id=50,
                device_limit=1,
                expires_at=expires_at,
            ),
        ),
    )
    monkeypatch.setattr(
        handler_module,
        "MySubscriptionService",
        FakeHandlerService,
    )
    message = FakeMessage()

    await my_subscription_command(message, session="session")

    assert len(message.answer_calls) == 1
    card = message.answer_calls[0]
    assert "Your VPN subscription has expired." in card["text"]
    assert "Was active until: 01.07.2026 12:00" in card["text"]
    assert row_callbacks(card["reply_markup"]) == [
        ["renew_subscription:50"]
    ]


def test_expired_subscription_keyboard_contains_only_renewal():
    markup = expired_subscription_keyboard(subscription_id=303)

    assert row_callbacks(markup) == [
        ["renew_subscription:303"]
    ]
    assert [
        [button.text for button in row]
        for row in markup.inline_keyboard
    ] == [["Renew Subscription"]]


def test_expired_subscription_text_explains_same_key_renewal():
    text = format_expired_vpn_subscription_text(
        device_limit=1,
        expires_at=datetime(
            2026,
            7,
            1,
            12,
            0,
            tzinfo=timezone.utc,
        ),
    )

    assert "Your VPN subscription has expired." in text
    assert "Devices: 1" in text
    assert "Was active until: 01.07.2026 12:00" in text
    assert "with the same VPN key" in text
