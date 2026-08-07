from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.payment_core.enums.order_status import OrderStatus
from app.payment_core.enums.payment_status import PaymentStatus
from app.services.payment_activation_service import PaymentActivationService


class FakePaymentEventService:
    def __init__(self, result) -> None:
        self.result = result
        self.calls: list[dict] = []

    async def process_confirmed_event(self, **kwargs):
        self.calls.append(kwargs)
        return self.result


class FakeAdsGramTrackingService:
    def __init__(
        self,
        *,
        should_fail: bool = False,
    ) -> None:
        self.should_fail = should_fail
        self.calls: list[dict] = []

    async def enqueue_purchase_conversion(self, **kwargs):
        self.calls.append(kwargs)

        if self.should_fail:
            raise RuntimeError(
                "adsgram queue failed"
            )

        return SimpleNamespace(
            status="queued",
            goal_type=2,
        )

class FakeAdsGramRecoveryService:
    def __init__(
        self,
        *,
        should_fail: bool = False,
    ) -> None:
        self.should_fail = should_fail
        self.calls: list[dict] = []

    async def record_purchase_failure(
        self,
        **kwargs,
    ) -> None:
        self.calls.append(kwargs)

        if self.should_fail:
            raise RuntimeError(
                "adsgram recovery failed"
            )

class FakeSubscriptionService:
    def __init__(self, *, should_fail: bool = False) -> None:
        self.should_fail = should_fail
        self.calls: list[int] = []
        self.subscription = SimpleNamespace(id=4, uuid="test-uuid")
        self.config_uri = "vless://test-config"

    async def activate_or_extend_by_order(self, order_id: int):
        self.calls.append(order_id)

        if self.should_fail:
            raise RuntimeError("activation failed")

        return self.subscription, self.config_uri

class FakeAdsGramSessionFactory:
    def __init__(self) -> None:
        self.session = SimpleNamespace(
            name="adsgram-session"
        )
        self.call_count = 0
        self.enter_count = 0
        self.exit_count = 0
        self.exit_error_types: list[
            type[BaseException] | None
        ] = []

    def __call__(self):
        self.call_count += 1
        return self

    async def __aenter__(self):
        self.enter_count += 1
        return self.session

    async def __aexit__(
        self,
        exc_type,
        exc,
        traceback,
    ):
        self.exit_count += 1
        self.exit_error_types.append(exc_type)
        return False

def make_service(
    *,
    event_result,
    subscription_service: (
        FakeSubscriptionService | None
    ) = None,
    adsgram_tracking_service: (
        FakeAdsGramTrackingService | None
    ) = None,
    session=None,
    adsgram_recovery_service: (
            FakeAdsGramRecoveryService | None
    ) = None,
):
    service = PaymentActivationService.__new__(
        PaymentActivationService
    )

    main_session = session or SimpleNamespace()
    tracking_service = (
        adsgram_tracking_service
        or FakeAdsGramTrackingService()
    )
    adsgram_session_factory = (
        FakeAdsGramSessionFactory()
    )
    recovery_service = (
        adsgram_recovery_service
        or FakeAdsGramRecoveryService()
    )

    def tracking_service_factory(session_arg):
        assert (
            session_arg
            is adsgram_session_factory.session
        )
        return tracking_service

    def recovery_service_factory(session_arg):
        assert (
            session_arg
            is adsgram_session_factory.session
        )
        return recovery_service

    service.session = main_session
    service.payment_event_service = (
        FakePaymentEventService(event_result)
    )
    service.subscription_service = (
        subscription_service
        or FakeSubscriptionService()
    )

    service.adsgram_session_factory = (
        adsgram_session_factory
    )
    service.adsgram_tracking_service_factory = (
        tracking_service_factory
    )
    service.adsgram_recovery_service_factory = (
        recovery_service_factory
    )
    # Оставляем ссылки для существующих assertions.
    service.adsgram_tracking_service = tracking_service
    service.adsgram_recovery_service = (
        recovery_service
    )
    service.adsgram_test_session_factory = (
        adsgram_session_factory
    )

    return service


