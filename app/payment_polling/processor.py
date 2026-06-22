from datetime import datetime, timezone
from decimal import Decimal
import logging

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Order
from app.payment_adapters.base import NormalizedTransaction
from app.payment_core.enums.order_status import OrderStatus
from app.services.payment_activation_service import PaymentActivationService
from app.services.payment_event_service import PaymentEventService


logger = logging.getLogger(__name__)


class PaymentPollingProcessor:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.activation_service = PaymentActivationService(session)
        self.payment_event_service = PaymentEventService(session)

    async def process_transaction(self, tx: NormalizedTransaction):
        late_order = await self._find_late_matching_order(tx)

        if late_order is not None:
            late_order_id_for_log = late_order.id

            event, payment, expired_order = (
                await self.payment_event_service.process_detected_event(
                    order_id=late_order_id_for_log,
                    amount=tx.amount,
                    provider=tx.provider or "unknown",
                    event_type="payment_late",
                    external_event_id=tx.txid,
                    txid=tx.txid,
                    address_from=tx.address_from,
                    address_to=tx.address_to,
                    memo_tag=tx.memo_tag,
                    confirmations=tx.confirmations,
                    raw_payload=str(tx.raw_payload),
                )
            )

            logger.info(
                "Late payment processed: txid=%s order_id=%s",
                tx.txid,
                late_order_id_for_log,
            )

            return event, payment, None, None

        order = await self._find_matching_order(tx)

        if order is not None:
            order_id_for_log = order.id

            event, payment, subscription, config_uri = (
                await self.activation_service.process_confirmed_payment_event_and_activate(
                    order_id=order_id_for_log,
                    amount=tx.amount,
                    provider=tx.provider or "unknown",
                    event_type="payment_confirmed",
                    external_event_id=tx.txid,
                    txid=tx.txid,
                    address_from=tx.address_from,
                    address_to=tx.address_to,
                    memo_tag=tx.memo_tag,
                    confirmations=tx.confirmations,
                    raw_payload=str(tx.raw_payload),
                )
            )

            logger.info(
                "Payment transaction processed: txid=%s order_id=%s",
                tx.txid,
                order_id_for_log,
            )

            return event, payment, subscription, config_uri

        invalid_amount_order = await self._find_invalid_amount_order(tx)

        if invalid_amount_order is not None:
            return await self._process_invalid_tx(
                order=invalid_amount_order,
                tx=tx,
                reason="wrong_amount",
            )

        invalid_network_order = await self._find_invalid_network_order(tx)

        if invalid_network_order is not None:
            return await self._process_invalid_tx(
                order=invalid_network_order,
                tx=tx,
                reason="wrong_network",
            )

        invalid_currency_order = await self._find_invalid_currency_order(tx)

        if invalid_currency_order is not None:
            return await self._process_invalid_tx(
                order=invalid_currency_order,
                tx=tx,
                reason="wrong_currency",
            )

        logger.info(
            "No matching order for tx: txid=%s amount=%s currency=%s network=%s",
            tx.txid,
            tx.amount,
            tx.currency,
            tx.network,
        )

        return None

    async def _process_invalid_tx(
        self,
        order: Order,
        tx: NormalizedTransaction,
        reason: str,
    ):
        order_id_for_log = order.id

        event, payment, invalid_order = (
            await self.payment_event_service.process_invalid_event(
                order_id=order_id_for_log,
                amount=tx.amount,
                currency=tx.currency,
                network=tx.network,
                provider=tx.provider or "unknown",
                event_type="payment_invalid",
                reason=reason,
                external_event_id=tx.txid,
                txid=tx.txid,
                address_from=tx.address_from,
                address_to=tx.address_to,
                memo_tag=tx.memo_tag,
                confirmations=tx.confirmations,
                raw_payload=str(tx.raw_payload),
            )
        )

        logger.info(
            "Invalid payment transaction processed: reason=%s txid=%s order_id=%s",
            reason,
            tx.txid,
            order_id_for_log,
        )

        return event, payment, None, None

    async def process_transactions(self, transactions: list[NormalizedTransaction]) -> list:
        results = []

        for tx in transactions:
            result = await self.process_transaction(tx)
            if result is not None:
                results.append(result)

        return results

    async def _find_late_matching_order(self, tx: NormalizedTransaction) -> Order | None:
        now = datetime.now(timezone.utc)
        tx_amount = Decimal(tx.amount)

        stmt = (
            select(Order)
            .where(
                or_(
                    Order.status == OrderStatus.EXPIRED,
                    and_(
                        Order.status == OrderStatus.WAITING_PAYMENT,
                        Order.expires_at <= now,
                    ),
                ),
                Order.expected_currency == tx.currency,
                Order.expected_network == tx.network,
                Order.expected_amount == tx_amount,
                Order.destination_address == tx.address_to,
            )
            .order_by(Order.created_at.asc())
            .limit(1)
        )

        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def _find_matching_order(self, tx: NormalizedTransaction) -> Order | None:
        now = datetime.now(timezone.utc)
        tx_amount = Decimal(tx.amount)

        exact_stmt = (
            select(Order)
            .where(
                Order.status == OrderStatus.WAITING_PAYMENT,
                Order.expires_at > now,
                Order.expected_currency == tx.currency,
                Order.expected_network == tx.network,
                Order.expected_amount == tx_amount,
                Order.destination_address == tx.address_to,
            )
            .order_by(Order.created_at.asc())
            .limit(1)
        )

        exact_result = await self.session.execute(exact_stmt)
        exact_order = exact_result.scalar_one_or_none()

        if exact_order is not None:
            return exact_order

        fallback_stmt = (
            select(Order)
            .where(
                Order.status == OrderStatus.WAITING_PAYMENT,
                Order.expires_at > now,
                Order.expected_currency == tx.currency,
                Order.expected_network == tx.network,
                Order.expected_amount.is_(None),
                Order.price_usd == tx_amount,
                Order.destination_address == tx.address_to,
            )
            .order_by(Order.created_at.asc())
            .limit(1)
        )

        fallback_result = await self.session.execute(fallback_stmt)
        return fallback_result.scalar_one_or_none()

    async def _find_invalid_amount_order(self, tx: NormalizedTransaction) -> Order | None:
        now = datetime.now(timezone.utc)
        tx_amount = Decimal(tx.amount)

        stmt = (
            select(Order)
            .where(
                Order.status == OrderStatus.WAITING_PAYMENT,
                Order.expires_at > now,
                Order.expected_currency == tx.currency,
                Order.expected_network == tx.network,
                Order.expected_amount.is_not(None),
                Order.expected_amount != tx_amount,
                Order.destination_address == tx.address_to,
            )
            .order_by(Order.created_at.asc())
            .limit(1)
        )

        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def _find_invalid_network_order(self, tx: NormalizedTransaction) -> Order | None:
        now = datetime.now(timezone.utc)
        tx_amount = Decimal(tx.amount)

        stmt = (
            select(Order)
            .where(
                Order.status == OrderStatus.WAITING_PAYMENT,
                Order.expires_at > now,
                Order.expected_currency == tx.currency,
                Order.expected_network != tx.network,
                Order.expected_amount == tx_amount,
                Order.destination_address == tx.address_to,
            )
            .order_by(Order.created_at.asc())
            .limit(1)
        )

        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def _find_invalid_currency_order(self, tx: NormalizedTransaction) -> Order | None:
        now = datetime.now(timezone.utc)
        tx_amount = Decimal(tx.amount)

        stmt = (
            select(Order)
            .where(
                Order.status == OrderStatus.WAITING_PAYMENT,
                Order.expires_at > now,
                Order.expected_currency != tx.currency,
                Order.expected_network == tx.network,
                Order.expected_amount == tx_amount,
                Order.destination_address == tx.address_to,
            )
            .order_by(Order.created_at.asc())
            .limit(1)
        )

        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()