from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql, sqlite

from app.database.repositories.adsgram_conversions import (
    AdsGramConversionRepository,
    ClaimedAdsGramConversion,
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
async def test_claim_due_uses_atomic_update_returning_for_sqlite():
    now = datetime(
        2026,
        8,
        6,
        10,
        0,
        tzinfo=UTC,
    )

    claimed_row = SimpleNamespace(
        id=50,
        user_id=7,
        order_id=23,
        campaign_id="campaign_42",
        goal_type=2,
        attempt_count=1,
    )

    session = FakeSession(
        [
            FakeResult(
                rows=[claimed_row]
            ),
            FakeResult(
                rows=[
                    (
                        7,
                        123456789,
                    )
                ]
            ),
        ]
    )
    repository = AdsGramConversionRepository(
        session
    )

    claimed = await repository.claim_due(
        now=now,
        limit=10,
        claim_token="claim-token",
    )

    assert claimed == [
        ClaimedAdsGramConversion(
            id=50,
            user_id=7,
            telegram_id=123456789,
            order_id=23,
            campaign_id="campaign_42",
            goal_type=2,
            attempt_count=1,
            claim_token="claim-token",
        )
    ]

    assert session.flush_count == 0
    assert len(session.execute_calls) == 2

    compiled_claim = (
        session.execute_calls[0].compile(
            dialect=sqlite.dialect(),
        )
    )
    claim_sql = " ".join(
        str(compiled_claim).split()
    )

    assert (
        "UPDATE adsgram_conversions SET"
        in claim_sql
    )
    assert (
        "adsgram_conversions.status = ?"
        in claim_sql
    )
    assert (
        "adsgram_conversions.id IN "
        "(SELECT adsgram_conversions.id"
        in claim_sql
    )
    assert (
        "RETURNING id, user_id, order_id, "
        "campaign_id, goal_type, attempt_count"
        in claim_sql
    )
    assert "FOR UPDATE" not in claim_sql

    compiled_users = (
        session.execute_calls[1].compile(
            dialect=sqlite.dialect(),
        )
    )
    users_sql = " ".join(
        str(compiled_users).split()
    )

    assert (
        "SELECT users.id, users.telegram_id"
        in users_sql
    )

@pytest.mark.asyncio
async def test_claim_due_does_not_query_users_when_nothing_was_claimed():
    session = FakeSession(
        [
            FakeResult(rows=[]),
        ]
    )
    repository = AdsGramConversionRepository(
        session
    )

    claimed = await repository.claim_due(
        now=datetime.now(UTC),
        limit=10,
        claim_token="claim-token",
    )

    assert claimed == []
    assert len(session.execute_calls) == 1
    assert session.flush_count == 0


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