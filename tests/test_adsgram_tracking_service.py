from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.adsgram_tracking_service import (
    ADSGRAM_GOAL_REGISTRATION,
    AdsGramTrackingService,
    normalize_adsgram_campaign_id,
)
from sqlalchemy.exc import IntegrityError

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
        self.lock_calls: list[int] = []
        self.get_calls: list[int] = []
        self.set_calls: list[dict] = []

    async def get_by_telegram_id_for_update(
        self,
        telegram_id: int,
    ):
        self.lock_calls.append(telegram_id)
        return self.user

    async def get_by_telegram_id(
        self,
        telegram_id: int,
    ):
        self.get_calls.append(telegram_id)
        return self.user

    async def set_adsgram_attribution(
        self,
        user,
        *,
        campaign_id: str,
        attributed_at,
    ):
        self.set_calls.append(
            {
                "user_id": user.id,
                "campaign_id": campaign_id,
                "attributed_at": attributed_at,
            }
        )

        user.adsgram_campaign_id = campaign_id
        user.adsgram_attributed_at = attributed_at
        return user


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

class IntegrityFailingConversionRepository(
    FakeConversionRepository
):
    async def create_pending(self, **kwargs):
        self.create_calls.append(kwargs)

        raise IntegrityError(
            "INSERT INTO adsgram_conversions",
            {},
            RuntimeError("constraint failure"),
        )

@pytest.mark.asyncio
async def test_integrity_error_without_registration_conversion_is_not_silently_accepted():
    user = make_user(
        campaign_id="campaign_42"
    )
    session = FakeSession()
    users = FakeUserRepository(user)
    conversions = (
        IntegrityFailingConversionRepository()
    )

    service = AdsGramTrackingService(
        session,
        user_repository=users,
        conversion_repository=conversions,
    )

    with pytest.raises(IntegrityError):
        await service.capture_start_attribution(
            telegram_id=user.telegram_id,
            campaign_id="campaign_42",
            enqueue_registration=True,
        )

    assert conversions.get_calls == [
        "registration:user:7",
        "registration:user:7",
    ]

    assert len(conversions.create_calls) == 1

    assert session.commit_count == 0
    assert session.rollback_count == 1


def make_user(*, campaign_id=None):
    return SimpleNamespace(
        id=7,
        telegram_id=123456,
        adsgram_campaign_id=campaign_id,
        adsgram_attributed_at=None,
    )


def make_service(*, user=None, conversion=None):
    session = FakeSession()
    user_repository = FakeUserRepository(user)
    conversion_repository = FakeConversionRepository(
        conversion
    )

    service = AdsGramTrackingService(
        session,
        user_repository=user_repository,
        conversion_repository=conversion_repository,
    )

    return (
        service,
        session,
        user_repository,
        conversion_repository,
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("123", "123"),
        (" campaign_42 ", "campaign_42"),
        ("campaign-42", "campaign-42"),
        (None, None),
        ("", None),
        ("contains space", None),
        ("bad/value", None),
        ("x" * 60, "x" * 60),
        ("x" * 61, None),
    ],
)
def test_normalize_adsgram_campaign_id(raw, expected):
    assert normalize_adsgram_campaign_id(raw) == expected


@pytest.mark.asyncio
async def test_capture_start_attribution_stores_first_touch_and_registration():
    user = make_user()

    service, session, users, conversions = (
        make_service(user=user)
    )

    result = await service.capture_start_attribution(
        telegram_id=user.telegram_id,
        campaign_id="campaign_42",
    )

    assert result.status == "attributed"
    assert result.user_id == user.id
    assert result.campaign_id == "campaign_42"
    assert result.conversion_id == 100

    assert users.lock_calls == [user.telegram_id]
    assert len(users.set_calls) == 1
    assert (
        users.set_calls[0]["campaign_id"]
        == "campaign_42"
    )

    assert conversions.get_calls == [
        "registration:user:7"
    ]
    assert conversions.create_calls == [
        {
            "user_id": 7,
            "campaign_id": "campaign_42",
            "goal_type": ADSGRAM_GOAL_REGISTRATION,
            "idempotency_key": "registration:user:7",
        }
    ]

    assert session.commit_count == 1
    assert session.rollback_count == 0

