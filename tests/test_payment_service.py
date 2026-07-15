from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.common.enums import CurrencyCode, NetworkCode
from app.payment_core.enums.order_status import OrderStatus
from app.payment_core.enums.payment_method import PaymentMethod
from app.payment_core.enums.payment_status import PaymentStatus
from app.services.payment_service import PaymentService


class FakeSession:
    def __init__(self) -> None:
        self.commit_count = 0
        self.rollback_count = 0

    async def commit(self) -> None:
        self.commit_count += 1

    async def rollback(self) -> None:
        self.rollback_count += 1


class FakeOrderRepository:
    def __init__(self, *, order=None) -> None:
        self.order = order
        self.get_by_id_calls: list[int] = []
        self.mark_paid_calls: list[dict] = []

    async def get_by_id(self, order_id: int):
        self.get_by_id_calls.append(order_id)

        if self.order is None:
            return None

        if self.order.id != order_id:
            return None

        return self.order

    async def mark_paid(self, *, order, paid_at):
        self.mark_paid_calls.append({"order": order, "paid_at": paid_at})
        order.status = OrderStatus.PAID
        order.paid_at = paid_at
        return order


class FakePaymentRepository:
    def __init__(
        self,
        *,
        payment=None,
        existing_by_txid=None,
        existing_by_provider_payment_id=None,
    ) -> None:
        self.payment = payment
        self.existing_by_txid = existing_by_txid
        self.existing_by_provider_payment_id = existing_by_provider_payment_id
        self.get_by_id_calls: list[int] = []
        self.get_by_txid_calls: list[str] = []
        self.get_by_provider_payment_id_calls: list[str] = []
        self.create_calls: list[dict] = []
        self.mark_detected_calls: list[object] = []
        self.mark_confirmed_calls: list[object] = []
        self.next_payment_id = 700

    async def get_by_id(self, payment_id: int):
        self.get_by_id_calls.append(payment_id)

        if self.payment is None:
            return None

        if self.payment.id != payment_id:
            return None

        return self.payment

    async def get_by_txid(self, txid: str):
        self.get_by_txid_calls.append(txid)
        return self.existing_by_txid

    async def get_by_provider_payment_id(self, provider_payment_id: str):
        self.get_by_provider_payment_id_calls.append(provider_payment_id)
        return self.existing_by_provider_payment_id

    async def create(self, **kwargs):
        self.create_calls.append(kwargs)
        payment = SimpleNamespace(id=self.next_payment_id, **kwargs)
        self.next_payment_id += 1
        return payment

    async def mark_detected(self, payment):
        self.mark_detected_calls.append(payment)
        payment.status = PaymentStatus.DETECTED
        payment.detected_at = datetime.now(timezone.utc)
        return payment

    async def mark_confirmed(self, payment):
        self.mark_confirmed_calls.append(payment)
        payment.status = PaymentStatus.CONFIRMED
        payment.confirmed_at = datetime.now(timezone.utc)
        return payment


def make_order(
    *,
    order_id: int = 23,
    user_id: int = 7,
    status: OrderStatus = OrderStatus.WAITING_PAYMENT,
):
    return SimpleNamespace(
        id=order_id,
        user_id=user_id,
        status=status,
        payment_method=PaymentMethod.CRYPTO,
        payment_option_id=5,
        expected_currency=CurrencyCode.USDT,
        expected_network=NetworkCode.TRC20,
        paid_at=None,
    )


def make_payment(
    *,
    payment_id: int = 50,
    order_id: int = 23,
    status: PaymentStatus = PaymentStatus.NEW,
):
    return SimpleNamespace(
        id=payment_id,
        order_id=order_id,
        status=status,
        detected_at=None,
        confirmed_at=None,
    )


def make_service(
    *,
    order=None,
    payment=None,
    order_repository: FakeOrderRepository | None = None,
    payment_repository: FakePaymentRepository | None = None,
):
    service = PaymentService.__new__(PaymentService)
    service.session = FakeSession()
    service.order_repository = order_repository or FakeOrderRepository(order=order)
    service.payment_repository = payment_repository or FakePaymentRepository(payment=payment)
    return service


@pytest.mark.asyncio
async def test_create_payment_for_missing_order_raises_without_creating_payment():
    payment_repository = FakePaymentRepository()
    service = make_service(
        order=None,
        payment_repository=payment_repository,
    )

    with pytest.raises(ValueError, match="Order not found: 404"):
        await service._create_payment_for_order(
            order_id=404,
            amount=Decimal("4.00"),
            txid="tx-1",
        )

    assert payment_repository.create_calls == []
    assert payment_repository.get_by_txid_calls == []
    assert payment_repository.get_by_provider_payment_id_calls == []


