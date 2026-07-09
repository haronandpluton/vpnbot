from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    async_sessionmaker,
    create_async_engine,
)

import app.database.models  # noqa: F401
from app.common.enums import TariffCode
from app.database.base import Base
from app.database.models import Order, Subscription, User
from app.payment_core.enums.order_status import OrderStatus
from app.payment_core.enums.payment_method import PaymentMethod
from app.payment_core.enums.subscription_status import SubscriptionStatus
from app.services.subscription_service import SubscriptionService


TEST_DATABASE_ENV = "VPNBOT_TEST_POSTGRES_URL"


class BlockingVpnAccessService:
    def __init__(self) -> None:
        self.extend_entered = asyncio.Event()
        self.release_extend = asyncio.Event()
        self.extend_calls: list[dict] = []
        self.get_config_calls: list[dict] = []

    async def extend_access(
        self,
        *,
        uuid: str,
        device_limit: int,
    ):
        self.extend_calls.append(
            {
                "uuid": uuid,
                "device_limit": device_limit,
            }
        )

        if len(self.extend_calls) == 1:
            self.extend_entered.set()
            await asyncio.wait_for(
                self.release_extend.wait(),
                timeout=10,
            )

        return SimpleNamespace(
            uuid=uuid,
            vpn_server_id=None,
            config_uri=f"https://connect.test/{uuid}",
        )

    async def get_config(
        self,
        *,
        uuid: str,
        device_limit: int,
    ) -> str:
        self.get_config_calls.append(
            {
                "uuid": uuid,
                "device_limit": device_limit,
            }
        )
        return f"https://connect.test/{uuid}"


