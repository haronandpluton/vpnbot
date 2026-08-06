from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import (
    async_sessionmaker,
    create_async_engine,
)

import app.database.models  # noqa: F401
from app.database.base import Base
from app.database.models.adsgram_conversion import (
    AdsGramConversion,
)
from app.database.models.user import User
from app.database.repositories.adsgram_conversions import (
    AdsGramConversionRepository,
)


@pytest.mark.asyncio
async def test_concurrent_sqlite_workers_claim_conversion_once(
    tmp_path,
):
    database_path = (
        tmp_path
        / "adsgram-outbox-concurrency.sqlite3"
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
            user = User(
                telegram_id=123456789,
                username="adsgram_test",
                first_name="AdsGram",
                last_name="Concurrency",
                language_code="en",
                is_admin=False,
            )
            session.add(user)
            await session.flush()

            conversion = AdsGramConversion(
                user_id=user.id,
                order_id=None,
                campaign_id="campaign_42",
                goal_type=1,
                idempotency_key=(
                    "registration:user:123456789"
                ),
                status="pending",
                attempt_count=0,
                next_attempt_at=None,
            )
            session.add(conversion)
            await session.commit()

            conversion_id = conversion.id

        start_event = asyncio.Event()
        claim_time = datetime.now(UTC)

        async def claim(
            claim_token: str,
        ):
            async with session_factory() as session:
                repository = (
                    AdsGramConversionRepository(
                        session
                    )
                )

                await start_event.wait()

                claimed = await repository.claim_due(
                    now=claim_time,
                    limit=1,
                    claim_token=claim_token,
                )
                await session.commit()

                return claimed

        first_task = asyncio.create_task(
            claim("worker-one")
        )
        second_task = asyncio.create_task(
            claim("worker-two")
        )

        await asyncio.sleep(0)
        start_event.set()

        first_result, second_result = (
            await asyncio.wait_for(
                asyncio.gather(
                    first_task,
                    second_task,
                ),
                timeout=15,
            )
        )

        claimed = [
            *first_result,
            *second_result,
        ]

        assert len(claimed) == 1
        assert claimed[0].id == conversion_id
        assert claimed[0].attempt_count == 1
        assert claimed[0].claim_token in {
            "worker-one",
            "worker-two",
        }

        assert sorted(
            [
                len(first_result),
                len(second_result),
            ]
        ) == [0, 1]

        async with session_factory() as session:
            stored = await session.get(
                AdsGramConversion,
                conversion_id,
            )

            assert stored is not None
            assert stored.status == "processing"
            assert stored.attempt_count == 1
            assert stored.claim_token in {
                "worker-one",
                "worker-two",
            }
            assert stored.claim_token == (
                claimed[0].claim_token
            )
            assert stored.claimed_at is not None
            assert stored.last_attempt_at is not None

    finally:
        await engine.dispose()