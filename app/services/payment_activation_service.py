from __future__ import annotations

import json
import logging
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.repositories.system_errors import (
    SystemErrorRecordRepository,
)
from app.payment_core.enums.order_status import OrderStatus
from app.payment_core.enums.payment_status import PaymentStatus
from app.services.payment_event_service import PaymentEventService
from app.services.subscription_service import SubscriptionService


logger = logging.getLogger(__name__)

SUBSCRIPTION_ACTIVATION_ERROR_TYPE = "subscription_activation_failed"


class PaymentActivationService:
    """
    Orchestration layer:

    payment event confirmed
    -> payment confirmed
    -> order paid
    -> subscription activated / extended

    A subscription failure is re-raised to the caller and also persisted
    separately in system_errors. Confirmed payment data is never converted
    into a false success.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.payment_event_service = PaymentEventService(session)
        self.subscription_service = SubscriptionService(session)

    async def process_confirmed_payment_event_and_activate(
        self,
        order_id: int,
        amount: Decimal,
        provider: str,
        event_type: str,
        external_event_id: str | None = None,
        txid: str | None = None,
        address_from: str | None = None,
        address_to: str | None = None,
        memo_tag: str | None = None,
        confirmations: int | None = None,
        raw_payload: str | None = None,
        allow_expired_order: bool = False,
    ):
        event_kwargs = {
            "order_id": order_id,
            "amount": amount,
            "provider": provider,
            "event_type": event_type,
            "external_event_id": external_event_id,
            "txid": txid,
            "address_from": address_from,
            "address_to": address_to,
            "memo_tag": memo_tag,
            "confirmations": confirmations,
            "raw_payload": raw_payload,
        }

        if allow_expired_order:
            event_kwargs["allow_expired_order"] = True

        event, payment, paid_order = (
            await self.payment_event_service.process_confirmed_event(
                **event_kwargs
            )
        )

        if payment is None:
            return event, payment, None, None

        if payment.status != PaymentStatus.CONFIRMED:
            return event, payment, None, None

        if paid_order is None:
            return event, payment, None, None

        if paid_order.status not in {
            OrderStatus.PAID,
            OrderStatus.ACTIVATED,
        }:
            return event, payment, None, None

        failure_context = {
            "order_id": self._model_id(paid_order) or order_id,
            "payment_event_id": self._model_id(event),
            "payment_id": self._model_id(payment),
            "target_subscription_id": getattr(
                paid_order,
                "target_subscription_id",
                None,
            ),
            "activated_subscription_id": getattr(
                paid_order,
                "activated_subscription_id",
                None,
            ),
            "provider": provider,
            "event_type": event_type,
            "external_event_id": external_event_id,
            "txid": txid,
            "amount": str(amount),
            "has_raw_payload": raw_payload is not None,
        }

        try:
            subscription, config_uri = (
                await self.subscription_service.activate_or_extend_by_order(
                    paid_order.id
                )
            )
        except Exception as error:
            logger.exception(
                "Subscription activation failed after confirmed payment: "
                "order_id=%s payment_event_id=%s payment_id=%s "
                "target_subscription_id=%s",
                failure_context["order_id"],
                failure_context["payment_event_id"],
                failure_context["payment_id"],
                failure_context["target_subscription_id"],
            )
            await self._record_activation_failure(
                error=error,
                context=failure_context,
            )
            raise

        return event, payment, subscription, config_uri

    async def _record_activation_failure(
        self,
        *,
        error: Exception,
        context: dict[str, Any],
    ) -> None:
        """
        Best-effort durable error record after SubscriptionService rollback.

        Failure to write system_errors must never replace the original
        subscription activation exception.
        """
        error_message = f"{type(error).__name__}: {error}"[:1000]
        event_id = context.get("payment_event_id")
        order_id = context.get("order_id")

        if event_id is not None:
            entity_type = "payment_event"
            entity_id = event_id
        else:
            entity_type = "order"
            entity_id = order_id

        payload = json.dumps(
            {
                **context,
                "error_class": type(error).__name__,
                "error_message": str(error),
            },
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )

        try:
            # SubscriptionService rolls back on failure. A second rollback is
            # intentional and makes this method safe when another caller did not.
            await self.session.rollback()

            repository = SystemErrorRecordRepository(self.session)
            pending = (
                await repository.get_unresolved_by_entity_and_error_type(
                    entity_type=entity_type,
                    entity_id=entity_id,
                    error_type=SUBSCRIPTION_ACTIVATION_ERROR_TYPE,
                )
            )

            if pending is None:
                await repository.create(
                    entity_type=entity_type,
                    entity_id=entity_id,
                    error_type=SUBSCRIPTION_ACTIVATION_ERROR_TYPE,
                    error_message=error_message,
                    payload=payload,
                )
            else:
                await repository.update_pending_failure(
                    pending,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    error_message=error_message,
                    payload=payload,
                )

            await self.session.commit()
        except Exception:
            logger.exception(
                "Failed to persist subscription activation error: "
                "order_id=%s payment_event_id=%s",
                order_id,
                event_id,
            )
            try:
                await self.session.rollback()
            except Exception:
                logger.exception(
                    "Failed to rollback after system_errors persistence failure."
                )

    @staticmethod
    def _model_id(obj: object | None) -> int | None:
        if obj is None:
            return None

        state = getattr(obj, "_sa_instance_state", None)
        identity = getattr(state, "identity", None)

        if identity:
            return int(identity[0])

        value = getattr(obj, "id", None)
        return int(value) if value is not None else None