@pytest.mark.asyncio
async def test_create_payment_returns_existing_payment_by_txid_without_creating_duplicate():
    order = make_order(order_id=23)
    existing_payment = make_payment(payment_id=51, order_id=23, status=PaymentStatus.DETECTED)
    payment_repository = FakePaymentRepository(existing_by_txid=existing_payment)
    service = make_service(order=order, payment_repository=payment_repository)

    result = await service._create_payment_for_order(
        order_id=23,
        amount=Decimal("4.00"),
        txid="tx-duplicate",
        provider_payment_id="provider-duplicate",
    )

    assert result is existing_payment
    assert payment_repository.get_by_txid_calls == ["tx-duplicate"]
    assert payment_repository.get_by_provider_payment_id_calls == []
    assert payment_repository.create_calls == []


@pytest.mark.asyncio
async def test_create_payment_returns_existing_payment_by_provider_payment_id_without_creating_duplicate():
    order = make_order(order_id=23)
    existing_payment = make_payment(payment_id=52, order_id=23, status=PaymentStatus.DETECTED)
    payment_repository = FakePaymentRepository(
        existing_by_provider_payment_id=existing_payment,
    )
    service = make_service(order=order, payment_repository=payment_repository)

    result = await service._create_payment_for_order(
        order_id=23,
        amount=Decimal("4.00"),
        provider_payment_id="provider-duplicate",
    )

    assert result is existing_payment
    assert payment_repository.get_by_txid_calls == []
    assert payment_repository.get_by_provider_payment_id_calls == ["provider-duplicate"]
    assert payment_repository.create_calls == []


@pytest.mark.asyncio
async def test_create_payment_copies_order_payment_fields_and_payload_to_new_payment():
    order = make_order(order_id=23, user_id=7)
    payment_repository = FakePaymentRepository()
    service = make_service(order=order, payment_repository=payment_repository)

    result = await service._create_payment_for_order(
        order_id=23,
        amount=Decimal("4.00"),
        txid="tx-1",
        provider_payment_id="provider-1",
        address_from="wallet-from",
        address_to="wallet-to",
        memo_tag="memo-1",
        confirmations=12,
        raw_payload='{"raw":true}',
        initial_status=PaymentStatus.DETECTED,
    )

    assert result.id == 700
    assert payment_repository.create_calls == [
        {
            "order_id": 23,
            "user_id": 7,
            "payment_method": PaymentMethod.CRYPTO,
            "payment_option_id": 5,
            "amount": Decimal("4.00"),
            "currency": CurrencyCode.USDT,
            "network": NetworkCode.TRC20,
            "txid": "tx-1",
            "provider_payment_id": "provider-1",
            "address_from": "wallet-from",
            "address_to": "wallet-to",
            "memo_tag": "memo-1",
            "confirmations": 12,
            "raw_payload": '{"raw":true}',
            "status": PaymentStatus.DETECTED,
        }
    ]


@pytest.mark.asyncio
async def test_mark_payment_detected_raises_for_missing_payment():
    service = make_service(payment=None)

    with pytest.raises(ValueError, match="Payment not found: 404"):
        await service._mark_payment_detected(404)


@pytest.mark.asyncio
async def test_mark_payment_detected_changes_new_payment_to_detected():
    payment = make_payment(payment_id=50, status=PaymentStatus.NEW)
    payment_repository = FakePaymentRepository(payment=payment)
    service = make_service(payment_repository=payment_repository)

    result = await service._mark_payment_detected(50)

    assert result is payment
    assert payment.status == PaymentStatus.DETECTED
    assert payment.detected_at is not None
    assert payment_repository.mark_detected_calls == [payment]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status",
    [
        PaymentStatus.DETECTED,
        PaymentStatus.CONFIRMED,
        PaymentStatus.INVALID,
        PaymentStatus.DUPLICATE,
        PaymentStatus.EXPIRED,
    ],
)
async def test_mark_payment_detected_is_idempotent_for_detected_and_final_statuses(status):
    payment = make_payment(payment_id=50, status=status)
    payment_repository = FakePaymentRepository(payment=payment)
    service = make_service(payment_repository=payment_repository)

    result = await service._mark_payment_detected(50)

    assert result is payment
    assert payment.status == status
    assert payment.detected_at is None
    assert payment_repository.mark_detected_calls == []


@pytest.mark.asyncio
async def test_confirm_payment_raises_for_missing_payment():
    service = make_service(payment=None)

    with pytest.raises(ValueError, match="Payment not found: 404"):
        await service._confirm_payment(404)


@pytest.mark.asyncio
async def test_confirm_payment_is_idempotent_for_already_confirmed_payment():
    order = make_order(order_id=23, status=OrderStatus.WAITING_PAYMENT)
    payment = make_payment(payment_id=50, order_id=23, status=PaymentStatus.CONFIRMED)
    order_repository = FakeOrderRepository(order=order)
    payment_repository = FakePaymentRepository(payment=payment)
    service = make_service(
        order_repository=order_repository,
        payment_repository=payment_repository,
    )

    result_payment, result_order = await service._confirm_payment(50)

    assert result_payment is payment
    assert result_order is order
    assert order.status == OrderStatus.WAITING_PAYMENT
    assert payment_repository.mark_confirmed_calls == []
    assert order_repository.mark_paid_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status",
    [PaymentStatus.INVALID, PaymentStatus.DUPLICATE, PaymentStatus.EXPIRED],
)
async def test_confirm_payment_does_not_confirm_invalid_duplicate_or_expired_payments(status):
    order = make_order(order_id=23, status=OrderStatus.WAITING_PAYMENT)
    payment = make_payment(payment_id=50, order_id=23, status=status)
    order_repository = FakeOrderRepository(order=order)
    payment_repository = FakePaymentRepository(payment=payment)
    service = make_service(
        order_repository=order_repository,
        payment_repository=payment_repository,
    )

    result_payment, result_order = await service._confirm_payment(50)

    assert result_payment is payment
    assert result_order is order
    assert payment.status == status
    assert order.status == OrderStatus.WAITING_PAYMENT
    assert payment_repository.mark_confirmed_calls == []
    assert order_repository.mark_paid_calls == []


