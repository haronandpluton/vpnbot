from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.database.repositories.adsgram_conversions import (
    ClaimedAdsGramConversion,
)
from app.services.adsgram_client import (
    AdsGramAPIError,
    AdsGramDeliveryResponse,
)
from app.services.adsgram_outbox_service import (
    AdsGramOutboxService,
    calculate_adsgram_retry_delay_seconds,
)


FIXED_NOW = datetime(
    2026,
    8,
    6,
    10,
    0,
    tzinfo=UTC,
)


class FakeSession:
    def __init__(self) -> None:
        self.events: list[str] = []

    async def commit(self) -> None:
        self.events.append("commit")

    async def rollback(self) -> None:
        self.events.append("rollback")


class FakeConversionRepository:
    def __init__(
        self,
        *,
        claimed=None,
        stale_requeued: int = 0,
        update_result: bool = True,
    ) -> None:
        self.claimed = list(claimed or [])
        self.stale_requeued = stale_requeued
        self.update_result = update_result

        self.requeue_calls: list[dict] = []
        self.claim_calls: list[dict] = []
        self.mark_sent_calls: list[dict] = []
        self.mark_retry_calls: list[dict] = []
        self.mark_failed_calls: list[dict] = []

    async def requeue_stale_claims(self, **kwargs):
        self.requeue_calls.append(kwargs)
        return self.stale_requeued

    async def claim_due(self, **kwargs):
        self.claim_calls.append(kwargs)
        return self.claimed

    async def mark_sent(self, **kwargs):
        self.mark_sent_calls.append(kwargs)
        return self.update_result

    async def mark_retry(self, **kwargs):
        self.mark_retry_calls.append(kwargs)
        return self.update_result

    async def mark_failed(self, **kwargs):
        self.mark_failed_calls.append(kwargs)
        return self.update_result


class FakeSystemErrorRepository:
    def __init__(self, pending=None) -> None:
        self.pending = pending
        self.get_calls: list[dict] = []
        self.create_calls: list[dict] = []
        self.update_calls: list[dict] = []

    async def get_unresolved_by_entity_and_error_type(
        self,
        **kwargs,
    ):
        self.get_calls.append(kwargs)
        return self.pending

    async def create(self, **kwargs):
        self.create_calls.append(kwargs)
        return SimpleNamespace(id=1)

    async def update_pending_failure(
        self,
        pending,
        **kwargs,
    ):
        self.update_calls.append(
            {
                "pending": pending,
                **kwargs,
            }
        )
        return pending


class FakeClient:
    def __init__(
        self,
        session: FakeSession,
        *,
        outcome=None,
        api_token: str = "secret-token",
    ) -> None:
        self.session = session
        self.outcome = outcome
        self.api_token = api_token
        self.calls: list[dict] = []

    async def confirm_conversion(self, **kwargs):
        # Claim должен быть зафиксирован до сети.
        assert self.session.events
        assert self.session.events[-1] == "commit"

        self.calls.append(kwargs)

        if isinstance(self.outcome, Exception):
            raise self.outcome

        return self.outcome or AdsGramDeliveryResponse(
            status_code=200,
            response_body="OK",
        )


def make_claimed(
    *,
    attempt_count: int = 1,
) -> ClaimedAdsGramConversion:
    return ClaimedAdsGramConversion(
        id=50,
        user_id=7,
        telegram_id=123456789,
        order_id=23,
        campaign_id="campaign_42",
        goal_type=2,
        attempt_count=attempt_count,
        claim_token="claim-token",
    )


def make_service(
    *,
    claimed=None,
    outcome=None,
    stale_requeued: int = 0,
    update_result: bool = True,
    max_attempts: int = 8,
):
    session = FakeSession()
    conversions = FakeConversionRepository(
        claimed=claimed,
        stale_requeued=stale_requeued,
        update_result=update_result,
    )
    errors = FakeSystemErrorRepository()
    client = FakeClient(
        session,
        outcome=outcome,
    )

    service = AdsGramOutboxService(
        session,
        client,
        conversion_repository=conversions,
        system_error_repository=errors,
        batch_size=50,
        claim_ttl_seconds=300,
        max_attempts=max_attempts,
        now_factory=lambda: FIXED_NOW,
    )

    return service, session, conversions, errors, client


@pytest.mark.parametrize(
    ("attempt_count", "expected"),
    [
        (1, 30),
        (2, 60),
        (3, 120),
        (7, 1920),
        (8, 3600),
        (20, 3600),
    ],
)
def test_retry_delay_uses_exponential_backoff(
    attempt_count,
    expected,
):
    assert (
        calculate_adsgram_retry_delay_seconds(
            attempt_count
        )
        == expected
    )


