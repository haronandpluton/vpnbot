import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.common.enums import TariffCode
from app.payment_core.enums.order_status import OrderStatus
from app.payment_core.enums.payment_method import PaymentMethod
from app.services.telegram_stars_payment_service import (
    TELEGRAM_STARS_CURRENCY,
    TELEGRAM_STARS_PROCESSING_ERROR_TYPE,
    TelegramStarsConfigurationError,
    TelegramStarsPaymentService,
    TelegramStarsValidationError,
)


class FakeSession:
    def __init__(self) -> None:
        self.commit_count = 0
        self.rollback_count = 0

    async def commit(self) -> None:
        self.commit_count += 1

    async def rollback(self) -> None:
        self.rollback_count += 1


class FakeUserRepository:
    def __init__(self, user) -> None:
        self.user = user

    async def get_by_telegram_id(self, telegram_id: int):
        if (
            self.user is not None
            and self.user.telegram_id == telegram_id
        ):
            return self.user

        return None


class FakeOrderRepository:
    def __init__(self, order) -> None:
        self.order = order

    async def get_by_id(self, order_id: int):
        if (
            self.order is not None
            and self.order.id == order_id
        ):
            return self.order

        return None


def make_settings(
    *,
    enabled: bool = True,
    secret: str = "test-stars-secret",
):
    return SimpleNamespace(
        telegram_stars_enabled=enabled,
        telegram_stars_invoice_secret=secret,
    )


def make_order(
    *,
    status: OrderStatus = OrderStatus.WAITING_PAYMENT,
    payment_method: PaymentMethod = PaymentMethod.TELEGRAM_STARS,
    expected_amount: Decimal = Decimal("300"),
    expires_at: datetime | None = None,
):
    return SimpleNamespace(
        id=41,
        user_id=7,
        status=status,
        tariff_code=TariffCode.PERIOD_1_MONTH,
        duration_days=33,
        payment_method=payment_method,
        expected_amount=expected_amount,
        expires_at=expires_at
        or datetime.now(UTC) + timedelta(minutes=10),
    )

class FakeActivationService:
    def __init__(
        self,
        *,
        error: Exception | None = None,
    ) -> None:
        self.calls: list[dict] = []
        self.error = error

        self.event = SimpleNamespace(id=1)
        self.payment = SimpleNamespace(id=2)
        self.subscription = SimpleNamespace(id=3)
        self.config_uri = "https://connect.example/uuid"

    async def process_confirmed_payment_event_and_activate(
        self,
        **kwargs,
    ):
        self.calls.append(kwargs)

        if self.error is not None:
            raise self.error

        return (
            self.event,
            self.payment,
            self.subscription,
            self.config_uri,
        )


class FakeSystemErrorRepository:
    def __init__(
        self,
        *,
        pending=None,
        fail_create: bool = False,
    ) -> None:
        self.pending = pending
        self.fail_create = fail_create

        self.lookup_calls: list[dict] = []
        self.create_calls: list[dict] = []
        self.update_calls: list[dict] = []

    async def get_unresolved_by_entity_and_error_type(
        self,
        **kwargs,
    ):
        self.lookup_calls.append(kwargs)
        return self.pending

    async def create(self, **kwargs):
        if self.fail_create:
            raise RuntimeError(
                "system_errors unavailable"
            )

        self.create_calls.append(kwargs)

        self.pending = SimpleNamespace(
            id=900,
            retry_count=0,
            **kwargs,
        )

        return self.pending

    async def update_pending_failure(
        self,
        error,
        **kwargs,
    ):
        self.update_calls.append(
            {
                "error": error,
                **kwargs,
            }
        )

        error.entity_type = kwargs["entity_type"]
        error.entity_id = kwargs["entity_id"]
        error.error_message = kwargs["error_message"]
        error.payload = kwargs["payload"]
        error.retry_count += 1

        return error
