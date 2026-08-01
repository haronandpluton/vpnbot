from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.enums import VPNNodeActualState, VPNNodeDesiredState
from app.database.models import SubscriptionNodeAccess
from app.database.repositories.subscription_node_access import (
    SubscriptionNodeAccessRepository,
)
from app.services.vpn_access_service import (
    VpnNodeProvisionResult,
    VpnNodeRenewalResult,
    VpnNodeStateChangeResult,
)


class SubscriptionNodeAccessStateService:
    """Creates retry-safe per-node state rows for a subscription."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        repository: SubscriptionNodeAccessRepository | None = None,
    ) -> None:
        self.repository = repository or SubscriptionNodeAccessRepository(session)

    async def initialize_pending(
        self,
        *,
        subscription_id: int,
        node_codes: Iterable[str],
    ) -> tuple[SubscriptionNodeAccess, ...]:
        if subscription_id <= 0:
            raise ValueError("subscription_id must be positive")

        normalized_codes = self._normalize_node_codes(node_codes)
        records: list[SubscriptionNodeAccess] = []

        for node_code in normalized_codes:
            record = await self.repository.get_by_subscription_and_node_for_update(
                subscription_id,
                node_code,
            )

            if record is None:
                record = await self.repository.create(
                    subscription_id=subscription_id,
                    node_code=node_code,
                    desired_state=VPNNodeDesiredState.ENABLED,
                    actual_state=VPNNodeActualState.PENDING,
                )
            elif record.desired_state != VPNNodeDesiredState.ENABLED:
                # A retry must restore the intended state, but must not erase a
                # previously observed actual state or its diagnostic fields.
                record = await self.repository.set_desired_state(
                    record,
                    VPNNodeDesiredState.ENABLED,
                )

            records.append(record)

        return tuple(records)

    async def record_provisioning_results(
        self,
        *,
        subscription_id: int,
        results: Iterable[VpnNodeProvisionResult],
    ) -> tuple[SubscriptionNodeAccess, ...]:
        if subscription_id <= 0:
            raise ValueError("subscription_id must be positive")

        recorded: list[SubscriptionNodeAccess] = []

        for result in results:
            node_code = str(result.node_name).strip()
            if not node_code:
                raise ValueError("VPN node code must not be empty")

            record = await self.repository.get_by_subscription_and_node_for_update(
                subscription_id,
                node_code,
            )
            if record is None:
                record = await self.repository.create(
                    subscription_id=subscription_id,
                    node_code=node_code,
                    desired_state=VPNNodeDesiredState.ENABLED,
                    actual_state=VPNNodeActualState.PENDING,
                )

            if result.enabled:
                record = await self.repository.mark_enabled(record)
            else:
                error_message = (result.error or "VPN node provisioning failed")[:1000]
                record = await self.repository.mark_error(
                    record,
                    error_message=error_message,
                )

            recorded.append(record)

        return tuple(recorded)

    async def record_successful_renewal_results(
        self,
        *,
        subscription_id: int,
        results: Iterable[VpnNodeRenewalResult],
    ) -> tuple[SubscriptionNodeAccess, ...]:
        """Persist only successful per-node renewal synchronization results."""
        if subscription_id <= 0:
            raise ValueError("subscription_id must be positive")

        recorded: list[SubscriptionNodeAccess] = []

        for result in results:
            if not result.updated:
                continue

            node_code = str(result.node_name).strip()
            if not node_code:
                raise ValueError("VPN node code must not be empty")

            record = await self.repository.get_by_subscription_and_node_for_update(
                subscription_id,
                node_code,
            )
            if record is None:
                record = await self.repository.create(
                    subscription_id=subscription_id,
                    node_code=node_code,
                    desired_state=VPNNodeDesiredState.ENABLED,
                    actual_state=VPNNodeActualState.PENDING,
                )

            record = await self.repository.mark_renewal_succeeded(record)
            recorded.append(record)

        return tuple(recorded)

    async def record_successful_enable_results(
        self,
        *,
        subscription_id: int,
        results: Iterable[VpnNodeStateChangeResult],
    ) -> tuple[SubscriptionNodeAccess, ...]:
        """Persist only successful per-node enable results."""
        if subscription_id <= 0:
            raise ValueError("subscription_id must be positive")

        recorded: list[SubscriptionNodeAccess] = []

        for result in results:
            if not result.succeeded:
                continue

            node_code = str(result.node_name).strip()
            if not node_code:
                raise ValueError("VPN node code must not be empty")

            record = await self.repository.get_by_subscription_and_node_for_update(
                subscription_id,
                node_code,
            )
            if record is None:
                record = await self.repository.create(
                    subscription_id=subscription_id,
                    node_code=node_code,
                    desired_state=VPNNodeDesiredState.ENABLED,
                    actual_state=VPNNodeActualState.PENDING,
                )
            elif record.desired_state != VPNNodeDesiredState.ENABLED:
                record = await self.repository.set_desired_state(
                    record,
                    VPNNodeDesiredState.ENABLED,
                )

            record = await self.repository.mark_renewal_succeeded(record)
            recorded.append(record)

        return tuple(recorded)

    async def record_failed_enable_results(
        self,
        *,
        subscription_id: int,
        results: Iterable[VpnNodeStateChangeResult],
    ) -> tuple[SubscriptionNodeAccess, ...]:
        """Persist only failed per-node enable results."""
        if subscription_id <= 0:
            raise ValueError("subscription_id must be positive")

        recorded: list[SubscriptionNodeAccess] = []

        for result in results:
            if result.succeeded:
                continue

            node_code = str(result.node_name).strip()
            if not node_code:
                raise ValueError("VPN node code must not be empty")

            record = await self.repository.get_by_subscription_and_node_for_update(
                subscription_id,
                node_code,
            )
            if record is None:
                record = await self.repository.create(
                    subscription_id=subscription_id,
                    node_code=node_code,
                    desired_state=VPNNodeDesiredState.ENABLED,
                    actual_state=VPNNodeActualState.PENDING,
                )
            elif record.desired_state != VPNNodeDesiredState.ENABLED:
                record = await self.repository.set_desired_state(
                    record,
                    VPNNodeDesiredState.ENABLED,
                )

            error_message = (result.error or "VPN node enable failed")[:1000]
            record = await self.repository.mark_error(
                record,
                error_message=error_message,
            )
            recorded.append(record)

        return tuple(recorded)

    async def record_failed_renewal_results(
        self,
        *,
        subscription_id: int,
        results: Iterable[VpnNodeRenewalResult],
    ) -> tuple[SubscriptionNodeAccess, ...]:
        """Persist only failed per-node renewal synchronization results."""
        if subscription_id <= 0:
            raise ValueError("subscription_id must be positive")

        recorded: list[SubscriptionNodeAccess] = []

        for result in results:
            if result.updated:
                continue

            node_code = str(result.node_name).strip()
            if not node_code:
                raise ValueError("VPN node code must not be empty")

            record = await self.repository.get_by_subscription_and_node_for_update(
                subscription_id,
                node_code,
            )
            if record is None:
                record = await self.repository.create(
                    subscription_id=subscription_id,
                    node_code=node_code,
                    desired_state=VPNNodeDesiredState.ENABLED,
                    actual_state=VPNNodeActualState.PENDING,
                )

            error_message = (result.error or "VPN node renewal failed")[:1000]
            record = await self.repository.mark_error(
                record,
                error_message=error_message,
            )
            recorded.append(record)

        return tuple(recorded)

    @staticmethod
    def _normalize_node_codes(node_codes: Iterable[str]) -> tuple[str, ...]:
        result: list[str] = []
        seen: set[str] = set()

        for raw_code in node_codes:
            code = str(raw_code).strip()
            if not code:
                raise ValueError("VPN node code must not be empty")
            if code in seen:
                continue
            seen.add(code)
            result.append(code)

        if not result:
            raise ValueError("At least one VPN node is required")

        return tuple(result)
