from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from app.common.enums import VPNNodeActualState, VPNNodeDesiredState
from app.database.models import SubscriptionNodeAccess
from app.database.repositories.base import BaseRepository


class SubscriptionNodeAccessRepository(BaseRepository):
    async def get_by_subscription_and_node(
        self,
        subscription_id: int,
        node_code: str,
    ) -> SubscriptionNodeAccess | None:
        stmt = select(SubscriptionNodeAccess).where(
            SubscriptionNodeAccess.subscription_id == subscription_id,
            SubscriptionNodeAccess.node_code == node_code,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_subscription_and_node_for_update(
        self,
        subscription_id: int,
        node_code: str,
    ) -> SubscriptionNodeAccess | None:
        stmt = (
            select(SubscriptionNodeAccess)
            .where(
                SubscriptionNodeAccess.subscription_id == subscription_id,
                SubscriptionNodeAccess.node_code == node_code,
            )
            .with_for_update()
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_subscription(
        self,
        subscription_id: int,
    ) -> list[SubscriptionNodeAccess]:
        stmt = (
            select(SubscriptionNodeAccess)
            .where(SubscriptionNodeAccess.subscription_id == subscription_id)
            .order_by(SubscriptionNodeAccess.node_code.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create(
        self,
        *,
        subscription_id: int,
        node_code: str,
        desired_state: VPNNodeDesiredState = VPNNodeDesiredState.ENABLED,
        actual_state: VPNNodeActualState = VPNNodeActualState.PENDING,
    ) -> SubscriptionNodeAccess:
        record = SubscriptionNodeAccess(
            subscription_id=subscription_id,
            node_code=node_code,
            desired_state=desired_state,
            actual_state=actual_state,
        )
        self.session.add(record)
        await self.session.flush()
        return record

    async def set_desired_state(
        self,
        record: SubscriptionNodeAccess,
        desired_state: VPNNodeDesiredState,
    ) -> SubscriptionNodeAccess:
        record.desired_state = desired_state
        await self.session.flush()
        return record

    async def mark_enabled(
        self,
        record: SubscriptionNodeAccess,
        *,
        occurred_at: datetime | None = None,
    ) -> SubscriptionNodeAccess:
        record.actual_state = VPNNodeActualState.ENABLED
        record.last_error = None
        record.retry_count = 0
        record.provisioned_at = occurred_at or datetime.now(timezone.utc)
        record.disabled_at = None
        await self.session.flush()
        return record

    async def mark_renewal_succeeded(
        self,
        record: SubscriptionNodeAccess,
    ) -> SubscriptionNodeAccess:
        """Record a successful expiry sync without resetting provisioned_at."""
        record.actual_state = VPNNodeActualState.ENABLED
        record.last_error = None
        record.retry_count = 0
        record.disabled_at = None
        await self.session.flush()
        return record

    async def mark_disabled(
        self,
        record: SubscriptionNodeAccess,
        *,
        occurred_at: datetime | None = None,
    ) -> SubscriptionNodeAccess:
        record.actual_state = VPNNodeActualState.DISABLED
        record.last_error = None
        record.retry_count = 0
        record.disabled_at = occurred_at or datetime.now(timezone.utc)
        await self.session.flush()
        return record

    async def mark_error(
        self,
        record: SubscriptionNodeAccess,
        *,
        error_message: str,
    ) -> SubscriptionNodeAccess:
        record.actual_state = VPNNodeActualState.ERROR
        record.last_error = error_message
        record.retry_count += 1
        await self.session.flush()
        return record
