from __future__ import annotations

from datetime import datetime, UTC, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

import app.payment_polling.processor as polling_processor_module
import app.services.subscription_service as subscription_service_module
from app.common.enums import CurrencyCode, NetworkCode, TariffCode
from app.database.base import Base
from app.database.models import Order, Payment, PaymentEvent, Subscription
from app.database.repositories.orders import OrderRepository
from app.database.repositories.payment_options import PaymentOptionRepository
from app.database.repositories.users import UserRepository
from app.payment_adapters.base import NormalizedTransaction
from app.payment_core.enums.order_status import OrderStatus
from app.payment_core.enums.payment_method import PaymentMethod
from app.payment_core.enums.payment_status import PaymentStatus
from app.payment_core.enums.subscription_status import SubscriptionStatus
from app.payment_polling.processor import PaymentPollingProcessor
from app.services.payment_activation_service import PaymentActivationService
from app.services.telegram_stars_payment_service import (
    TelegramStarsPaymentService,
)

from app.services.order_service import OrderService

class NaiveDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        current = datetime.now()
        return cls(
            current.year,
            current.month,
            current.day,
            current.hour,
            current.minute,
            current.second,
            current.microsecond,
        )


class AsyncSessionAdapter:
    def __init__(self, sync_session) -> None:
        self.sync_session = sync_session

    def add(self, instance) -> None:
        self.sync_session.add(instance)

    async def execute(self, statement):
        return self.sync_session.execute(statement)

    async def flush(self) -> None:
        self.sync_session.flush()

    async def commit(self) -> None:
        self.sync_session.commit()

    async def rollback(self) -> None:
        self.sync_session.rollback()

    async def get(self, model, ident):
        return self.sync_session.get(model, ident)

    async def refresh(self, instance) -> None:
        self.sync_session.refresh(instance)


class AsyncSessionContext:
    def __init__(self, sync_session_factory) -> None:
        self.sync_session_factory = sync_session_factory
        self.sync_session = None

    async def __aenter__(self):
        self.sync_session = self.sync_session_factory()
        return AsyncSessionAdapter(self.sync_session)

    async def __aexit__(self, exc_type, exc, tb) -> None:
        self.sync_session.close()


class FakeVpnAccessService:
    instances: list["FakeVpnAccessService"] = []
    create_calls: list[dict] = []
    extend_calls: list[dict] = []
    get_config_calls: list[dict] = []
    uuid_counter = 0

    def __init__(self) -> None:
        self.__class__.instances.append(self)

    async def create_access(self, *, user_id: int, device_limit: int):
        self.__class__.uuid_counter += 1
        uuid = f"fake-uuid-{self.__class__.uuid_counter}"
        self.__class__.create_calls.append(
            {"user_id": user_id, "device_limit": device_limit, "uuid": uuid}
        )
        return SimpleNamespace(
            uuid=uuid,
            vpn_server_id=None,
            config_uri=f"https://connect.test/{uuid}?device=android",
        )

    async def extend_access(self, *, uuid: str, device_limit: int):
        self.__class__.extend_calls.append(
            {"uuid": uuid, "device_limit": device_limit}
        )
        return SimpleNamespace(
            uuid=uuid,
            vpn_server_id=None,
            config_uri=f"https://connect.test/{uuid}?device=android",
        )

    async def get_config(self, *, uuid: str, device_limit: int):
        self.__class__.get_config_calls.append(
            {"uuid": uuid, "device_limit": device_limit}
        )
        return f"https://connect.test/{uuid}?device=android"


class FakeSubscriptionMetaSyncService:
    calls: list[dict] = []

    def __init__(self, session) -> None:
        self.session = session

    async def sync_safely(self, **kwargs):
        self.__class__.calls.append(kwargs)
        return SimpleNamespace(status="skipped")


@pytest.fixture(autouse=True)
def patch_external_vpn_and_meta_sync(monkeypatch):
    FakeVpnAccessService.instances = []
    FakeVpnAccessService.create_calls = []
    FakeVpnAccessService.extend_calls = []
    FakeVpnAccessService.get_config_calls = []
    FakeVpnAccessService.uuid_counter = 0
    FakeSubscriptionMetaSyncService.calls = []

    monkeypatch.setattr(
        subscription_service_module,
        "VpnAccessService",
        FakeVpnAccessService,
    )
    monkeypatch.setattr(
        subscription_service_module,
        "SubscriptionMetaSyncService",
        FakeSubscriptionMetaSyncService,
    )
    monkeypatch.setattr(subscription_service_module, "datetime", NaiveDateTime)
    monkeypatch.setattr(polling_processor_module, "datetime", NaiveDateTime)