def make_service(
    *,
    order=None,
    user=None,
    activation_service=None,
    system_error_repository=None,
    session=None,
):
    fake_session = session or FakeSession()
    fake_system_error_repository = (
        system_error_repository
        or FakeSystemErrorRepository()
    )

    service = TelegramStarsPaymentService(
        fake_session,
        settings=make_settings(),
        activation_service=activation_service,
        system_error_repository=(
            fake_system_error_repository
        ),
    )

    service.user_repository = FakeUserRepository(
        user
        or SimpleNamespace(
            id=7,
            telegram_id=123,
        )
    )

    service.order_repository = FakeOrderRepository(
        order or make_order()
    )

    return service


def test_stars_payload_round_trip():
    service = make_service()

    payload = service.build_payload(
        order_id=41,
        telegram_id=123,
    )

    assert service.parse_payload(payload) == (41, 123)
    assert payload.startswith("vpn_stars:41:123:")
    assert len(payload.encode("utf-8")) <= 128


def test_stars_payload_rejects_modified_order_id():
    service = make_service()

    payload = service.build_payload(
        order_id=41,
        telegram_id=123,
    )

    modified_payload = payload.replace(
        "vpn_stars:41:",
        "vpn_stars:42:",
    )

    with pytest.raises(
        TelegramStarsValidationError,
        match="signature",
    ):
        service.parse_payload(modified_payload)


def test_stars_payload_rejects_modified_telegram_id():
    service = make_service()

    payload = service.build_payload(
        order_id=41,
        telegram_id=123,
    )

    modified_payload = payload.replace(
        ":123:",
        ":999:",
    )

    with pytest.raises(
        TelegramStarsValidationError,
        match="signature",
    ):
        service.parse_payload(modified_payload)


def test_stars_service_rejects_disabled_payments():
    service = TelegramStarsPaymentService(
        FakeSession(),
        settings=make_settings(enabled=False),
    )

    with pytest.raises(
        TelegramStarsConfigurationError,
        match="disabled",
    ):
        service.build_payload(
            order_id=41,
            telegram_id=123,
        )


def test_stars_service_rejects_empty_secret():
    service = TelegramStarsPaymentService(
        FakeSession(),
        settings=make_settings(secret=""),
    )

    with pytest.raises(
        TelegramStarsConfigurationError,
        match="SECRET",
    ):
        service.build_payload(
            order_id=41,
            telegram_id=123,
        )


@pytest.mark.asyncio
async def test_create_invoice_returns_300_xtr_for_33_days():
    service = make_service()

    invoice = await service.create_invoice(
        order_id=41,
        telegram_id=123,
    )

    assert invoice.order_id == 41
    assert invoice.amount == 300
    assert invoice.title == "VPN — 33 days"
    assert invoice.description == (
        "33 days (30 days + 3 days 🎁)"
    )
    assert invoice.label == "VPN access for 33 days"
    assert service.parse_payload(invoice.payload) == (
        41,
        123,
    )


@pytest.mark.asyncio
async def test_create_invoice_rejects_wrong_user():
    service = make_service()

    with pytest.raises(
        TelegramStarsValidationError,
        match="User not found",
    ):
        await service.create_invoice(
            order_id=41,
            telegram_id=999,
        )


@pytest.mark.asyncio
async def test_create_invoice_rejects_crypto_order():
    service = make_service(
        order=make_order(
            payment_method=PaymentMethod.CRYPTO,
        )
    )

    with pytest.raises(
        TelegramStarsValidationError,
        match="another payment method",
    ):
        await service.create_invoice(
            order_id=41,
            telegram_id=123,
        )


@pytest.mark.asyncio
async def test_create_invoice_rejects_expired_order():
    service = make_service(
        order=make_order(
            expires_at=(
                datetime.now(UTC)
                - timedelta(seconds=1)
            ),
        )
    )

    with pytest.raises(
        TelegramStarsValidationError,
        match="expired",
    ):
        await service.create_invoice(
            order_id=41,
            telegram_id=123,
        )


