from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.services.trial_activation_service import (
    TRIAL_ACTIVATION_ERROR_TYPE,
    TrialActivationService,
)
from app.services.vpn_access_service import VpnAccessResult
from app.services.xui_client import XuiClientError


class FakeSession:
    def __init__(self) -> None:
        self.flush_count = 0
        self.commit_count = 0
        self.rollback_count = 0

    async def flush(self) -> None:
        self.flush_count += 1

    async def commit(self) -> None:
        self.commit_count += 1

    async def rollback(self) -> None:
        self.rollback_count += 1


class FakeUserRepository:
    def __init__(self, user=None) -> None:
        self.user = user
        self.lock_calls: list[int] = []

    async def get_by_telegram_id_for_update(
        self,
        telegram_id: int,
    ):
        self.lock_calls.append(telegram_id)
        return self.user


class FakeSubscriptionRepository:
    def __init__(self, *, fail_create: bool = False) -> None:
        self.fail_create = fail_create
        self.create_calls: list[dict] = []
        self.activate_calls = []
        self.mark_access_sent_calls: list[dict] = []

    async def create(self, **kwargs):
        self.create_calls.append(kwargs)

        if self.fail_create:
            raise RuntimeError("subscription create failed")

        return SimpleNamespace(
            id=77,
            **kwargs,
        )

    async def activate(self, subscription):
        self.activate_calls.append(subscription)
        return subscription

    async def mark_access_sent(
        self,
        subscription,
        sent_at=None,
    ):
        self.mark_access_sent_calls.append(
            {
                "subscription": subscription,
                "sent_at": sent_at,
            }
        )
        return subscription


class FakeVpnAccessService:
    def __init__(self, *, fail_create: bool = False) -> None:
        self.fail_create = fail_create
        self.create_calls: list[dict] = []

    async def create_access(
        self,
        user_id: int,
        device_limit: int,
        expires_at=None,
    ) -> VpnAccessResult:
        self.create_calls.append(
            {
                "user_id": user_id,
                "device_limit": device_limit,
                "expires_at": expires_at,
            }
        )

        if self.fail_create:
            raise XuiClientError(
                "3x-ui client creation failed: test failure"
            )

        return VpnAccessResult(
            uuid="12345678-1234-5678-1234-567812345678",
            vpn_server_id=None,
            config_uri=(
                "https://connect.example/connect/"
                "12345678-1234-5678-1234-567812345678"
            ),
        )


class FakeSystemErrorRepository:
    def __init__(self, *, pending=None) -> None:
        self.pending = pending
        self.get_calls: list[dict] = []
        self.create_calls: list[dict] = []
        self.update_calls: list[dict] = []
        self.resolve_calls = []

    async def get_unresolved_by_entity_and_error_type(
        self,
        *,
        entity_type: str,
        entity_id: int | None,
        error_type: str,
    ):
        self.get_calls.append(
            {
                "entity_type": entity_type,
                "entity_id": entity_id,
                "error_type": error_type,
            }
        )
        return self.pending

    async def create(self, **kwargs):
        self.create_calls.append(kwargs)
        return SimpleNamespace(id=500, **kwargs)

    async def update_pending_failure(
        self,
        error,
        **kwargs,
    ):
        self.update_calls.append(
            {
                "error": error,
                **kwargs,
            }
        )
        return error

    async def mark_resolved(self, error):
        self.resolve_calls.append(error)
        return error


