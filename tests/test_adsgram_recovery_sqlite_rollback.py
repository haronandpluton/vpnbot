from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import (
    async_sessionmaker,
    create_async_engine,
)

import app.database.models  # noqa: F401
from app.database.base import Base
from app.database.models.system_error_record import (
    SystemErrorRecord,
)
from app.services.adsgram_recovery_service import (
    ADSGRAM_PURCHASE_ENQUEUE_ERROR_TYPE,
    AdsGramRecoveryService,
)


class FakeTrackingService:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def enqueue_purchase_conversion(
        self,
        **kwargs,
    ):
        self.calls.append(kwargs)

        if kwargs["order_id"] == 23:
            return SimpleNamespace(
                status="confirmed_payment_not_found",
                conversion_id=None,
            )

        if kwargs["order_id"] == 24:
            return SimpleNamespace(
                status="queued",
                conversion_id=200,
            )

        raise AssertionError(
            f"Unexpected order_id={kwargs['order_id']}"
        )


@pytest.mark.asyncio
async def test_sqlite_recovery_continues_after_first_item_rollback(
    tmp_path,
):
    database_path = (
        tmp_path
        / "adsgram-recovery-rollback.sqlite3"
    )

    engine = create_async_engine(
        f"sqlite+aiosqlite:///{database_path}",
        connect_args={
            "timeout": 10,
        },
    )

    session_factory = async_sessionmaker(
        bind=engine,
        expire_on_commit=False,
        autoflush=False,
    )

    try:
        async with engine.begin() as connection:
            await connection.run_sync(
                Base.metadata.create_all
            )

        async with session_factory() as session:
            first_error = SystemErrorRecord(
                entity_type="order",
                entity_id=23,
                error_type=(
                    ADSGRAM_PURCHASE_ENQUEUE_ERROR_TYPE
                ),
                error_message="first failure",
                payload=json.dumps(
                    {
                        "user_id": 7,
                        "order_id": 23,
                        "payment_id": 55,
                    }
                ),
            )

            second_error = SystemErrorRecord(
                entity_type="order",
                entity_id=24,
                error_type=(
                    ADSGRAM_PURCHASE_ENQUEUE_ERROR_TYPE
                ),
                error_message="second failure",
                payload=json.dumps(
                    {
                        "user_id": 7,
                        "order_id": 24,
                        "payment_id": 56,
                    }
                ),
            )

            session.add_all(
                [
                    first_error,
                    second_error,
                ]
            )
            await session.commit()

            first_error_id = first_error.id
            second_error_id = second_error.id

        tracking = FakeTrackingService()

        async with session_factory() as session:
            service = AdsGramRecoveryService(
                session,
                tracking_service_factory=(
                    lambda session_arg: tracking
                ),
            )

            result = await service.run_once()

            assert result.purchase_checked == 2
            assert result.failed == 1
            assert result.resolved == 1

        async with session_factory() as session:
            stored_first = await session.get(
                SystemErrorRecord,
                first_error_id,
            )
            stored_second = await session.get(
                SystemErrorRecord,
                second_error_id,
            )

            assert stored_first is not None
            assert stored_second is not None

            assert stored_first.is_resolved is False
            assert stored_first.retry_count == 1

            assert stored_second.is_resolved is True

        assert tracking.calls == [
            {
                "user_id": 7,
                "order_id": 23,
                "payment_id": 55,
            },
            {
                "user_id": 7,
                "order_id": 24,
                "payment_id": 56,
            },
        ]

    finally:
        await engine.dispose()