@pytest.mark.asyncio
async def test_create_invoice_rejects_processed_order():
    service = make_service(
        order=make_order(
            status=OrderStatus.ACTIVATED,
        )
    )

    with pytest.raises(
        TelegramStarsValidationError,
        match="no longer waiting",
    ):
        await service.create_invoice(
            order_id=41,
            telegram_id=123,
        )

@pytest.mark.asyncio
async def test_pre_checkout_accepts_exact_stars_payment():
    service = make_service()

    payload = service.build_payload(
        order_id=41,
        telegram_id=123,
    )

    decision = await service.validate_pre_checkout(
        telegram_id=123,
        invoice_payload=payload,
        currency=TELEGRAM_STARS_CURRENCY,
        total_amount=300,
    )

    assert decision.ok is True
    assert decision.error_message is None

@pytest.mark.asyncio
async def test_pre_checkout_rejects_wrong_amount_and_user():
    service = make_service()

    payload = service.build_payload(
        order_id=41,
        telegram_id=123,
    )

    wrong_amount = await service.validate_pre_checkout(
        telegram_id=123,
        invoice_payload=payload,
        currency=TELEGRAM_STARS_CURRENCY,
        total_amount=299,
    )

    wrong_user = await service.validate_pre_checkout(
        telegram_id=999,
        invoice_payload=payload,
        currency=TELEGRAM_STARS_CURRENCY,
        total_amount=300,
    )

    assert wrong_amount.ok is False
    assert "amount" in wrong_amount.error_message

    assert wrong_user.ok is False
    assert "another user" in wrong_user.error_message

@pytest.mark.asyncio
async def test_pre_checkout_rejects_expired_order():
    service = make_service(
        order=make_order(
            expires_at=(
                datetime.now(UTC)
                - timedelta(seconds=1)
            ),
        )
    )

    payload = service.build_payload(
        order_id=41,
        telegram_id=123,
    )

    decision = await service.validate_pre_checkout(
        telegram_id=123,
        invoice_payload=payload,
        currency=TELEGRAM_STARS_CURRENCY,
        total_amount=300,
    )

    assert decision.ok is False
    assert "expired" in decision.error_message

@pytest.mark.asyncio
async def test_successful_payment_activates_order_through_payment_core():
    activation_service = FakeActivationService()

    service = make_service(
        activation_service=activation_service,
    )

    payload = service.build_payload(
        order_id=41,
        telegram_id=123,
    )

    result = await service.process_successful_payment(
        telegram_id=123,
        invoice_payload=payload,
        currency="XTR",
        total_amount=300,
        telegram_payment_charge_id="charge-123",
        raw_payload='{"currency": "XTR"}',
    )

    assert result == (
        activation_service.event,
        activation_service.payment,
        activation_service.subscription,
        activation_service.config_uri,
    )

    assert activation_service.calls == [
        {
            "order_id": 41,
            "amount": Decimal("300"),
            "provider": "telegram_stars",
            "event_type": "successful_payment",
            "external_event_id": "charge-123",
            "raw_payload": '{"currency": "XTR"}',
            "allow_expired_order": True,
        }
    ]

@pytest.mark.asyncio
async def test_successful_payment_rejects_wrong_amount():
    activation_service = FakeActivationService()

    service = make_service(
        activation_service=activation_service,
    )

    payload = service.build_payload(
        order_id=41,
        telegram_id=123,
    )

    with pytest.raises(
        TelegramStarsValidationError,
        match="amount",
    ):
        await service.process_successful_payment(
            telegram_id=123,
            invoice_payload=payload,
            currency="XTR",
            total_amount=301,
            telegram_payment_charge_id="charge-123",
        )

    assert activation_service.calls == []

