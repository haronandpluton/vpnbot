from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.services.admin_action_log_service import (
    AdminActionLogService,
    AdminActionLookupService,
)


class FakeExecuteResult:
    def __init__(self, *, scalar_value=None, rows=None) -> None:
        self.scalar_value = scalar_value
        self.rows = rows or []

    def scalar_one_or_none(self):
        return self.scalar_value

    def all(self):
        return self.rows


class FakeSession:
    def __init__(
        self,
        *,
        admin_user=None,
        rows=None,
        fail_commit: bool = False,
        fail_flush: bool = False,
    ) -> None:
        self.admin_user = admin_user
        self.rows = rows or []
        self.fail_commit = fail_commit
        self.fail_flush = fail_flush
        self.execute_calls = []
        self.add_calls = []
        self.commit_count = 0
        self.flush_count = 0
        self.refresh_calls = []
        self.next_action_id = 700

    async def execute(self, stmt):
        self.execute_calls.append(stmt)
        return FakeExecuteResult(
            scalar_value=self.admin_user,
            rows=self.rows,
        )

    def add(self, obj) -> None:
        self.add_calls.append(obj)

    async def commit(self) -> None:
        self.commit_count += 1

        if self.fail_commit:
            raise RuntimeError("commit failed")

        self._assign_action_id()

    async def flush(self) -> None:
        self.flush_count += 1

        if self.fail_flush:
            raise RuntimeError("flush failed")

        self._assign_action_id()

    async def refresh(self, obj) -> None:
        self.refresh_calls.append(obj)
        self._assign_action_id(obj)

    def _assign_action_id(self, obj=None) -> None:
        if obj is not None:
            if getattr(obj, "id", None) is None:
                obj.id = self.next_action_id
                self.next_action_id += 1
            return

        for item in self.add_calls:
            if getattr(item, "id", None) is None:
                item.id = self.next_action_id
                self.next_action_id += 1


def make_user(
    *,
    user_id: int = 10,
    telegram_id: int = 123456,
    username: str | None = "admin",
):
    return SimpleNamespace(
        id=user_id,
        telegram_id=telegram_id,
        username=username,
    )


def make_action(
    *,
    action_id: int = 1,
    admin_user_id: int = 10,
    target_user_id: int | None = 20,
    action_type: str = "manual_extend_subscription",
    reason: str | None = "test reason",
    order_id: int | None = 30,
    payment_id: int | None = 40,
    subscription_id: int | None = 50,
    payload: str | None = "payload",
    created_at=None,
):
    return SimpleNamespace(
        id=action_id,
        admin_user_id=admin_user_id,
        target_user_id=target_user_id,
        action_type=action_type,
        reason=reason,
        order_id=order_id,
        payment_id=payment_id,
        subscription_id=subscription_id,
        payload=payload,
        created_at=created_at or datetime(2026, 7, 5, 12, 0, tzinfo=timezone.utc),
    )


@pytest.mark.asyncio
async def test_create_action_returns_admin_not_found_without_db_write():
    session = FakeSession(admin_user=None)
    service = AdminActionLogService(session)

    result = await service.create_action_by_admin_telegram_id(
        admin_telegram_id=999,
        action_type="manual_extend_subscription",
        target_user_id=20,
        order_id=30,
        payment_id=40,
        subscription_id=50,
        reason="test reason",
        payload="payload",
    )

    assert result.status == "admin_user_not_found"
    assert result.action_id is None
    assert result.admin_user_id is None
    assert result.message == "Admin user not found in users table."
    assert len(session.execute_calls) == 1
    assert session.add_calls == []
    assert session.commit_count == 0
    assert session.flush_count == 0
    assert session.refresh_calls == []


@pytest.mark.asyncio
async def test_create_action_with_commit_true_adds_action_commits_refreshes_and_returns_result():
    admin_user = make_user(user_id=10, telegram_id=123456)
    session = FakeSession(admin_user=admin_user)
    service = AdminActionLogService(session)

    result = await service.create_action_by_admin_telegram_id(
        admin_telegram_id=123456,
        action_type="manual_disable_subscription",
        target_user_id=20,
        order_id=30,
        payment_id=40,
        subscription_id=50,
        reason="manual block",
        payload="old_status=active; new_status=disabled",
        commit=True,
    )

    assert result.status == "created"
    assert result.action_id == 700
    assert result.admin_user_id == 10
    assert result.message == "Admin action logged."

    assert len(session.execute_calls) == 1
    assert len(session.add_calls) == 1
    assert session.commit_count == 1
    assert session.flush_count == 0
    assert session.refresh_calls == session.add_calls

    action = session.add_calls[0]
    assert action.id == 700
    assert action.admin_user_id == 10
    assert action.target_user_id == 20
    assert action.order_id == 30
    assert action.payment_id == 40
    assert action.subscription_id == 50
    assert action.action_type == "manual_disable_subscription"
    assert action.reason == "manual block"
    assert action.payload == "old_status=active; new_status=disabled"


