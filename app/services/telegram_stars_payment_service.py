from __future__ import annotations

import json
import logging
import hashlib
import hmac
from dataclasses import dataclass
from decimal import Decimal
from app.database.repositories.system_errors import (
    SystemErrorRecordRepository,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.datetime_utils import is_due_or_past
from app.config.settings import Settings, get_settings
from app.config.tariffs import get_tariff
from app.database.repositories.orders import OrderRepository
from app.database.repositories.users import UserRepository
from app.payment_core.enums.order_status import OrderStatus
from app.payment_core.enums.payment_method import PaymentMethod

from app.services.payment_activation_service import PaymentActivationService

PAYLOAD_PREFIX = "vpn_stars"
TELEGRAM_STARS_CURRENCY = "XTR"
TELEGRAM_STARS_PROVIDER = "telegram_stars"
TELEGRAM_STARS_EVENT_TYPE = "successful_payment"
logger = logging.getLogger(__name__)

TELEGRAM_STARS_PROCESSING_ERROR_TYPE = (
    "telegram_stars_processing_failed"
)

class TelegramStarsConfigurationError(RuntimeError):
    """Telegram Stars отключены или секрет подписи не настроен."""


class TelegramStarsValidationError(ValueError):
    """Заказ или invoice payload не прошли проверку."""


@dataclass(frozen=True, slots=True)
class StarsInvoice:
    order_id: int
    payload: str
    title: str
    description: str
    label: str
    amount: int


@dataclass(frozen=True, slots=True)
class PreCheckoutDecision:
    ok: bool
    error_message: str | None = None


class TelegramStarsPaymentService:
    def __init__(
            self,
            session: AsyncSession,
            *,
            settings: Settings | None = None,
            activation_service: PaymentActivationService | None = None,
            system_error_repository: SystemErrorRecordRepository | None = None,
    ) -> None:
        self.session = session
        self.settings = settings or get_settings()

        self.order_repository = OrderRepository(session)
        self.user_repository = UserRepository(session)

        self.activation_service = (
            activation_service
            if activation_service is not None
            else PaymentActivationService(session)
        )

        self.system_error_repository = (
            system_error_repository
            if system_error_repository is not None
            else SystemErrorRecordRepository(session)
        )

    def ensure_enabled(self) -> None:
        if not self.settings.telegram_stars_enabled:
            raise TelegramStarsConfigurationError(
                "Telegram Stars payments are disabled"
            )

        if not self.settings.telegram_stars_invoice_secret.strip():
            raise TelegramStarsConfigurationError(
                "TELEGRAM_STARS_INVOICE_SECRET is not configured"
            )

    def build_payload(self, *, order_id: int, telegram_id: int) -> str:
        self.ensure_enabled()

        if order_id <= 0:
            raise TelegramStarsValidationError("Invalid order_id")

        if telegram_id <= 0:
            raise TelegramStarsValidationError("Invalid telegram_id")

        body = f"{PAYLOAD_PREFIX}:{order_id}:{telegram_id}"

        signature = hmac.new(
            self.settings.telegram_stars_invoice_secret.encode("utf-8"),
            body.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()[:32]

        return f"{body}:{signature}"

    def parse_payload(self, payload: str) -> tuple[int, int]:
        self.ensure_enabled()

        parts = payload.split(":")

        if len(parts) != 4 or parts[0] != PAYLOAD_PREFIX:
            raise TelegramStarsValidationError(
                "Invalid Telegram Stars invoice payload"
            )

        _, order_id_raw, telegram_id_raw, supplied_signature = parts

        if not order_id_raw.isdigit() or not telegram_id_raw.isdigit():
            raise TelegramStarsValidationError(
                "Invalid Telegram Stars invoice payload"
            )

        order_id = int(order_id_raw)
        telegram_id = int(telegram_id_raw)

        if order_id <= 0 or telegram_id <= 0:
            raise TelegramStarsValidationError(
                "Invalid Telegram Stars invoice payload"
            )

        body = f"{PAYLOAD_PREFIX}:{order_id}:{telegram_id}"

        expected_signature = hmac.new(
            self.settings.telegram_stars_invoice_secret.encode("utf-8"),
            body.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()[:32]

        if not hmac.compare_digest(
            supplied_signature,
            expected_signature,
        ):
            raise TelegramStarsValidationError(
                "Invalid Telegram Stars invoice signature"
            )

        return order_id, telegram_id

    async def create_invoice(
        self,
        *,
        order_id: int,
        telegram_id: int,
    ) -> StarsInvoice:
        order = await self._get_owned_stars_order(
            order_id=order_id,
            telegram_id=telegram_id,
        )

        if order.status != OrderStatus.WAITING_PAYMENT:
            raise TelegramStarsValidationError(
                "Order is no longer waiting for payment"
            )

        if is_due_or_past(order.expires_at):
            raise TelegramStarsValidationError(
                "Order has expired"
            )

        tariff = get_tariff(order.tariff_code)
        amount = self._expected_stars_amount(order)

        return StarsInvoice(
            order_id=order.id,
            payload=self.build_payload(
                order_id=order.id,
                telegram_id=telegram_id,
            ),
            title=f"VPN — {order.duration_days} days",
            description=tariff.title,
            label=f"VPN access for {order.duration_days} days",
            amount=amount,
        )

    async def validate_pre_checkout(
        self,
        *,
        telegram_id: int,
        invoice_payload: str,
        currency: str,
        total_amount: int,
    ) -> PreCheckoutDecision:
        try:
            order_id, payload_telegram_id = self.parse_payload(
                invoice_payload
            )

            if payload_telegram_id != telegram_id:
                raise TelegramStarsValidationError(
                    "This invoice was created for another user"
                )

            order = await self._get_owned_stars_order(
                order_id=order_id,
                telegram_id=telegram_id,
            )

            if currency != TELEGRAM_STARS_CURRENCY:
                raise TelegramStarsValidationError(
                    "Invalid invoice currency"
                )

            expected_amount = self._expected_stars_amount(order)

            if total_amount != expected_amount:
                raise TelegramStarsValidationError(
                    "The invoice amount has changed. "
                    "Please create a new order"
                )

            if order.status != OrderStatus.WAITING_PAYMENT:
                raise TelegramStarsValidationError(
                    "This order is no longer available for payment"
                )

            if is_due_or_past(order.expires_at):
                raise TelegramStarsValidationError(
                    "The order has expired. Please create a new order"
                )

            return PreCheckoutDecision(ok=True)

        except (
            TelegramStarsConfigurationError,
            TelegramStarsValidationError,
        ) as error:
            return PreCheckoutDecision(
                ok=False,
                error_message=str(error),
            )

    async def process_successful_payment(
            self,
            *,
            telegram_id: int,
            invoice_payload: str,
            currency: str,
            total_amount: int,
            telegram_payment_charge_id: str,
            raw_payload: str | None = None,
    ):
        order_id: int | None = None

        try:
            order_id, payload_telegram_id = self.parse_payload(
                invoice_payload
            )

            if payload_telegram_id != telegram_id:
                raise TelegramStarsValidationError(
                    "This payment belongs to another user"
                )

            if not telegram_payment_charge_id.strip():
                raise TelegramStarsValidationError(
                    "Telegram payment charge ID is missing"
                )

            order = await self._get_owned_stars_order(
                order_id=order_id,
                telegram_id=telegram_id,
            )

            if currency != TELEGRAM_STARS_CURRENCY:
                raise TelegramStarsValidationError(
                    "Invalid payment currency"
                )

            expected_amount = self._expected_stars_amount(order)

            if total_amount != expected_amount:
                raise TelegramStarsValidationError(
                    "Payment amount does not match the order"
                )

            if order.status not in {
                OrderStatus.WAITING_PAYMENT,
                OrderStatus.EXPIRED,
                OrderStatus.PAID,
                OrderStatus.ACTIVATED,
            }:
                raise TelegramStarsValidationError(
                    "This order cannot be activated by this payment"
                )

            event, payment, subscription, config_uri = (
                await self.activation_service
                .process_confirmed_payment_event_and_activate(
                    order_id=order.id,
                    amount=Decimal(total_amount),
                    provider=TELEGRAM_STARS_PROVIDER,
                    event_type=TELEGRAM_STARS_EVENT_TYPE,
                    external_event_id=telegram_payment_charge_id,
                    raw_payload=raw_payload,
                    allow_expired_order=True,
                )
            )

            if payment is None:
                raise TelegramStarsValidationError(
                    "Payment was not linked to the order"
                )

            if subscription is None:
                raise TelegramStarsValidationError(
                    "Subscription was not activated"
                )

            return event, payment, subscription, config_uri

        except Exception as error:
            await self._record_processing_failure(
                error=error,
                order_id=order_id,
                telegram_id=telegram_id,
                invoice_payload=invoice_payload,
                currency=currency,
                total_amount=total_amount,
                telegram_payment_charge_id=(
                    telegram_payment_charge_id
                ),
                raw_payload=raw_payload,
            )
            raise

    async def _record_processing_failure(
            self,
            *,
            error: Exception,
            order_id: int | None,
            telegram_id: int,
            invoice_payload: str,
            currency: str,
            total_amount: int,
            telegram_payment_charge_id: str,
            raw_payload: str | None,
    ) -> None:
        error_message = (
                            f"{type(error).__name__}: {error}"
                        )[:1000]

        if order_id is None:
            entity_type = "telegram_stars_payment"
            entity_id = None
        else:
            entity_type = "order"
            entity_id = order_id

        payload = json.dumps(
            {
                "order_id": order_id,
                "telegram_id": telegram_id,
                "telegram_payment_charge_id": (
                    telegram_payment_charge_id
                ),
                "currency": currency,
                "total_amount": total_amount,
                "invoice_payload": invoice_payload,
                "raw_payload": raw_payload,
                "error_class": type(error).__name__,
                "error_message": str(error),
            },
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )

        try:
            await self.session.rollback()

            pending = (
                await self.system_error_repository
                .get_unresolved_by_entity_and_error_type(
                    entity_type=entity_type,
                    entity_id=entity_id,
                    error_type=(
                        TELEGRAM_STARS_PROCESSING_ERROR_TYPE
                    ),
                )
            )

            if pending is None:
                await self.system_error_repository.create(
                    entity_type=entity_type,
                    entity_id=entity_id,
                    error_type=(
                        TELEGRAM_STARS_PROCESSING_ERROR_TYPE
                    ),
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
                "Failed to persist Telegram Stars processing error: "
                "order_id=%s telegram_id=%s charge_id=%s",
                order_id,
                telegram_id,
                telegram_payment_charge_id,
            )

            try:
                await self.session.rollback()
            except Exception:
                logger.exception(
                    "Failed to rollback after Telegram Stars "
                    "system_errors persistence failure."
                )

    async def _get_owned_stars_order(
        self,
        *,
        order_id: int,
        telegram_id: int,
    ):
        self.ensure_enabled()

        user = await self.user_repository.get_by_telegram_id(
            telegram_id
        )

        if user is None:
            raise TelegramStarsValidationError(
                "User not found"
            )

        order = await self.order_repository.get_by_id(order_id)

        if order is None or order.user_id != user.id:
            raise TelegramStarsValidationError(
                "Order not found"
            )

        if order.payment_method != PaymentMethod.TELEGRAM_STARS:
            raise TelegramStarsValidationError(
                "Order uses another payment method"
            )

        return order

    @staticmethod
    def _expected_stars_amount(order) -> int:
        amount = order.expected_amount

        if amount is None:
            tariff = get_tariff(order.tariff_code)
            amount = tariff.stars_price

        if amount is None:
            raise TelegramStarsValidationError(
                "Telegram Stars price is not configured"
            )

        decimal_amount = Decimal(str(amount))

        if decimal_amount <= 0:
            raise TelegramStarsValidationError(
                "Invalid Telegram Stars price"
            )

        if decimal_amount != decimal_amount.to_integral_value():
            raise TelegramStarsValidationError(
                "Telegram Stars price must be an integer"
            )

        return int(decimal_amount)