@pytest.mark.asyncio
async def test_successful_payment_processing_failure_is_saved_to_system_errors():
    activation_service = FakeActivationService(
        error=RuntimeError("vpn mutation failed")
    )
    system_error_repository = FakeSystemErrorRepository()
    session = FakeSession()

    service = make_service(
        activation_service=activation_service,
        system_error_repository=system_error_repository,
        session=session,
    )

    invoice_payload = service.build_payload(
        order_id=41,
        telegram_id=123,
    )

    with pytest.raises(
        RuntimeError,
        match="vpn mutation failed",
    ):
        await service.process_successful_payment(
            telegram_id=123,
            invoice_payload=invoice_payload,
            currency="XTR",
            total_amount=300,
            telegram_payment_charge_id="charge-123",
            raw_payload='{"update_id": 500}',
        )

    assert system_error_repository.lookup_calls == [
        {
            "entity_type": "order",
            "entity_id": 41,
            "error_type": (
                TELEGRAM_STARS_PROCESSING_ERROR_TYPE
            ),
        }
    ]

    assert len(
        system_error_repository.create_calls
    ) == 1

    created = system_error_repository.create_calls[0]

    assert created["entity_type"] == "order"
    assert created["entity_id"] == 41
    assert created["error_type"] == (
        TELEGRAM_STARS_PROCESSING_ERROR_TYPE
    )
    assert created["error_message"] == (
        "RuntimeError: vpn mutation failed"
    )

    payload = json.loads(created["payload"])

    assert payload["order_id"] == 41
    assert payload["telegram_id"] == 123
    assert payload["telegram_payment_charge_id"] == (
        "charge-123"
    )
    assert payload["currency"] == "XTR"
    assert payload["total_amount"] == 300
    assert payload["error_class"] == "RuntimeError"
    assert payload["error_message"] == (
        "vpn mutation failed"
    )

    assert session.rollback_count == 1
    assert session.commit_count == 1

@pytest.mark.asyncio
async def test_repeated_stars_processing_failure_updates_pending_error():
    pending = SimpleNamespace(
        id=900,
        entity_type="order",
        entity_id=41,
        error_type=(
            TELEGRAM_STARS_PROCESSING_ERROR_TYPE
        ),
        error_message="first failure",
        payload="{}",
        retry_count=0,
    )

    system_error_repository = FakeSystemErrorRepository(
        pending=pending
    )
    session = FakeSession()

    service = make_service(
        activation_service=FakeActivationService(
            error=RuntimeError("vpn mutation failed")
        ),
        system_error_repository=system_error_repository,
        session=session,
    )

    invoice_payload = service.build_payload(
        order_id=41,
        telegram_id=123,
    )

    for _ in range(2):
        with pytest.raises(
            RuntimeError,
            match="vpn mutation failed",
        ):
            await service.process_successful_payment(
                telegram_id=123,
                invoice_payload=invoice_payload,
                currency="XTR",
                total_amount=300,
                telegram_payment_charge_id="charge-123",
            )

    assert system_error_repository.create_calls == []
    assert len(
        system_error_repository.update_calls
    ) == 2

    assert pending.retry_count == 2
    assert pending.entity_type == "order"
    assert pending.entity_id == 41

    assert session.rollback_count == 2
    assert session.commit_count == 2

@pytest.mark.asyncio
async def test_system_error_failure_does_not_mask_original_stars_error():
    session = FakeSession()
    system_error_repository = FakeSystemErrorRepository(
        fail_create=True
    )

    service = make_service(
        activation_service=FakeActivationService(
            error=RuntimeError("vpn mutation failed")
        ),
        system_error_repository=system_error_repository,
        session=session,
    )

    invoice_payload = service.build_payload(
        order_id=41,
        telegram_id=123,
    )

    with pytest.raises(
        RuntimeError,
        match="vpn mutation failed",
    ):
        await service.process_successful_payment(
            telegram_id=123,
            invoice_payload=invoice_payload,
            currency="XTR",
            total_amount=300,
            telegram_payment_charge_id="charge-123",
        )

    assert session.commit_count == 0
    assert session.rollback_count == 2