@pytest.fixture
def session_factory(tmp_path):
    db_path = tmp_path / "integration.sqlite3"
    engine = create_engine(f"sqlite:///{db_path}", future=True)
    Base.metadata.create_all(engine)
    sync_session_factory = sessionmaker(
        bind=engine,
        expire_on_commit=False,
        autoflush=False,
        autocommit=False,
        future=True,
    )

    def factory():
        return AsyncSessionContext(sync_session_factory)

    yield factory

    engine.dispose()


async def count_rows(session, model) -> int:
    result = await session.execute(select(func.count(model.id)))
    return result.scalar_one()


async def create_user_option_and_order(
    session,
    *,
    telegram_id: int = 777000,
    amount: Decimal = Decimal("4.00"),
    currency=CurrencyCode.USDT,
    network=NetworkCode.TRC20,
    address: str = "receiver-wallet",
    expires_delta: timedelta = timedelta(minutes=15),
    device_limit: int = 1,
    tariff_code=TariffCode.PERIOD_1_MONTH,
    price_usd: Decimal = Decimal("4.00"),
    duration_days: int = 33,
):
    user_repo = UserRepository(session)
    option_repo = PaymentOptionRepository(session)
    order_repo = OrderRepository(session)

    user = await user_repo.create(
        telegram_id=telegram_id,
        username="ivan",
        first_name="Ivan",
        last_name="Redeemer",
        language_code="ru",
        is_admin=False,
    )
    option = await option_repo.create(
        code=f"usdt_trc20_{telegram_id}_{len(str(NaiveDateTime.now().timestamp()))}",
        payment_method=PaymentMethod.CRYPTO,
        currency=currency,
        network=network,
        display_name="USDT TRC20",
        is_active=True,
        sort_order=10,
    )
    order = await order_repo.create(
        user_id=user.id,
        tariff_code=tariff_code,
        device_limit=device_limit,
        duration_days=duration_days,
        price_usd=price_usd,
        payment_method=PaymentMethod.CRYPTO,
        payment_option_id=option.id,
        expected_amount=amount,
        expected_currency=currency,
        expected_network=network,
        destination_address=address,
        destination_memo_tag=None,
        expires_at=NaiveDateTime.now() + expires_delta,
        source="bot",
        comment=None,
    )
    await session.commit()
    return user, option, order

async def create_user_stars_order(
        session,
        *,
        telegram_id: int = 777001,
        stars_amount: Decimal = Decimal("300"),
        duration_days: int = 33,
):
    user_repo = UserRepository(session)
    option_repo = PaymentOptionRepository(session)
    order_repo = OrderRepository(session)

    user = await user_repo.create(
        telegram_id=telegram_id,
        username="stars_user",
        first_name="Stars",
        last_name="User",
        language_code="en",
        is_admin=False,
    )

    option = await option_repo.create(
        code=f"telegram_stars_{telegram_id}",
        payment_method=PaymentMethod.TELEGRAM_STARS,
        currency=CurrencyCode.XTR,
        network=None,
        display_name="Telegram Stars",
        is_active=True,
        sort_order=200,
    )

    order = await order_repo.create(
        user_id=user.id,
        tariff_code=TariffCode.PERIOD_1_MONTH,
        device_limit=1,
        duration_days=duration_days,
        price_usd=Decimal("4.00"),
        payment_method=PaymentMethod.TELEGRAM_STARS,
        payment_option_id=option.id,
        expected_amount=stars_amount,
        expected_currency=CurrencyCode.XTR,
        expected_network=None,
        destination_address=None,
        destination_memo_tag=None,
        expires_at=NaiveDateTime.now() + timedelta(minutes=15),
        source="bot",
        comment=None,
    )

    await session.commit()

    return user, option, order


