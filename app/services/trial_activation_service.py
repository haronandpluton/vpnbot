from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.repositories.subscriptions import SubscriptionRepository
from app.database.repositories.system_errors import (
    SystemErrorRecordRepository,
)
from app.database.repositories.users import UserRepository
from app.payment_core.enums.subscription_status import SubscriptionStatus
from app.services.subscription_meta_sync_service import (
    SubscriptionMetaSyncService,
)
from app.services.vpn_access_service import VpnAccessService


logger = logging.getLogger(__name__)

TRIAL_DURATION_DAYS = 3
TRIAL_DEVICE_LIMIT = 1
TRIAL_ACTIVATION_ERROR_TYPE = "trial_activation_failed"


@dataclass(frozen=True, slots=True)
class TrialActivationResult:
    status: str
    subscription_id: int | None = None
    config_uri: str | None = None
    expires_at: datetime | None = None


class TrialActivationService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        vpn_access_service: VpnAccessService | None = None,
        user_repository: UserRepository | None = None,
        subscription_repository: SubscriptionRepository | None = None,
        system_error_repository: SystemErrorRecordRepository | None = None,
        metadata_sync_service: SubscriptionMetaSyncService | None = None,
    ) -> None:
        self.session = session
        self.vpn_access_service = (
            vpn_access_service or VpnAccessService()
        )
        self.user_repository = (
            user_repository or UserRepository(session)
        )
        self.subscription_repository = (
            subscription_repository or SubscriptionRepository(session)
        )
        self.system_error_repository = (
            system_error_repository
            or SystemErrorRecordRepository(session)
        )
        self.metadata_sync_service = (
            metadata_sync_service
            or SubscriptionMetaSyncService(session)
        )

    async def activate_trial(
        self,
        *,
        telegram_id: int,
        now: datetime | None = None,
    ) -> TrialActivationResult:
        claimed_at = now or datetime.now(timezone.utc)

        if claimed_at.tzinfo is None or claimed_at.utcoffset() is None:
            raise ValueError("now must be timezone-aware")

        expires_at = claimed_at + timedelta(
            days=TRIAL_DURATION_DAYS
        )

        user_id: int | None = None
        access_uuid: str | None = None
        stage = "lock_user"

        try:
            user = (
                await self.user_repository
                .get_by_telegram_id_for_update(telegram_id)
            )

            if user is None:
                await self.session.rollback()
                return TrialActivationResult(
                    status="user_not_found",
                )

            user_id = user.id

            if not user.trial_eligible:
                await self.session.rollback()
                return TrialActivationResult(
                    status="not_eligible",
                )

            stage = "create_vpn_access"

            access = await self.vpn_access_service.create_access(
                user_id=user.id,
                device_limit=TRIAL_DEVICE_LIMIT,
                expires_at=expires_at,
            )
            access_uuid = access.uuid

            stage = "create_subscription"

            subscription = await self.subscription_repository.create(
                user_id=user.id,
                order_id=None,
                vpn_server_id=access.vpn_server_id,
                uuid=access.uuid,
                device_limit=TRIAL_DEVICE_LIMIT,
                starts_at=claimed_at,
                expires_at=expires_at,
                is_trial=True,
            )

            subscription = (
                await self.subscription_repository.activate(
                    subscription
                )
            )
            subscription = (
                await self.subscription_repository.mark_access_sent(
                    subscription,
                    sent_at=claimed_at,
                )
            )

            user.trial_eligible = False
            user.trial_claimed_at = claimed_at

            stage = "flush"
            await self.session.flush()

            subscription_id = subscription.id

            if subscription_id is None:
                raise RuntimeError(
                    "Trial subscription id was not assigned"
                )

            stage = "commit"
            await self.session.commit()

        except Exception as error:
            logger.exception(
                "Trial activation failed: "
                "telegram_id=%s user_id=%s stage=%s",
                telegram_id,
                user_id,
                stage,
            )

            try:
                await self.session.rollback()
            except Exception:
                logger.exception(
                    "Failed to rollback trial activation transaction."
                )

            await self._record_activation_failure(
                telegram_id=telegram_id,
                user_id=user_id,
                stage=stage,
                error=error,
                access_uuid=access_uuid,
                expires_at=expires_at,
            )
            raise

        await self._resolve_pending_activation_error(user_id)

        await self.metadata_sync_service.sync_safely(
            entity_type="subscription",
            entity_id=subscription_id,
            reason="trial_activation",
            payload={
                "subscription_id": subscription_id,
                "user_id": user_id,
                "telegram_id": telegram_id,
                "uuid": access_uuid,
                "is_trial": True,
                "device_limit": TRIAL_DEVICE_LIMIT,
                "starts_at": claimed_at.isoformat(),
                "expires_at": expires_at.isoformat(),
                "status": SubscriptionStatus.ACTIVE.value,
            },
        )

        return TrialActivationResult(
            status="activated",
            subscription_id=subscription_id,
            config_uri=access.config_uri,
            expires_at=expires_at,
        )

    async def _record_activation_failure(
        self,
        *,
        telegram_id: int,
        user_id: int | None,
        stage: str,
        error: Exception,
        access_uuid: str | None,
        expires_at: datetime,
    ) -> None:
        error_message = (
            str(error).strip() or error.__class__.__name__
        )[:1000]

        if user_id is None:
            entity_type = "telegram_user"
            entity_id = telegram_id
        else:
            entity_type = "user"
            entity_id = user_id

        payload = json.dumps(
            {
                "telegram_id": telegram_id,
                "user_id": user_id,
                "stage": stage,
                "error": error_message,
                "access_uuid": access_uuid,
                "expires_at": expires_at.isoformat(),
                "orphan_access_possible": access_uuid is not None,
            },
            ensure_ascii=False,
        )

        try:
            await self.session.rollback()

            pending = (
                await self.system_error_repository
                .get_unresolved_by_entity_and_error_type(
                    entity_type=entity_type,
                    entity_id=entity_id,
                    error_type=TRIAL_ACTIVATION_ERROR_TYPE,
                )
            )

            if pending is None:
                await self.system_error_repository.create(
                    entity_type=entity_type,
                    entity_id=entity_id,
                    error_type=TRIAL_ACTIVATION_ERROR_TYPE,
                    error_message=error_message,
                    payload=payload,
                )
            else:
                await self.system_error_repository.update_pending_failure(
                    pending,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    error_message=error_message,
                    payload=payload,
                )

            await self.session.commit()

        except Exception:
            logger.exception(
                "Failed to persist trial activation error: "
                "telegram_id=%s user_id=%s",
                telegram_id,
                user_id,
            )

            try:
                await self.session.rollback()
            except Exception:
                logger.exception(
                    "Failed to rollback after trial "
                    "system_errors persistence failure."
                )

    async def _resolve_pending_activation_error(
        self,
        user_id: int,
    ) -> None:
        try:
            pending = (
                await self.system_error_repository
                .get_unresolved_by_entity_and_error_type(
                    entity_type="user",
                    entity_id=user_id,
                    error_type=TRIAL_ACTIVATION_ERROR_TYPE,
                )
            )

            if pending is None:
                await self.session.rollback()
                return

            await self.system_error_repository.mark_resolved(pending)
            await self.session.commit()

        except Exception:
            logger.exception(
                "Failed to resolve previous trial activation error: "
                "user_id=%s",
                user_id,
            )

            try:
                await self.session.rollback()
            except Exception:
                logger.exception(
                    "Failed to rollback trial error resolution."
                )