def make_event(*, event_id: int = 1):
    return SimpleNamespace(id=event_id)


def make_payment(*, status: PaymentStatus = PaymentStatus.CONFIRMED):
    return SimpleNamespace(id=2, status=status)


def make_order(
    *,
    order_id: int = 3,
    user_id: int = 7,
    status: OrderStatus = OrderStatus.PAID,
):
    return SimpleNamespace(
        id=order_id,
        user_id=user_id,
        status=status,
    )


@pytest.mark.asyncio
async def test_confirmed_paid_order_activates_subscription_once_and_passes_event_payload():
    event = make_event()
    payment = make_payment(status=PaymentStatus.CONFIRMED)
    paid_order = make_order(order_id=23, status=OrderStatus.PAID)
    service = make_service(event_result=(event, payment, paid_order))

    result = await service.process_confirmed_payment_event_and_activate(
        order_id=23,
        amount=Decimal("4.00"),
        provider="cryptobot",
        event_type="invoice_paid",
        external_event_id="cryptobot:55822653",
        txid=None,
        address_from="payer",
        address_to="merchant",
        memo_tag="memo",
        confirmations=1,
        raw_payload='{"invoice_id": 55822653}',
    )

    subscription, config_uri = result[2], result[3]

    assert result[0] is event
    assert result[1] is payment
    assert subscription.id == 4
    assert config_uri == "vless://test-config"
    assert service.subscription_service.calls == [23]
    assert service.adsgram_tracking_service.calls == [
        {
            "user_id": 7,
            "order_id": 23,
            "payment_id": 2,
        }
    ]

    assert service.payment_event_service.calls == [
        {
            "order_id": 23,
            "amount": Decimal("4.00"),
            "provider": "cryptobot",
            "event_type": "invoice_paid",
            "external_event_id": "cryptobot:55822653",
            "txid": None,
            "address_from": "payer",
            "address_to": "merchant",
            "memo_tag": "memo",
            "confirmations": 1,
            "raw_payload": '{"invoice_id": 55822653}',
        }
    ]


@pytest.mark.asyncio
async def test_duplicate_existing_event_with_activated_order_uses_idempotent_subscription_path():
    event = make_event(event_id=10)
    payment = make_payment(status=PaymentStatus.CONFIRMED)
    already_activated_order = make_order(order_id=23, status=OrderStatus.ACTIVATED)
    service = make_service(event_result=(event, payment, already_activated_order))

    result = await service.process_confirmed_payment_event_and_activate(
        order_id=23,
        amount=Decimal("4.00"),
        provider="cryptobot",
        event_type="invoice_paid",
        external_event_id="cryptobot:55822653",
    )

    assert result[0] is event
    assert result[1] is payment
    assert result[2].uuid == "test-uuid"
    assert result[3] == "vless://test-config"
    assert service.subscription_service.calls == [23]
    assert service.adsgram_tracking_service.calls == [
        {
            "user_id": 7,
            "order_id": 23,
            "payment_id": 2,
        }
    ]

@pytest.mark.asyncio
async def test_event_without_payment_does_not_activate_subscription():
    event = make_event()
    service = make_service(event_result=(event, None, None))

    result = await service.process_confirmed_payment_event_and_activate(
        order_id=23,
        amount=Decimal("4.00"),
        provider="cryptobot",
        event_type="invoice_paid",
        external_event_id="cryptobot:55822653",
    )

    assert result == (event, None, None, None)
    assert service.subscription_service.calls == []
    assert service.adsgram_tracking_service.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payment_status",
    [
        PaymentStatus.NEW,
        PaymentStatus.DETECTED,
        PaymentStatus.INVALID,
        PaymentStatus.DUPLICATE,
        PaymentStatus.EXPIRED,
        PaymentStatus.ERROR,
    ],
)
async def test_non_confirmed_payment_does_not_activate_subscription(payment_status):
    event = make_event()
    payment = make_payment(status=payment_status)
    paid_order = make_order(order_id=23, status=OrderStatus.PAID)
    service = make_service(event_result=(event, payment, paid_order))

    result = await service.process_confirmed_payment_event_and_activate(
        order_id=23,
        amount=Decimal("4.00"),
        provider="cryptobot",
        event_type="invoice_paid",
        external_event_id="cryptobot:55822653",
    )

    assert result == (event, payment, None, None)
    assert service.subscription_service.calls == []
    assert service.adsgram_tracking_service.calls == []