class SignallingSubscriptionService(SubscriptionService):
    def __init__(
        self,
        *args,
        lock_attempted: asyncio.Event | None = None,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.lock_attempted = lock_attempted

    async def _get_order_for_activation(
        self,
        order_id: int,
    ) -> Order | None:
        if self.lock_attempted is not None:
            self.lock_attempted.set()

        return await super()._get_order_for_activation(order_id)


def _get_test_database_url() -> str:
    database_url = os.getenv(TEST_DATABASE_ENV)

    if not database_url:
        pytest.skip(
            f"{TEST_DATABASE_ENV} is not configured; "
            "PostgreSQL concurrency test was not executed."
        )

    url = make_url(database_url)

    if url.get_backend_name() != "postgresql":
        pytest.fail(
            f"{TEST_DATABASE_ENV} must use PostgreSQL, "
            f"got backend={url.get_backend_name()!r}."
        )

    if "test" not in (url.database or "").lower():
        pytest.fail(
            f"{TEST_DATABASE_ENV} must point to a dedicated test "
            "database whose name contains 'test'."
        )

    return database_url


@pytest.mark.asyncio
async def test_same_renewal_order_is_applied_once_under_postgres_lock(
    monkeypatch,
):
    pytest.importorskip("asyncpg")
    database_url = _get_test_database_url()
    schema_name = f"vpn_concurrency_{uuid.uuid4().hex}"

    admin_engine = create_async_engine(
        database_url,
        pool_pre_ping=True,
    )
    test_engine = None

    try:
        async with admin_engine.begin() as connection:
            await connection.execute(
                text(f'CREATE SCHEMA "{schema_name}"')
            )

        test_engine = create_async_engine(
            database_url,
            pool_pre_ping=True,
            connect_args={
                "server_settings": {
                    "search_path": schema_name,
                }
            },
        )

        async with test_engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        session_factory = async_sessionmaker(
            bind=test_engine,
            expire_on_commit=False,
            autoflush=False,
        )

        now = datetime.now(timezone.utc)
        original_expires_at = now + timedelta(days=10)

        async with session_factory() as session:
            user = User(
                telegram_id=9_900_001,
                username="concurrency-test",
                first_name="Concurrency",
                last_name="Test",
                language_code="ru",
            )
            session.add(user)
            await session.flush()

            original_order = Order(
                user_id=user.id,
                status=OrderStatus.ACTIVATED,
                tariff_code=TariffCode.PERIOD_1_MONTH,
                device_limit=1,
                duration_days=33,
                target_subscription_id=None,
                activated_subscription_id=None,
                price_usd=Decimal("4.00"),
                payment_method=PaymentMethod.CRYPTO,
                payment_option_id=None,
                expected_amount=None,
                expected_currency=None,
                expected_network=None,
                destination_address=None,
                destination_memo_tag=None,
                expires_at=now + timedelta(minutes=15),
                paid_at=now,
                activated_at=now,
                source="test",
            )
            session.add(original_order)
            await session.flush()

            subscription = Subscription(
                user_id=user.id,
                order_id=original_order.id,
                vpn_server_id=None,
                status=SubscriptionStatus.ACTIVE,
                uuid=f"concurrency-{uuid.uuid4()}",
                device_limit=1,
                starts_at=now - timedelta(days=20),
                expires_at=original_expires_at,
            )
            session.add(subscription)
            await session.flush()

            original_order.activated_subscription_id = subscription.id

            renewal_order = Order(
                user_id=user.id,
                status=OrderStatus.PAID,
                tariff_code=TariffCode.PERIOD_1_MONTH,
                device_limit=1,
                duration_days=33,
                target_subscription_id=subscription.id,
                activated_subscription_id=None,
                price_usd=Decimal("4.00"),
                payment_method=PaymentMethod.CRYPTO,
                payment_option_id=None,
                expected_amount=None,
                expected_currency=None,
                expected_network=None,
                destination_address=None,
                destination_memo_tag=None,
                expires_at=now + timedelta(minutes=15),
                paid_at=now,
                activated_at=None,
                source="test",
            )
            session.add(renewal_order)
            await session.commit()

            renewal_order_id = renewal_order.id
            subscription_id = subscription.id
            original_order_id = original_order.id
            original_uuid = subscription.uuid

        async def no_meta_sync(self, **kwargs) -> None:
            return None

        monkeypatch.setattr(
            SubscriptionService,
            "_sync_order_activation",
            no_meta_sync,
        )

        vpn_access_service = BlockingVpnAccessService()
        second_lock_attempted = asyncio.Event()

        async def activate(
            *,
            lock_attempted: asyncio.Event | None = None,
        ):
            async with session_factory() as session:
                service = SignallingSubscriptionService(
                    session,
                    vpn_access_service=vpn_access_service,
                    lock_attempted=lock_attempted,
                )
                return await service.activate_or_extend_by_order(
                    renewal_order_id
                )

        first_task = asyncio.create_task(activate())

        await asyncio.wait_for(
            vpn_access_service.extend_entered.wait(),
            timeout=10,
        )

        second_task = asyncio.create_task(
            activate(lock_attempted=second_lock_attempted)
        )

        await asyncio.wait_for(
            second_lock_attempted.wait(),
            timeout=10,
        )
        await asyncio.sleep(0.1)

        assert second_task.done() is False

        vpn_access_service.release_extend.set()

        first_result, second_result = await asyncio.wait_for(
            asyncio.gather(first_task, second_task),
            timeout=15,
        )

        assert first_result[0].id == subscription_id
        assert second_result[0].id == subscription_id
        assert first_result[0].uuid == original_uuid
        assert second_result[0].uuid == original_uuid

        assert vpn_access_service.extend_calls == [
            {
                "uuid": original_uuid,
                "device_limit": 1,
            }
        ]
        assert vpn_access_service.get_config_calls == [
            {
                "uuid": original_uuid,
                "device_limit": 1,
            }
        ]

        async with session_factory() as session:
            final_order = await session.get(
                Order,
                renewal_order_id,
            )
            final_subscription = await session.get(
                Subscription,
                subscription_id,
            )
            subscription_count = await session.scalar(
                select(func.count(Subscription.id))
            )

        assert final_order is not None
        assert final_order.status == OrderStatus.ACTIVATED
        assert final_order.activated_subscription_id == subscription_id
        assert final_order.target_subscription_id == subscription_id
        assert final_order.activated_at is not None

        assert final_subscription is not None
        assert final_subscription.status == SubscriptionStatus.ACTIVE
        assert final_subscription.uuid == original_uuid
        assert final_subscription.order_id == original_order_id
        assert final_subscription.expires_at == (
            original_expires_at + timedelta(days=33)
        )
        assert subscription_count == 1

    finally:
        if test_engine is not None:
            await test_engine.dispose()

        async with admin_engine.begin() as connection:
            await connection.execute(
                text(
                    f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE'
                )
            )

        await admin_engine.dispose()