@pytest.mark.asyncio
async def test_capture_start_attribution_can_skip_registration_conversion():
    user = make_user()

    service, session, users, conversions = (
        make_service(user=user)
    )

    result = await service.capture_start_attribution(
        telegram_id=user.telegram_id,
        campaign_id="campaign_42",
        enqueue_registration=False,
    )

    assert (
        result.status
        == "attributed_without_registration"
    )
    assert result.user_id == user.id
    assert result.campaign_id == "campaign_42"
    assert result.conversion_id is None

    assert len(users.set_calls) == 1
    assert (
        users.set_calls[0]["campaign_id"]
        == "campaign_42"
    )

    assert conversions.get_calls == []
    assert conversions.create_calls == []

    assert session.commit_count == 1
    assert session.rollback_count == 0


@pytest.mark.asyncio
async def test_capture_start_attribution_does_not_overwrite_first_touch():
    user = make_user(
        campaign_id="original_campaign"
    )

    service, session, users, conversions = (
        make_service(user=user)
    )

    result = await service.capture_start_attribution(
        telegram_id=user.telegram_id,
        campaign_id="new_campaign",
        enqueue_registration=False,
    )

    assert result.status == "already_attributed"
    assert result.campaign_id == "original_campaign"

    assert users.set_calls == []
    assert conversions.get_calls == []
    assert conversions.create_calls == []

    assert session.commit_count == 1
    assert session.rollback_count == 0


@pytest.mark.asyncio
async def test_existing_attribution_ensures_registration_conversion_for_new_user():
    user = make_user(
        campaign_id="campaign_42"
    )

    service, session, users, conversions = (
        make_service(
            user=user,
            conversion=None,
        )
    )

    result = await service.capture_start_attribution(
        telegram_id=user.telegram_id,
        campaign_id="campaign_42",
        enqueue_registration=True,
    )

    assert result.status == "already_attributed"
    assert result.user_id == user.id
    assert result.campaign_id == "campaign_42"
    assert result.conversion_id is not None
    assert conversions.get_calls == [
        "registration:user:7"
    ]
    assert len(conversions.create_calls) == 1

    assert conversions.create_calls[0] == {
        "user_id": user.id,
        "campaign_id": "campaign_42",
        "goal_type": ADSGRAM_GOAL_REGISTRATION,
        "idempotency_key": (
            f"registration:user:{user.id}"
        ),
    }

    assert session.commit_count == 1


@pytest.mark.asyncio
async def test_capture_start_attribution_reuses_existing_registration_outbox():
    user = make_user()
    conversion = SimpleNamespace(id=88)

    service, session, users, conversions = (
        make_service(
            user=user,
            conversion=conversion,
        )
    )

    result = await service.capture_start_attribution(
        telegram_id=user.telegram_id,
        campaign_id="campaign_42",
    )

    assert result.status == "attributed"
    assert result.conversion_id == 88
    assert len(users.set_calls) == 1
    assert conversions.create_calls == []
    assert session.commit_count == 1


@pytest.mark.asyncio
async def test_capture_start_attribution_rejects_invalid_campaign_without_db_work():
    service, session, users, conversions = (
        make_service(user=make_user())
    )

    result = await service.capture_start_attribution(
        telegram_id=123456,
        campaign_id="bad campaign",
    )

    assert result.status == "invalid_campaign"
    assert users.lock_calls == []
    assert conversions.get_calls == []
    assert session.commit_count == 0
    assert session.rollback_count == 0


@pytest.mark.asyncio
async def test_capture_start_attribution_returns_user_not_found():
    service, session, users, conversions = (
        make_service(user=None)
    )

    result = await service.capture_start_attribution(
        telegram_id=123456,
        campaign_id="campaign_42",
    )

    assert result.status == "user_not_found"
    assert users.lock_calls == [123456]
    assert conversions.get_calls == []
    assert session.commit_count == 0
    assert session.rollback_count == 1