@pytest.mark.asyncio
async def test_confirm_payment_marks_payment_confirmed_and_waiting_order_paid():
    order = make_order(order_id=23, status=OrderStatus.WAITING_PAYMENT)
    payment = make_payment(payment_id=50, order_id=23, status=PaymentStatus.DETECTED)
    order_repository = FakeOrderRepository(order=order)
    payment_repository = FakePaymentRepository(payment=payment)
    service = make_service(
        order_repository=order_repository,
        payment_repository=payment_repository,
    )

    before_call = datetime.now(timezone.utc)
    result_payment, result_order = await service._confirm_payment(50)
    after_call = datetime.now(timezone.utc)

    assert result_payment is payment
    assert result_order is order
    assert payment.status == PaymentStatus.CONFIRMED
    assert payment.confirmed_at is not None
    assert payment.confirmed_at >= before_call
    assert payment.confirmed_at <= after_call
    assert order.status == OrderStatus.PAID
    assert order.paid_at == payment.confirmed_at
    assert payment_repository.mark_confirmed_calls == [payment]
    assert order_repository.mark_paid_calls == [
        {"order": order, "paid_at": payment.confirmed_at}
    ]

@pytest.mark.asyncio
async def test_confirm_payment_can_mark_expired_order_paid_when_explicitly_allowed():
    order = make_order(
        order_id=23,
        status=OrderStatus.EXPIRED,
    )
    payment = make_payment(
        payment_id=50,
        order_id=23,
        status=PaymentStatus.DETECTED,
    )

    order_repository = FakeOrderRepository(order=order)
    payment_repository = FakePaymentRepository(payment=payment)

    service = make_service(
        order_repository=order_repository,
        payment_repository=payment_repository,
    )

    result_payment, result_order = await service._confirm_payment(
        50,
        allow_expired_order=True,
    )

    assert result_payment is payment
    assert result_order is order
    assert payment.status == PaymentStatus.CONFIRMED
    assert order.status == OrderStatus.PAID
    assert order.paid_at == payment.confirmed_at
    assert order_repository.mark_paid_calls == [
        {
            "order": order,
            "paid_at": payment.confirmed_at,
        }
    ]

@pytest.mark.asyncio
async def test_confirm_payment_confirms_payment_but_does_not_mark_non_waiting_order_paid():
    order = make_order(order_id=23, status=OrderStatus.ACTIVATED)
    payment = make_payment(payment_id=50, order_id=23, status=PaymentStatus.DETECTED)
    order_repository = FakeOrderRepository(order=order)
    payment_repository = FakePaymentRepository(payment=payment)
    service = make_service(
        order_repository=order_repository,
        payment_repository=payment_repository,
    )

    result_payment, result_order = await service._confirm_payment(50)

    assert result_payment is payment
    assert result_order is order
    assert payment.status == PaymentStatus.CONFIRMED
    assert order.status == OrderStatus.ACTIVATED
    assert order_repository.mark_paid_calls == []


@pytest.mark.asyncio
async def test_public_create_payment_commits_on_success():
    order = make_order(order_id=23)
    service = make_service(order=order)

    payment = await service.create_payment_for_order(
        order_id=23,
        amount=Decimal("4.00"),
    )

    assert payment.id == 700
    assert service.session.commit_count == 1
    assert service.session.rollback_count == 0


@pytest.mark.asyncio
async def test_public_create_payment_rolls_back_on_error():
    service = make_service(order=None)

    with pytest.raises(ValueError, match="Order not found: 404"):
        await service.create_payment_for_order(
            order_id=404,
            amount=Decimal("4.00"),
        )

    assert service.session.commit_count == 0
    assert service.session.rollback_count == 1


@pytest.mark.asyncio
async def test_public_mark_payment_detected_commits_on_success():
    payment = make_payment(payment_id=50, status=PaymentStatus.NEW)
    service = make_service(payment=payment)

    result = await service.mark_payment_detected(50)

    assert result is payment
    assert payment.status == PaymentStatus.DETECTED
    assert service.session.commit_count == 1
    assert service.session.rollback_count == 0


@pytest.mark.asyncio
async def test_public_confirm_payment_rolls_back_on_error():
    service = make_service(payment=None)

    with pytest.raises(ValueError, match="Payment not found: 404"):
        await service.confirm_payment(404)

    assert service.session.commit_count == 0
    assert service.session.rollback_count == 1