@pytest.mark.asyncio
async def test_create_action_with_commit_false_flushes_without_commit_or_refresh():
    admin_user = make_user(user_id=11, telegram_id=123456)
    session = FakeSession(admin_user=admin_user)
    service = AdminActionLogService(session)

    result = await service.create_action_by_admin_telegram_id(
        admin_telegram_id=123456,
        action_type="retry_activation",
        target_user_id=None,
        order_id=30,
        payment_id=None,
        subscription_id=None,
        reason=None,
        payload=None,
        commit=False,
    )

    assert result.status == "created"
    assert result.action_id == 700
    assert result.admin_user_id == 11
    assert result.message == "Admin action logged."

    assert len(session.add_calls) == 1
    assert session.commit_count == 0
    assert session.flush_count == 1
    assert session.refresh_calls == []

    action = session.add_calls[0]
    assert action.id == 700
    assert action.admin_user_id == 11
    assert action.target_user_id is None
    assert action.order_id == 30
    assert action.payment_id is None
    assert action.subscription_id is None
    assert action.action_type == "retry_activation"
    assert action.reason is None
    assert action.payload is None


@pytest.mark.asyncio
async def test_create_action_propagates_commit_error_without_fake_success():
    admin_user = make_user(user_id=10, telegram_id=123456)
    session = FakeSession(admin_user=admin_user, fail_commit=True)
    service = AdminActionLogService(session)

    with pytest.raises(RuntimeError, match="commit failed"):
        await service.create_action_by_admin_telegram_id(
            admin_telegram_id=123456,
            action_type="manual_extend_subscription",
            subscription_id=50,
            reason="test",
            commit=True,
        )

    assert len(session.add_calls) == 1
    assert session.commit_count == 1
    assert session.flush_count == 0
    assert session.refresh_calls == []


@pytest.mark.asyncio
async def test_create_action_propagates_flush_error_without_fake_success():
    admin_user = make_user(user_id=10, telegram_id=123456)
    session = FakeSession(admin_user=admin_user, fail_flush=True)
    service = AdminActionLogService(session)

    with pytest.raises(RuntimeError, match="flush failed"):
        await service.create_action_by_admin_telegram_id(
            admin_telegram_id=123456,
            action_type="manual_extend_subscription",
            subscription_id=50,
            reason="test",
            commit=False,
        )

    assert len(session.add_calls) == 1
    assert session.commit_count == 0
    assert session.flush_count == 1
    assert session.refresh_calls == []


@pytest.mark.asyncio
async def test_get_user_by_telegram_id_returns_user_from_scalar_result():
    admin_user = make_user(user_id=10, telegram_id=123456)
    session = FakeSession(admin_user=admin_user)
    service = AdminActionLogService(session)

    result = await service._get_user_by_telegram_id(123456)

    assert result is admin_user
    assert len(session.execute_calls) == 1


def test_lookup_build_item_maps_action_and_admin_user_to_dto():
    created_at = datetime(2026, 7, 5, 12, 0, tzinfo=timezone.utc)
    action = make_action(
        action_id=101,
        admin_user_id=10,
        target_user_id=20,
        action_type="manual_disable_subscription",
        reason="manual block",
        order_id=30,
        payment_id=40,
        subscription_id=50,
        payload="payload",
        created_at=created_at,
    )
    admin_user = make_user(
        user_id=10,
        telegram_id=123456,
        username="root_admin",
    )

    item = AdminActionLookupService._build_item(
        action=action,
        admin_user=admin_user,
    )

    assert item.action_id == 101
    assert item.admin_user_id == 10
    assert item.admin_telegram_id == 123456
    assert item.admin_username == "root_admin"
    assert item.target_user_id == 20
    assert item.action_type == "manual_disable_subscription"
    assert item.reason == "manual block"
    assert item.order_id == 30
    assert item.payment_id == 40
    assert item.subscription_id == 50
    assert item.payload == "payload"
    assert item.created_at == created_at


@pytest.mark.asyncio
async def test_lookup_get_last_actions_returns_mapped_items():
    action_1 = make_action(action_id=1, action_type="retry_activation")
    action_2 = make_action(action_id=2, action_type="manual_extend_subscription")
    admin_user = make_user(user_id=10, telegram_id=123456, username="admin")
    session = FakeSession(
        rows=[
            (action_1, admin_user),
            (action_2, admin_user),
        ]
    )
    service = AdminActionLookupService(session)

    items = await service.get_last_actions(limit=2)

    assert len(items) == 2
    assert [item.action_id for item in items] == [1, 2]
    assert [item.action_type for item in items] == [
        "retry_activation",
        "manual_extend_subscription",
    ]
    assert len(session.execute_calls) == 1


@pytest.mark.asyncio
async def test_lookup_get_actions_by_subscription_id_returns_mapped_items():
    action = make_action(
        action_id=3,
        subscription_id=77,
        action_type="manual_disable_subscription",
    )
    admin_user = make_user(user_id=10, telegram_id=123456, username="admin")
    session = FakeSession(rows=[(action, admin_user)])
    service = AdminActionLookupService(session)

    items = await service.get_actions_by_subscription_id(
        subscription_id=77,
        limit=10,
    )

    assert len(items) == 1
    assert items[0].action_id == 3
    assert items[0].subscription_id == 77
    assert items[0].action_type == "manual_disable_subscription"
    assert len(session.execute_calls) == 1


@pytest.mark.asyncio
async def test_lookup_get_actions_by_target_user_id_returns_mapped_items():
    action = make_action(
        action_id=4,
        target_user_id=88,
        action_type="manual_extend_subscription",
    )
    admin_user = make_user(user_id=10, telegram_id=123456, username="admin")
    session = FakeSession(rows=[(action, admin_user)])
    service = AdminActionLookupService(session)

    items = await service.get_actions_by_target_user_id(
        target_user_id=88,
        limit=10,
    )

    assert len(items) == 1
    assert items[0].action_id == 4
    assert items[0].target_user_id == 88
    assert items[0].action_type == "manual_extend_subscription"
    assert len(session.execute_calls) == 1