@pytest.mark.asyncio
async def test_confirmed_payment_without_paid_order_does_not_activate_subscription():
    event = make_event()
    payment = make_payment(status=PaymentStatus.CONFIRMED)
    service = make_service(event_result=(event, payment, None))

    result = await service.process_confirmed_payment_event_and_activate(
        order_id=23,
        amount=Decimal("4.00"),
        provider="cryptobot",
        event_type="invoice_paid",
        external_event_id="cryptobot:55822653",
    )

    assert result == (event, payment, None, None)
    assert service.subscription_service.calls == []
    assert service.adsgram_tracking_service.calls == []


@pytest.mark.asyncio
async def test_confirmed_payment_with_waiting_order_does_not_activate_subscription():
    event = make_event()
    payment = make_payment(status=PaymentStatus.CONFIRMED)
    waiting_order = make_order(order_id=23, status=OrderStatus.WAITING_PAYMENT)
    service = make_service(event_result=(event, payment, waiting_order))

    result = await service.process_confirmed_payment_event_and_activate(
        order_id=23,
        amount=Decimal("4.00"),
        provider="cryptobot",
        event_type="invoice_paid",
        external_event_id="cryptobot:55822653",
    )

    assert result == (event, payment, None, None)
    assert service.subscription_service.calls == []
    assert service.adsgram_tracking_service.calls == []


@pytest.mark.asyncio
async def test_activation_error_is_not_silently_converted_to_success():
    event = make_event()
    payment = make_payment(status=PaymentStatus.CONFIRMED)
    paid_order = make_order(order_id=23, status=OrderStatus.PAID)
    subscription_service = FakeSubscriptionService(should_fail=True)
    service = make_service(
        event_result=(event, payment, paid_order),
        subscription_service=subscription_service,
    )

    with pytest.raises(RuntimeError, match="activation failed"):
        await service.process_confirmed_payment_event_and_activate(
            order_id=23,
            amount=Decimal("4.00"),
            provider="cryptobot",
            event_type="invoice_paid",
            external_event_id="cryptobot:55822653",
        )

    assert subscription_service.calls == [23]

@pytest.mark.asyncio
async def test_activation_passes_allow_expired_order_only_when_requested():
    event = make_event()
    payment = make_payment(
        status=PaymentStatus.CONFIRMED,
    )
    paid_order = make_order(
        order_id=23,
        status=OrderStatus.PAID,
    )

    service = make_service(
        event_result=(
            event,
            payment,
            paid_order,
        )
    )

    await service.process_confirmed_payment_event_and_activate(
        order_id=23,
        amount=Decimal(300),
        provider="telegram_stars",
        event_type="successful_payment",
        external_event_id="charge-123",
        allow_expired_order=True,
    )

    assert service.payment_event_service.calls == [
        {
            "order_id": 23,
            "amount": Decimal(300),
            "provider": "telegram_stars",
            "event_type": "successful_payment",
            "external_event_id": "charge-123",
            "txid": None,
            "address_from": None,
            "address_to": None,
            "memo_tag": None,
            "confirmations": None,
            "raw_payload": None,
            "allow_expired_order": True,
        }
    ]

class RollbackSession:
    def __init__(self) -> None:
        self.rollback_count = 0

    async def rollback(self) -> None:
        self.rollback_count += 1