def make_tx(
    *,
    txid: str = "tx-1",
    amount: Decimal = Decimal("4.00"),
    currency=CurrencyCode.USDT,
    network=NetworkCode.TRC20,
    address_to: str = "receiver-wallet",
):
    return NormalizedTransaction(
        txid=txid,
        amount=amount,
        currency=currency,
        network=network,
        address_from="sender-wallet",
        address_to=address_to,
        confirmations=12,
        provider="integration-test",
        raw_payload={"txid": txid, "amount": str(amount)},
    )


@pytest.mark.asyncio
async def test_polling_confirmed_payment_activates_subscription_once(session_factory):
    async with session_factory() as session:
        user, option, order = await create_user_option_and_order(session)

        event, payment, subscription, config_uri = await PaymentPollingProcessor(
            session
        ).process_transaction(make_tx())

        assert event.order_id == order.id
        assert event.payment_id == payment.id
        assert event.processed is True
        assert event.processing_status == "confirmed"
        assert payment.order_id == order.id
        assert payment.user_id == user.id
        assert payment.status == PaymentStatus.CONFIRMED
        assert payment.txid == "tx-1"
        assert payment.provider_payment_id == "tx-1"
        assert payment.amount == Decimal("4.00000000")
        assert subscription.user_id == user.id
        assert subscription.order_id == order.id
        assert subscription.status == SubscriptionStatus.ACTIVE
        assert subscription.uuid == "fake-uuid-1"
        assert subscription.device_limit == 1
        assert config_uri == "https://connect.test/fake-uuid-1?device=android"

        refreshed_order = await session.get(Order, order.id)
        assert refreshed_order.status == OrderStatus.ACTIVATED
        assert refreshed_order.paid_at is not None
        assert refreshed_order.activated_at is not None

        assert await count_rows(session, PaymentEvent) == 1
        assert await count_rows(session, Payment) == 1
        assert await count_rows(session, Subscription) == 1
        assert FakeVpnAccessService.create_calls == [
            {"user_id": user.id, "device_limit": 1, "uuid": "fake-uuid-1"}
        ]
        assert FakeVpnAccessService.extend_calls == []
        assert FakeSubscriptionMetaSyncService.calls[0]["reason"] == (
            "post_payment_subscription_change"
        )


@pytest.mark.asyncio
async def test_repeating_same_confirmed_event_reuses_existing_payment_and_subscription(
    session_factory,
):
    async with session_factory() as session:
        _, _, order = await create_user_option_and_order(session)
        activation_service = PaymentActivationService(session)

        first_event, first_payment, first_subscription, first_config = (
            await activation_service.process_confirmed_payment_event_and_activate(
                order_id=order.id,
                amount=Decimal("4.00"),
                provider="integration-test",
                event_type="payment_confirmed",
                external_event_id="external-1",
                txid="tx-1",
                address_from="sender-wallet",
                address_to="receiver-wallet",
                confirmations=12,
                raw_payload='{"first": true}',
            )
        )
        second_event, second_payment, second_subscription, second_config = (
            await activation_service.process_confirmed_payment_event_and_activate(
                order_id=order.id,
                amount=Decimal("4.00"),
                provider="integration-test",
                event_type="payment_confirmed",
                external_event_id="external-1",
                txid="tx-1",
                address_from="sender-wallet",
                address_to="receiver-wallet",
                confirmations=12,
                raw_payload='{"duplicate": true}',
            )
        )

        assert second_event.id == first_event.id
        assert second_payment.id == first_payment.id
        assert second_subscription.id == first_subscription.id
        assert second_subscription.uuid == first_subscription.uuid
        assert second_config == first_config
        assert await count_rows(session, PaymentEvent) == 1
        assert await count_rows(session, Payment) == 1
        assert await count_rows(session, Subscription) == 1
        assert FakeVpnAccessService.create_calls == [
            {"user_id": order.user_id, "device_limit": 1, "uuid": "fake-uuid-1"}
        ]
        assert FakeVpnAccessService.extend_calls == []
        assert FakeVpnAccessService.get_config_calls == [
            {"uuid": "fake-uuid-1", "device_limit": 1}
        ]