class FakeMetadataSyncService:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def sync_safely(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(ok=True)


def make_user(*, eligible: bool = True):
    return SimpleNamespace(
        id=7,
        telegram_id=123456,
        trial_eligible=eligible,
        trial_claimed_at=None,
    )


def make_service(
    *,
    user=None,
    fail_vpn: bool = False,
    fail_subscription: bool = False,
    pending_error=None,
):
    session = FakeSession()
    user_repository = FakeUserRepository(user)
    subscription_repository = FakeSubscriptionRepository(
        fail_create=fail_subscription,
    )
    vpn_access_service = FakeVpnAccessService(
        fail_create=fail_vpn,
    )
    system_error_repository = FakeSystemErrorRepository(
        pending=pending_error,
    )
    metadata_sync_service = FakeMetadataSyncService()

    service = TrialActivationService(
        session,
        vpn_access_service=vpn_access_service,
        user_repository=user_repository,
        subscription_repository=subscription_repository,
        system_error_repository=system_error_repository,
        metadata_sync_service=metadata_sync_service,
    )

    return SimpleNamespace(
        service=service,
        session=session,
        user_repository=user_repository,
        subscription_repository=subscription_repository,
        vpn_access_service=vpn_access_service,
        system_error_repository=system_error_repository,
        metadata_sync_service=metadata_sync_service,
    )


@pytest.mark.asyncio
async def test_activate_trial_creates_three_day_subscription_and_consumes_eligibility():
    user = make_user()
    context = make_service(user=user)
    now = datetime(
        2030,
        1,
        1,
        12,
        0,
        tzinfo=timezone.utc,
    )
    expected_expires_at = datetime(
        2030,
        1,
        4,
        12,
        0,
        tzinfo=timezone.utc,
    )

    result = await context.service.activate_trial(
        telegram_id=123456,
        now=now,
    )

    assert result.status == "activated"
    assert result.subscription_id == 77
    assert result.expires_at == expected_expires_at
    assert result.config_uri.startswith(
        "https://connect.example/connect/"
    )

    assert context.user_repository.lock_calls == [123456]
    assert context.vpn_access_service.create_calls == [
        {
            "user_id": 7,
            "device_limit": 1,
            "expires_at": expected_expires_at,
        }
    ]

    assert context.subscription_repository.create_calls == [
        {
            "user_id": 7,
            "order_id": None,
            "vpn_server_id": None,
            "uuid": "12345678-1234-5678-1234-567812345678",
            "device_limit": 1,
            "starts_at": now,
            "expires_at": expected_expires_at,
            "is_trial": True,
        }
    ]

    assert user.trial_eligible is False
    assert user.trial_claimed_at == now
    assert context.session.flush_count == 1
    assert context.session.commit_count == 1

    assert len(context.metadata_sync_service.calls) == 1
    sync_call = context.metadata_sync_service.calls[0]
    assert sync_call["entity_type"] == "subscription"
    assert sync_call["entity_id"] == 77
    assert sync_call["reason"] == "trial_activation"
    assert sync_call["payload"]["is_trial"] is True


@pytest.mark.asyncio
async def test_activate_trial_returns_not_eligible_without_creating_access():
    user = make_user(eligible=False)
    context = make_service(user=user)

    result = await context.service.activate_trial(
        telegram_id=123456,
    )

    assert result.status == "not_eligible"
    assert result.subscription_id is None
    assert context.vpn_access_service.create_calls == []
    assert context.subscription_repository.create_calls == []
    assert context.session.commit_count == 0
    assert context.session.rollback_count == 1
    assert context.metadata_sync_service.calls == []


@pytest.mark.asyncio
async def test_activate_trial_returns_user_not_found_without_external_side_effects():
    context = make_service(user=None)

    result = await context.service.activate_trial(
        telegram_id=123456,
    )

    assert result.status == "user_not_found"
    assert context.vpn_access_service.create_calls == []
    assert context.subscription_repository.create_calls == []
    assert context.session.commit_count == 0
    assert context.session.rollback_count == 1


@pytest.mark.asyncio
async def test_activate_trial_records_vpn_creation_failure_and_preserves_eligibility():
    user = make_user()
    context = make_service(
        user=user,
        fail_vpn=True,
    )

    with pytest.raises(
        XuiClientError,
        match="3x-ui client creation failed",
    ):
        await context.service.activate_trial(
            telegram_id=123456,
        )

    assert user.trial_eligible is True
    assert user.trial_claimed_at is None
    assert context.subscription_repository.create_calls == []
    assert len(
        context.system_error_repository.create_calls
    ) == 1

    error_call = (
        context.system_error_repository.create_calls[0]
    )
    assert error_call["entity_type"] == "user"
    assert error_call["entity_id"] == 7
    assert (
        error_call["error_type"]
        == TRIAL_ACTIVATION_ERROR_TYPE
    )

    payload = json.loads(error_call["payload"])
    assert payload["stage"] == "create_vpn_access"
    assert payload["access_uuid"] is None
    assert payload["orphan_access_possible"] is False


@pytest.mark.asyncio
async def test_activate_trial_logs_possible_orphan_when_database_write_fails():
    user = make_user()
    context = make_service(
        user=user,
        fail_subscription=True,
    )

    with pytest.raises(
        RuntimeError,
        match="subscription create failed",
    ):
        await context.service.activate_trial(
            telegram_id=123456,
        )

    assert user.trial_eligible is True
    assert user.trial_claimed_at is None

    error_call = (
        context.system_error_repository.create_calls[0]
    )
    payload = json.loads(error_call["payload"])

    assert payload["stage"] == "create_subscription"
    assert (
        payload["access_uuid"]
        == "12345678-1234-5678-1234-567812345678"
    )
    assert payload["orphan_access_possible"] is True


@pytest.mark.asyncio
async def test_activate_trial_updates_existing_unresolved_error_instead_of_duplicating():
    pending_error = SimpleNamespace(id=501)
    user = make_user()
    context = make_service(
        user=user,
        fail_vpn=True,
        pending_error=pending_error,
    )

    with pytest.raises(XuiClientError):
        await context.service.activate_trial(
            telegram_id=123456,
        )

    assert (
        context.system_error_repository.create_calls
        == []
    )
    assert len(
        context.system_error_repository.update_calls
    ) == 1
    assert (
        context.system_error_repository.update_calls[0]["error"]
        is pending_error
    )