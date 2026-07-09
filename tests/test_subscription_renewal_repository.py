from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, cast

import pytest
from sqlalchemy.dialects import postgresql

from app.database.repositories.subscriptions import SubscriptionRepository
from app.payment_core.enums.subscription_status import SubscriptionStatus


class FakeResult:
    def __init__(self, value=None) -> None:
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class FakeSession:
    def __init__(self, value=None) -> None:
        self.value = value
        self.execute_calls = []
        self.flush_count = 0

    async def execute(self, stmt):
        self.execute_calls.append(stmt)
        return FakeResult(self.value)

    async def flush(self):
        self.flush_count += 1


@pytest.mark.asyncio
async def test_get_by_id_for_update_uses_row_lock():
    session = FakeSession()
    repository = SubscriptionRepository(cast(Any, session))

    await repository.get_by_id_for_update(50)

    sql = str(
        session.execute_calls[0].compile(
            dialect=postgresql.dialect(),
        )
    )

    assert "FOR UPDATE" in sql


@pytest.mark.asyncio
async def test_renew_preserves_origin_order_and_reactivates_subscription():
    old_order_id = 10
    subscription = SimpleNamespace(
        id=50,
        order_id=old_order_id,
        status=SubscriptionStatus.EXPIRED,
        expires_at=datetime.now(timezone.utc) - timedelta(days=1),
        device_limit=1,
        error_reason="expired",
        disabled_at=None,
    )
    new_expires_at = datetime.now(timezone.utc) + timedelta(days=33)
    session = FakeSession()
    repository = SubscriptionRepository(cast(Any, session))

    result = await repository.renew(
        subscription=subscription,
        expires_at=new_expires_at,
        device_limit=1,
    )

    assert result is subscription
    assert subscription.order_id == old_order_id
    assert subscription.expires_at == new_expires_at
    assert subscription.status == SubscriptionStatus.ACTIVE
    assert subscription.error_reason is None
    assert subscription.disabled_at is None
    assert session.flush_count == 1
