from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql

from app.database.repositories.adsgram_conversions import (
    AdsGramConversionRepository,
)


class FakeResult:
    def __init__(
        self,
        *,
        rows=None,
        rowcount: int = 0,
    ) -> None:
        self.rows = rows or []
        self.rowcount = rowcount

    def all(self):
        return self.rows


class FakeSession:
    def __init__(self, results) -> None:
        self.results = list(results)
        self.execute_calls = []
        self.flush_count = 0

    async def execute(self, stmt):
        self.execute_calls.append(stmt)
        return self.results.pop(0)

    async def flush(self):
        self.flush_count += 1


@pytest.mark.asyncio
async def test_claim_due_uses_skip_locked_and_marks_rows_processing():
    now = datetime(
        2026,
        8,
        6,
        10,
        0,
        tzinfo=UTC,
    )

    conversion = SimpleNamespace(
        id=50,
        user_id=7,
        order_id=23,
        campaign_id="campaign_42",
        goal_type=2,
        status="pending",
        attempt_count=0,
        claim_token=None,
        claimed_at=None,
        last_attempt_at=None,
    )

    session = FakeSession(
        [
            FakeResult(
                rows=[
                    (
                        conversion,
                        123456789,
                    )
                ]
            )
        ]
    )
    repository = AdsGramConversionRepository(session)

    claimed = await repository.claim_due(
        now=now,
        limit=10,
        claim_token="claim-token",
    )

    assert len(claimed) == 1
    assert claimed[0].id == 50
    assert claimed[0].telegram_id == 123456789
    assert claimed[0].attempt_count == 1
    assert claimed[0].claim_token == "claim-token"

    assert conversion.status == "processing"
    assert conversion.attempt_count == 1
    assert conversion.claim_token == "claim-token"
    assert conversion.claimed_at == now
    assert conversion.last_attempt_at == now

    assert session.flush_count == 1

    compiled = session.execute_calls[0].compile(
        dialect=postgresql.dialect(),
    )
    sql = " ".join(str(compiled).split())

    assert (
        "FOR UPDATE OF adsgram_conversions SKIP LOCKED"
        in sql
    )


@pytest.mark.asyncio
async def test_mark_sent_requires_matching_processing_claim():
    session = FakeSession(
        [
            FakeResult(rowcount=1),
        ]
    )
    repository = AdsGramConversionRepository(session)

    updated = await repository.mark_sent(
        conversion_id=50,
        claim_token="claim-token",
        sent_at=datetime.now(UTC),
        http_status=200,
    )

    assert updated is True

    compiled = session.execute_calls[0].compile(
        dialect=postgresql.dialect(),
    )
    sql = " ".join(str(compiled).split())

    assert "adsgram_conversions.id =" in sql
    assert "adsgram_conversions.status =" in sql
    assert "adsgram_conversions.claim_token =" in sql