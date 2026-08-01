from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.enums import VPNNodeDesiredState
from app.database.repositories.subscription_node_access import (
    SubscriptionNodeAccessRepository,
)
from app.services.subscription_node_access_state_service import (
    SubscriptionNodeAccessStateService,
)
from app.services.vpn_access_service import VpnAccessService


@dataclass(frozen=True, slots=True)
class SubscriptionNodeAccessReconciliationResult:
    checked_count: int
    succeeded_count: int
    failed_count: int
    errors: tuple[str, ...] = ()


class SubscriptionNodeAccessReconciliationService:
    """Retry VPN node rows whose actual state differs from the desired state."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        repository: SubscriptionNodeAccessRepository | None = None,
        vpn_access_service: VpnAccessService | None = None,
        state_service: SubscriptionNodeAccessStateService | None = None,
    ) -> None:
        self.session = session
        self.repository = repository or SubscriptionNodeAccessRepository(session)
        self.vpn_access_service = vpn_access_service or VpnAccessService()
        self.state_service = state_service or SubscriptionNodeAccessStateService(
            session
        )

    async def reconcile(
        self,
        *,
        limit: int = 100,
    ) -> SubscriptionNodeAccessReconciliationResult:
        if limit <= 0:
            raise ValueError("limit must be positive")

        candidates = await self.repository.list_reconciliation_candidates(
            limit=limit
        )
        succeeded_count = 0
        failed_count = 0
        errors: list[str] = []

        for candidate in candidates:
            enabled = candidate.desired_state == VPNNodeDesiredState.ENABLED

            try:
                result = await self.vpn_access_service.set_access_state_on_node(
                    candidate.subscription.uuid,
                    candidate.node_code,
                    enabled=enabled,
                )

                if enabled:
                    await self.state_service.record_successful_enable_results(
                        subscription_id=candidate.subscription_id,
                        results=(result,),
                    )
                    await self.state_service.record_failed_enable_results(
                        subscription_id=candidate.subscription_id,
                        results=(result,),
                    )
                else:
                    await self.state_service.record_successful_disable_results(
                        subscription_id=candidate.subscription_id,
                        results=(result,),
                    )
                    await self.state_service.record_failed_disable_results(
                        subscription_id=candidate.subscription_id,
                        results=(result,),
                    )

                await self.session.commit()
            except Exception as error:  # noqa: BLE001 - isolate candidate failures
                await self.session.rollback()
                failed_count += 1
                errors.append(
                    f"subscription_id={candidate.subscription_id} "
                    f"node={candidate.node_code}: {error}"
                )
                continue

            if result.succeeded:
                succeeded_count += 1
            else:
                failed_count += 1
                errors.append(
                    f"subscription_id={candidate.subscription_id} "
                    f"node={candidate.node_code}: "
                    f"{result.error or 'VPN node reconciliation failed'}"
                )

        return SubscriptionNodeAccessReconciliationResult(
            checked_count=len(candidates),
            succeeded_count=succeeded_count,
            failed_count=failed_count,
            errors=tuple(errors),
        )
