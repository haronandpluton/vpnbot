from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.payment_event_service import PaymentEventService
from app.services.subscription_service import SubscriptionService


class PaymentActivationService:
    """
    Orchestration layer:

    payment event confirmed
    -> payment confirmed
    -> order paid
    -> subscription activated / extended

    Пока без реального Xray.
    VPN-доступ создает stub через SubscriptionService -> VpnAccessService.
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
    ):
        event, payment, paid_order = (
            await self.payment_event_service.process_confirmed_event(
                order_id=order_id,
                amount=amount,
                provider=provider,
                event_type=event_type,
                external_event_id=external_event_id,
                txid=txid,
                address_from=address_from,
                address_to=address_to,
                memo_tag=memo_tag,
                confirmations=confirmations,
                raw_payload=raw_payload,
            )
        )

        if paid_order is None:
            if event is not None and event.order_id is not None:
                subscription, config_uri = (
                    await self.subscription_service.activate_or_extend_by_order(
                        event.order_id
                    )
                )
                return event, payment, subscription, config_uri

            raise ValueError("Paid order was not returned and event has no order_id")

        subscription, config_uri = (
            await self.subscription_service.activate_or_extend_by_order(paid_order.id)
        )

        return event, payment, subscription, config_uri