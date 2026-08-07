from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    async_sessionmaker,
    create_async_engine,
)

import app.database.models  # noqa: F401
from app.database.base import Base
from app.database.models import (
    AdsGramConversion,
    User,
)
from app.database.repositories.users import (
    UserRepository,
)
from app.services.adsgram_tracking_service import (
    ADSGRAM_GOAL_REGISTRATION,
    AdsGramTrackingService,
)


class ReadBarrier:
    def __init__(self, parties: int = 2) -> None:
        self.parties = parties
        self.count = 0
        self.lock = asyncio.Lock()
        self.ready = asyncio.Event()

    async def wait(self) -> None:
        async with self.lock:
            self.count += 1

            if self.count >= self.parties:
                self.ready.set()

        await asyncio.wait_for(
            self.ready.wait(),
            timeout=5,
        )


class BarrierUserRepository(UserRepository):
    def __init__(
        self,
        session,
        barrier: ReadBarrier,
    ) -> None:
        super().__init__(session)
        self.barrier = barrier

    async def set_adsgram_attribution_if_empty(
            self,
            *,
            telegram_id: int,
            campaign_id: str,
            attributed_at,
    ) -> bool:
        # Оба worker уже прочитали NULL и только
        # после этого одновременно идут в atomic UPDATE.
        await self.barrier.wait()

        return await super().set_adsgram_attribution_if_empty(
            telegram_id=telegram_id,
            campaign_id=campaign_id,
            attributed_at=attributed_at,
        )


@pytest.mark.asyncio
async def test_sqlite_concurrent_first_touch_keeps_single_consistent_attribution(
    tmp_path,
):
    database_path = (
        tmp_path
        / "adsgram-first-touch.sqlite3"
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

    telegram_id = 987654321

    try:
        async with engine.begin() as connection:
            await connection.run_sync(
                Base.metadata.create_all
            )

        # Пользователь уже существует, но ещё
        # не имеет AdsGram attribution.
        async with session_factory() as session:
            user = await UserRepository(
                session
            ).create(
                telegram_id=telegram_id,
                username="race-user",
                first_name="Race",
                last_name="User",
                language_code="en",
                is_admin=False,
            )

            await session.commit()

            user_id = user.id

        barrier = ReadBarrier()

        async def run_attribution(
            campaign_id: str,
        ):
            async with session_factory() as session:
                service = AdsGramTrackingService(
                    session,
                    user_repository=(
                        BarrierUserRepository(
                            session,
                            barrier,
                        )
                    ),
                )

                return await (
                    service.capture_start_attribution(
                        telegram_id=telegram_id,
                        campaign_id=campaign_id,
                        enqueue_registration=True,
                    )
                )

        results = await asyncio.gather(
            run_attribution("campaign_a"),
            run_attribution("campaign_b"),
            return_exceptions=True,
        )

        successful_results = [
            result
            for result in results
            if not isinstance(
                result,
                BaseException,
            )
        ]

        # Хотя SQLite может отклонить один
        # конкурирующий writer, хотя бы одна
        # операция обязана успешно завершиться.
        assert successful_results

        async with session_factory() as session:
            user_result = await session.execute(
                select(User).where(
                    User.id == user_id
                )
            )
            stored_user = (
                user_result.scalar_one()
            )

            conversions_result = (
                await session.execute(
                    select(
                        AdsGramConversion
                    ).where(
                        AdsGramConversion.idempotency_key
                        == (
                            f"registration:user:"
                            f"{user_id}"
                        )
                    )
                )
            )

            conversions = list(
                conversions_result.scalars().all()
            )

        assert stored_user.adsgram_campaign_id in {
            "campaign_a",
            "campaign_b",
        }

        # Независимо от race registration
        # должна существовать ровно одна.
        assert len(conversions) == 1

        conversion = conversions[0]

        assert conversion.user_id == user_id
        assert (
            conversion.goal_type
            == ADSGRAM_GOAL_REGISTRATION
        )
        assert (
            conversion.idempotency_key
            == f"registration:user:{user_id}"
        )

        # Главный first-touch invariant:
        # нельзя получить user=campaign_B,
        # но registration conversion=campaign_A.
        assert (
            conversion.campaign_id
            == stored_user.adsgram_campaign_id
        )

    finally:
        await engine.dispose()