@pytest.mark.asyncio
async def test_repeating_same_telegram_stars_payment_is_idempotent(
    session_factory,
):
    async with session_factory() as session:
        user, _, order = await create_user_stars_order(
            session
        )

        service = TelegramStarsPaymentService(
            session,
            settings=SimpleNamespace(
                telegram_stars_enabled=True,
                telegram_stars_invoice_secret=(
                    "integration-stars-secret"
                ),
            ),
        )

        invoice_payload = service.build_payload(
            order_id=order.id,
            telegram_id=user.telegram_id,
        )

        (
            first_event,
            first_payment,
            first_subscription,
            first_config,
        ) = await service.process_successful_payment(
            telegram_id=user.telegram_id,
            invoice_payload=invoice_payload,
            currency="XTR",
            total_amount=300,
            telegram_payment_charge_id="stars-charge-1",
            raw_payload='{"delivery": "first"}',
        )

        first_expires_at = first_subscription.expires_at
        assert first_payment.currency == CurrencyCode.XTR
        assert first_payment.amount == Decimal("300.00000000")
        (
            second_event,
            second_payment,
            second_subscription,
            second_config,
        ) = await service.process_successful_payment(
            telegram_id=user.telegram_id,
            invoice_payload=invoice_payload,
            currency="XTR",
            total_amount=300,
            telegram_payment_charge_id="stars-charge-1",
            raw_payload='{"delivery": "duplicate"}',
        )

        assert second_event.id == first_event.id
        assert second_payment.id == first_payment.id
        assert second_payment.currency == CurrencyCode.XTR
        assert second_subscription.id == first_subscription.id
        assert second_subscription.uuid == first_subscription.uuid
        assert second_subscription.expires_at == first_expires_at
        assert second_config == first_config

        refreshed_order = await session.get(
            Order,
            order.id,
        )
        assert refreshed_order.expected_currency == CurrencyCode.XTR
        assert refreshed_order.expected_amount == Decimal("300.00000000")
        assert refreshed_order.status == OrderStatus.ACTIVATED
        assert (
            refreshed_order.activated_subscription_id
            == first_subscription.id
        )

        assert await count_rows(session, PaymentEvent) == 1
        assert await count_rows(session, Payment) == 1
        assert await count_rows(session, Subscription) == 1

        assert FakeVpnAccessService.create_calls == [
            {
                "user_id": user.id,
                "device_limit": 1,
                "uuid": "fake-uuid-1",
            }
        ]
        assert FakeVpnAccessService.extend_calls == []
        assert FakeVpnAccessService.get_config_calls == [
            {
                "uuid": "fake-uuid-1",
                "device_limit": 1,
            }
        ]


@pytest.mark.asyncio
async def test_repeating_same_polled_transaction_after_activation_is_harmless(
    session_factory,
):
    async with session_factory() as session:
        await create_user_option_and_order(session)
        processor = PaymentPollingProcessor(session)

        first_result = await processor.process_transaction(make_tx(txid="tx-1"))
        second_result = await processor.process_transaction(make_tx(txid="tx-1"))

        assert first_result is not None
        assert second_result is None
        assert await count_rows(session, PaymentEvent) == 1
        assert await count_rows(session, Payment) == 1
        assert await count_rows(session, Subscription) == 1
        assert len(FakeVpnAccessService.create_calls) == 1
        assert FakeVpnAccessService.extend_calls == []


@pytest.mark.asyncio
async def test_wrong_amount_creates_invalid_payment_event_without_activation(
    session_factory,
):
    async with session_factory() as session:
        _, _, order = await create_user_option_and_order(session)

        event, payment, subscription, config_uri = await PaymentPollingProcessor(
            session
        ).process_transaction(make_tx(txid="tx-wrong", amount=Decimal("3.99")))

        assert subscription is None
        assert config_uri is None
        assert event.order_id == order.id
        assert event.payment_id == payment.id
        assert event.processed is True
        assert event.processing_status == "invalid"
        assert event.error_message == "wrong_amount"
        assert payment.status == PaymentStatus.INVALID
        assert payment.amount == Decimal("3.99000000")
        refreshed_order = await session.get(Order, order.id)
        assert refreshed_order.status == OrderStatus.WAITING_PAYMENT
        assert await count_rows(session, Subscription) == 0
        assert FakeVpnAccessService.create_calls == []
        assert FakeVpnAccessService.extend_calls == []