@pytest.mark.asyncio
async def test_adsgram_enqueue_failure_does_not_block_subscription_activation():
    event = make_event()
    payment = make_payment(
        status=PaymentStatus.CONFIRMED
    )
    paid_order = make_order(
        order_id=23,
        status=OrderStatus.PAID,
    )

    adsgram_service = FakeAdsGramTrackingService(
        should_fail=True
    )
    session = RollbackSession()

    service = make_service(
        event_result=(
            event,
            payment,
            paid_order,
        ),
        adsgram_tracking_service=adsgram_service,
        session=session,
    )

    result = (
        await service
        .process_confirmed_payment_event_and_activate(
            order_id=23,
            amount=Decimal("4.00"),
            provider="cryptobot",
            event_type="invoice_paid",
            external_event_id="cryptobot:55822653",
        )
    )

    assert result[2].uuid == "test-uuid"
    assert service.subscription_service.calls == [23]

    assert adsgram_service.calls == [
        {
            "user_id": 7,
            "order_id": 23,
            "payment_id": 2,
        }
    ]
    assert len(
        service.adsgram_recovery_service.calls
    ) == 1

    recovery_call = (
        service.adsgram_recovery_service.calls[0]
    )

    assert recovery_call["user_id"] == 7
    assert recovery_call["order_id"] == 23
    assert recovery_call["payment_id"] == 2

    assert isinstance(
        recovery_call["error"],
        RuntimeError,
    )
    assert (
        str(recovery_call["error"])
        == "adsgram queue failed"
    )
    # Основная payment/subscription-сессия не откатывалась.
    assert session.rollback_count == 0

    # Ошибка произошла внутри отдельной AdsGram-сессии.
    assert (
            service.adsgram_test_session_factory.call_count
            == 2
    )
    assert (
            service.adsgram_test_session_factory.enter_count
            == 2
    )
    assert (
            service.adsgram_test_session_factory.exit_count
            == 2
    )
    assert (
            service.adsgram_test_session_factory
            .exit_error_types
            == [RuntimeError, None]
    )

@pytest.mark.asyncio
async def test_adsgram_recovery_failure_does_not_block_subscription_activation():
    event = make_event()
    payment = make_payment(
        status=PaymentStatus.CONFIRMED
    )
    paid_order = make_order(
        order_id=23,
        status=OrderStatus.PAID,
    )

    adsgram_service = FakeAdsGramTrackingService(
        should_fail=True
    )
    recovery_service = FakeAdsGramRecoveryService(
        should_fail=True
    )
    session = RollbackSession()

    service = make_service(
        event_result=(
            event,
            payment,
            paid_order,
        ),
        adsgram_tracking_service=adsgram_service,
        adsgram_recovery_service=recovery_service,
        session=session,
    )

    result = (
        await service
        .process_confirmed_payment_event_and_activate(
            order_id=23,
            amount=Decimal("4.00"),
            provider="cryptobot",
            event_type="invoice_paid",
            external_event_id="cryptobot:55822653",
        )
    )

    # Несмотря на два последовательных сбоя аналитики,
    # основная бизнес-операция завершилась.
    assert result[0] is event
    assert result[1] is payment
    assert result[2].uuid == "test-uuid"
    assert result[3] == "vless://test-config"

    assert service.subscription_service.calls == [23]

    assert adsgram_service.calls == [
        {
            "user_id": 7,
            "order_id": 23,
            "payment_id": 2,
        }
    ]

    assert len(recovery_service.calls) == 1

    recovery_call = recovery_service.calls[0]

    assert recovery_call["user_id"] == 7
    assert recovery_call["order_id"] == 23
    assert recovery_call["payment_id"] == 2
    assert isinstance(
        recovery_call["error"],
        RuntimeError,
    )
    assert (
        str(recovery_call["error"])
        == "adsgram queue failed"
    )

    # Основная payment/subscription session
    # вообще не откатывалась.
    assert session.rollback_count == 0

    # Первая отдельная session — enqueue.
    # Вторая отдельная session — recovery.
    assert (
        service.adsgram_test_session_factory.call_count
        == 2
    )
    assert (
        service.adsgram_test_session_factory.enter_count
        == 2
    )
    assert (
        service.adsgram_test_session_factory.exit_count
        == 2
    )
    assert (
        service.adsgram_test_session_factory
        .exit_error_types
        == [RuntimeError, RuntimeError]
    )