@pytest.mark.asyncio
async def test_empty_queue_commits_claim_transaction_without_http():
    service, session, conversions, errors, client = (
        make_service(
            claimed=[],
            stale_requeued=2,
        )
    )

    result = await service.run_once()

    assert result.stale_requeued == 2
    assert result.claimed == 0
    assert result.sent == 0
    assert client.calls == []
    assert session.events == ["commit"]
    assert errors.create_calls == []


@pytest.mark.asyncio
async def test_success_is_sent_after_claim_commit():
    item = make_claimed()

    service, session, conversions, errors, client = (
        make_service(claimed=[item])
    )

    result = await service.run_once()

    assert result.claimed == 1
    assert result.sent == 1
    assert result.retried == 0
    assert result.failed == 0

    assert client.calls == [
        {
            "telegram_id": 123456789,
            "campaign_id": "campaign_42",
            "goal_type": 2,
        }
    ]

    assert conversions.mark_sent_calls == [
        {
            "conversion_id": 50,
            "claim_token": "claim-token",
            "sent_at": FIXED_NOW,
            "http_status": 200,
        }
    ]

    assert session.events == [
        "commit",
        "commit",
    ]
    assert errors.create_calls == []


@pytest.mark.asyncio
async def test_retryable_failure_is_returned_to_pending_queue():
    item = make_claimed(attempt_count=1)

    error = AdsGramAPIError(
        "temporary failure",
        retryable=True,
        status_code=503,
        response_body="unavailable",
    )

    service, session, conversions, errors, client = (
        make_service(
            claimed=[item],
            outcome=error,
        )
    )

    result = await service.run_once()

    assert result.retried == 1
    assert result.failed == 0

    assert conversions.mark_retry_calls == [
        {
            "conversion_id": 50,
            "claim_token": "claim-token",
            "next_attempt_at": (
                FIXED_NOW + timedelta(seconds=30)
            ),
            "http_status": 503,
            "error_message": (
                "AdsGramAPIError: temporary failure"
            ),
        }
    ]

    assert conversions.mark_failed_calls == []
    assert errors.create_calls == []


@pytest.mark.asyncio
async def test_permanent_failure_marks_failed_and_creates_system_error():
    item = make_claimed(attempt_count=1)

    error = AdsGramAPIError(
        "invalid secret-token",
        retryable=False,
        status_code=401,
        response_body="token secret-token rejected",
    )

    service, session, conversions, errors, client = (
        make_service(
            claimed=[item],
            outcome=error,
        )
    )

    result = await service.run_once()

    assert result.failed == 1
    assert result.retried == 0

    assert len(conversions.mark_failed_calls) == 1

    failure = conversions.mark_failed_calls[0]

    assert failure["conversion_id"] == 50
    assert failure["http_status"] == 401
    assert "secret-token" not in failure["error_message"]
    assert "[REDACTED]" in failure["error_message"]

    assert len(errors.create_calls) == 1

    system_error = errors.create_calls[0]

    assert system_error["entity_type"] == (
        "adsgram_conversion"
    )
    assert system_error["entity_id"] == 50
    assert system_error["error_type"] == (
        "adsgram_delivery_failed"
    )

    assert "secret-token" not in system_error["payload"]

    payload = json.loads(system_error["payload"])

    assert payload["conversion_id"] == 50
    assert payload["http_status"] == 401
    assert "[REDACTED]" in payload["response_body"]


@pytest.mark.asyncio
async def test_retryable_failure_at_max_attempts_becomes_terminal():
    item = make_claimed(attempt_count=8)

    error = AdsGramAPIError(
        "temporary failure",
        retryable=True,
        status_code=503,
    )

    service, session, conversions, errors, client = (
        make_service(
            claimed=[item],
            outcome=error,
            max_attempts=8,
        )
    )

    result = await service.run_once()

    assert result.failed == 1
    assert result.retried == 0
    assert len(conversions.mark_failed_calls) == 1
    assert len(errors.create_calls) == 1


@pytest.mark.asyncio
async def test_lost_claim_does_not_overwrite_new_owner():
    item = make_claimed()

    service, session, conversions, errors, client = (
        make_service(
            claimed=[item],
            update_result=False,
        )
    )

    result = await service.run_once()

    assert result.sent == 0
    assert result.lost_claim == 1
    assert errors.create_calls == []