@pytest.mark.asyncio
async def test_late_payment_is_persisted_as_expired_without_activation(session_factory):
    async with session_factory() as session:
        _, _, order = await create_user_option_and_order(
            session,
            expires_delta=timedelta(days=-1),
        )

        event, payment, subscription, config_uri = await PaymentPollingProcessor(
            session
        ).process_transaction(make_tx(txid="tx-late"))

        assert subscription is None
        assert config_uri is None
        assert event.order_id == order.id
        assert event.payment_id == payment.id
        assert event.processed is True
        assert event.processing_status == "expired"
        assert event.error_message == "Late payment for expired order"
        assert payment.status == PaymentStatus.EXPIRED
        refreshed_order = await session.get(Order, order.id)
        assert refreshed_order.status == OrderStatus.EXPIRED
        assert await count_rows(session, Subscription) == 0
        assert FakeVpnAccessService.create_calls == []
        assert FakeVpnAccessService.extend_calls == []


@pytest.mark.asyncio
async def test_second_paid_order_creates_independent_subscription_with_new_uuid(
    session_factory,
):
    async with session_factory() as session:
        user, _, first_order = await create_user_option_and_order(
            session,
            telegram_id=777000,
            amount=Decimal("4.00"),
            device_limit=1,
            tariff_code=TariffCode.PERIOD_1_MONTH,
            price_usd=Decimal("4.00"),
            duration_days=33,
        )
        processor = PaymentPollingProcessor(session)

        _, _, first_subscription, _ = await processor.process_transaction(
            make_tx(txid="tx-first", amount=Decimal("4.00"))
        )
        first_subscription_id = first_subscription.id
        first_uuid = first_subscription.uuid
        first_expires_at = first_subscription.expires_at

        order_repo = OrderRepository(session)
        second_order = await order_repo.create(
            user_id=user.id,
            tariff_code=TariffCode.PERIOD_3_MONTHS,
            device_limit=1,
            duration_days=99,
            price_usd=Decimal("11.00"),
            payment_method=PaymentMethod.CRYPTO,
            payment_option_id=first_order.payment_option_id,
            expected_amount=Decimal("11.00"),
            expected_currency=CurrencyCode.USDT,
            expected_network=NetworkCode.TRC20,
            destination_address="receiver-wallet-2",
            destination_memo_tag=None,
            expires_at=NaiveDateTime.now() + timedelta(minutes=15),
            source="bot",
            comment="second independent subscription",
        )
        await session.commit()

        event, payment, second_subscription, config_uri = (
            await processor.process_transaction(
                make_tx(
                    txid="tx-second",
                    amount=Decimal("11.00"),
                    address_to="receiver-wallet-2",
                )
            )
        )

        assert event.order_id == second_order.id
        assert payment.status == PaymentStatus.CONFIRMED
        assert second_subscription.id != first_subscription_id
        assert second_subscription.uuid != first_uuid
        assert second_subscription.uuid == "fake-uuid-2"
        assert second_subscription.order_id == second_order.id
        assert second_subscription.device_limit == 1
        assert second_subscription.expires_at > first_expires_at
        assert config_uri == (
            "https://connect.test/fake-uuid-2?device=android"
        )

        refreshed_second_order = await session.get(Order, second_order.id)
        assert refreshed_second_order.status == OrderStatus.ACTIVATED
        assert await count_rows(session, Subscription) == 2
        assert await count_rows(session, Payment) == 2
        assert await count_rows(session, PaymentEvent) == 2
        assert FakeVpnAccessService.create_calls == [
            {"user_id": user.id, "device_limit": 1, "uuid": "fake-uuid-1"},
            {"user_id": user.id, "device_limit": 1, "uuid": "fake-uuid-2"},
        ]
        assert FakeVpnAccessService.extend_calls == []


@pytest.mark.asyncio
async def test_order_service_does_not_reuse_expired_waiting_order(session_factory):
    async with session_factory() as session:
        user, payment_option, first_order = await create_user_option_and_order(
            session,
            expires_delta=timedelta(days=-1),
        )

        second_order = await OrderService(session).create_order(
            telegram_id=user.telegram_id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
            language_code=user.language_code,
            tariff_code=TariffCode.PERIOD_1_MONTH,
            payment_option_code=payment_option.code,
        )

        assert second_order.id != first_order.id
        assert second_order.status == OrderStatus.WAITING_PAYMENT
        assert second_order.expires_at > datetime.now(UTC)