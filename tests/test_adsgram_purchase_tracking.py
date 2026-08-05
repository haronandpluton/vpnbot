from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.adsgram_tracking_service import (
    ADSGRAM_GOAL_FIRST_PURCHASE,
    ADSGRAM_GOAL_REPEAT_PURCHASE,
    AdsGramTrackingService,
)


class FakeSession:
    def __init__(self) -> None:
        self.commit_count = 0
        self.rollback_count = 0

    async def commit(self) -> None:
        self.commit_count += 1

    async def rollback(self) -> None:
        self.rollback_count += 1


class FakeUserRepository:
    def __init__(self, user=None) -> None:
        self.user = user
        self.calls: list[int] = []

    async def get_by_id(self, user_id: int):
        self.calls.append(user_id)

        if self.user is None:
            return None

        if self.user.id != user_id:
            return None

        return self.user


class FakePaymentRepository:
    def __init__(
        self,
        first_confirmed_order_id=None,
    ) -> None:
        self.first_confirmed_order_id = (
            first_confirmed_order_id
        )
        self.calls: list[int] = []

    async def get_first_confirmed_order_id_by_user(
        self,
        user_id: int,
    ):
        self.calls.append(user_id)
        return self.first_confirmed_order_id


class FakeConversionRepository:
    def __init__(self, existing=None) -> None:
        self.existing = existing
        self.get_calls: list[str] = []
        self.create_calls: list[dict] = []
        self.next_id = 100

    async def get_by_idempotency_key(
        self,
        idempotency_key: str,
    ):
        self.get_calls.append(idempotency_key)
        return self.existing

    async def create_pending(self, **kwargs):
        self.create_calls.append(kwargs)

        conversion = SimpleNamespace(
            id=self.next_id,
            **kwargs,
        )
        self.next_id += 1
        self.existing = conversion
        return conversion


def make_user(*, campaign_id="campaign_42"):
    return SimpleNamespace(
        id=7,
        adsgram_campaign_id=campaign_id,
    )


def make_service(
    *,
    user=None,
    existing_conversion=None,
    first_confirmed_order_id=None,
):
    session = FakeSession()
    users = FakeUserRepository(user)
    payments = FakePaymentRepository(
        first_confirmed_order_id
    )
    conversions = FakeConversionRepository(
        existing_conversion
    )

    service = AdsGramTrackingService(
        session,
        user_repository=users,
        payment_repository=payments,
        conversion_repository=conversions,
    )

    return service, session, users, payments, conversions


@pytest.mark.asyncio
async def test_first_confirmed_order_creates_first_purchase_conversion():
    user = make_user()

    service, session, users, payments, conversions = (
        make_service(
            user=user,
            first_confirmed_order_id=23,
        )
    )

    result = await service.enqueue_purchase_conversion(
        user_id=user.id,
        order_id=23,
        payment_id=55,
    )

    assert result.status == "queued"
    assert result.goal_type == ADSGRAM_GOAL_FIRST_PURCHASE
    assert result.conversion_id == 100

    assert payments.calls == [user.id]

    assert conversions.create_calls == [
        {
            "user_id": user.id,
            "order_id": 23,
            "campaign_id": "campaign_42",
            "goal_type": ADSGRAM_GOAL_FIRST_PURCHASE,
            "idempotency_key": "purchase:order:23",
        }
    ]

    assert session.commit_count == 1
    assert session.rollback_count == 0


@pytest.mark.asyncio
async def test_later_confirmed_order_creates_repeat_purchase_conversion():
    user = make_user()

    service, session, users, payments, conversions = (
        make_service(
            user=user,
            first_confirmed_order_id=11,
        )
    )

    result = await service.enqueue_purchase_conversion(
        user_id=user.id,
        order_id=24,
        payment_id=56,
    )

    assert result.status == "queued"
    assert result.goal_type == ADSGRAM_GOAL_REPEAT_PURCHASE

    assert conversions.create_calls == [
        {
            "user_id": user.id,
            "order_id": 24,
            "campaign_id": "campaign_42",
            "goal_type": ADSGRAM_GOAL_REPEAT_PURCHASE,
            "idempotency_key": "purchase:order:24",
        }
    ]

    assert session.commit_count == 1


@pytest.mark.asyncio
async def test_unattributed_user_does_not_create_purchase_conversion():
    user = make_user(campaign_id=None)

    service, session, users, payments, conversions = (
        make_service(
            user=user,
            first_confirmed_order_id=23,
        )
    )

    result = await service.enqueue_purchase_conversion(
        user_id=user.id,
        order_id=23,
        payment_id=55,
    )

    assert result.status == "not_attributed"
    assert payments.calls == []
    assert conversions.get_calls == []
    assert conversions.create_calls == []
    assert session.commit_count == 1


@pytest.mark.asyncio
async def test_existing_order_conversion_is_reused():
    user = make_user()

    existing = SimpleNamespace(
        id=88,
        campaign_id="campaign_42",
        goal_type=ADSGRAM_GOAL_FIRST_PURCHASE,
    )

    service, session, users, payments, conversions = (
        make_service(
            user=user,
            existing_conversion=existing,
            first_confirmed_order_id=23,
        )
    )

    result = await service.enqueue_purchase_conversion(
        user_id=user.id,
        order_id=23,
        payment_id=55,
    )

    assert result.status == "already_queued"
    assert result.conversion_id == 88
    assert result.goal_type == ADSGRAM_GOAL_FIRST_PURCHASE

    assert payments.calls == []
    assert conversions.create_calls == []
    assert session.commit_count == 1


@pytest.mark.asyncio
async def test_purchase_is_not_queued_without_confirmed_payment():
    user = make_user()

    service, session, users, payments, conversions = (
        make_service(
            user=user,
            first_confirmed_order_id=None,
        )
    )

    result = await service.enqueue_purchase_conversion(
        user_id=user.id,
        order_id=23,
        payment_id=55,
    )

    assert result.status == "confirmed_payment_not_found"
    assert conversions.create_calls == []
    assert session.commit_count == 1