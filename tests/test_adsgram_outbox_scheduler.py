from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace

import pytest

import app.services.adsgram_outbox_scheduler as scheduler_module
from app.services.adsgram_outbox_scheduler import (
    AdsGramOutboxScheduler,
)


class FakeSessionContext:
    def __init__(self, session) -> None:
        self.session = session
        self.enter_count = 0
        self.exit_count = 0
        self.exit_error_types: list[
            type[BaseException] | None
        ] = []

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


class FakeSessionFactory:
    def __init__(self) -> None:
        self.contexts: list[
            FakeSessionContext
        ] = []

    def __call__(self):
        context = FakeSessionContext(
            SimpleNamespace(name="adsgram-session")
        )
        self.contexts.append(context)
        return context


class FakeAdsGramClient:
    instances: list["FakeAdsGramClient"] = []

    def __init__(
        self,
        *,
        api_url: str,
        api_token: str,
        timeout_seconds: float,
    ) -> None:
        self.api_url = api_url
        self.api_token = api_token
        self.timeout_seconds = timeout_seconds
        self.__class__.instances.append(self)


class FakeAdsGramOutboxService:
    instances: list[
        "FakeAdsGramOutboxService"
    ] = []

    result = SimpleNamespace(
        stale_requeued=0,
        claimed=0,
        sent=0,
        retried=0,
        failed=0,
        lost_claim=0,
        processing_errors=0,
    )

    def __init__(
        self,
        session,
        client,
        *,
        batch_size: int,
        claim_ttl_seconds: int,
        max_attempts: int,
    ) -> None:
        self.session = session
        self.client = client
        self.batch_size = batch_size
        self.claim_ttl_seconds = claim_ttl_seconds
        self.max_attempts = max_attempts
        self.run_count = 0
        self.__class__.instances.append(self)

    async def run_once(self):
        self.run_count += 1
        return self.__class__.result


@pytest.fixture
def scheduler_settings(monkeypatch):
    settings = SimpleNamespace(
        adsgram_enabled=True,
        adsgram_api_url=(
            "https://api.adsgram.ai/"
            "confirm_conversion"
        ),
        adsgram_api_token="secret-token",
        adsgram_request_timeout_seconds=7.5,
        adsgram_scheduler_interval_seconds=30,
        adsgram_scheduler_initial_delay_seconds=10,
        adsgram_scheduler_batch_size=25,
        adsgram_claim_ttl_seconds=180,
        adsgram_max_attempts=6,
    )

    FakeAdsGramClient.instances = []
    FakeAdsGramOutboxService.instances = []
    FakeAdsGramOutboxService.result = (
        SimpleNamespace(
            stale_requeued=0,
            claimed=0,
            sent=0,
            retried=0,
            failed=0,
            lost_claim=0,
            processing_errors=0,
        )
    )

    monkeypatch.setattr(
        scheduler_module,
        "get_settings",
        lambda: settings,
    )
    monkeypatch.setattr(
        scheduler_module,
        "AdsGramClient",
        FakeAdsGramClient,
    )
    monkeypatch.setattr(
        scheduler_module,
        "AdsGramOutboxService",
        FakeAdsGramOutboxService,
    )

    return settings


@pytest.mark.asyncio
async def test_scheduler_returns_immediately_when_disabled(
    scheduler_settings,
):
    scheduler_settings.adsgram_enabled = False
    session_factory = FakeSessionFactory()

    scheduler = AdsGramOutboxScheduler(
        session_factory
    )

    await scheduler.run_forever()

    assert session_factory.contexts == []
    assert FakeAdsGramClient.instances == []
    assert FakeAdsGramOutboxService.instances == []


@pytest.mark.asyncio
async def test_run_once_uses_isolated_session_and_runtime_settings(
    scheduler_settings,
    caplog,
):
    FakeAdsGramOutboxService.result = (
        SimpleNamespace(
            stale_requeued=0,
            claimed=2,
            sent=2,
            retried=0,
            failed=0,
            lost_claim=0,
            processing_errors=0,
        )
    )

    session_factory = FakeSessionFactory()
    scheduler = AdsGramOutboxScheduler(
        session_factory
    )

    with caplog.at_level(logging.INFO):
        result = await scheduler.run_once()

    assert result.claimed == 2
    assert result.sent == 2

    assert len(session_factory.contexts) == 1

    context = session_factory.contexts[0]

    assert context.enter_count == 1
    assert context.exit_count == 1
    assert context.exit_error_types == [None]

    assert len(FakeAdsGramClient.instances) == 1

    client = FakeAdsGramClient.instances[0]

    assert client.api_url == (
        "https://api.adsgram.ai/"
        "confirm_conversion"
    )
    assert client.api_token == "secret-token"
    assert client.timeout_seconds == 7.5

    assert len(
        FakeAdsGramOutboxService.instances
    ) == 1

    service = FakeAdsGramOutboxService.instances[0]

    assert service.session.name == "adsgram-session"
    assert service.client is client
    assert service.batch_size == 25
    assert service.claim_ttl_seconds == 180
    assert service.max_attempts == 6
    assert service.run_count == 1

    assert any(
        (
            "AdsGram outbox iteration completed: "
            "stale_requeued=0 claimed=2 sent=2"
        )
        in record.getMessage()
        for record in caplog.records
    )


@pytest.mark.asyncio
async def test_run_once_logs_warning_for_retry_or_failure(
    scheduler_settings,
    caplog,
):
    FakeAdsGramOutboxService.result = (
        SimpleNamespace(
            stale_requeued=1,
            claimed=3,
            sent=1,
            retried=1,
            failed=1,
            lost_claim=0,
            processing_errors=0,
        )
    )

    scheduler = AdsGramOutboxScheduler(
        FakeSessionFactory()
    )

    with caplog.at_level(logging.WARNING):
        result = await scheduler.run_once()

    assert result.retried == 1
    assert result.failed == 1

    assert any(
        record.levelno == logging.WARNING
        and "retried=1 failed=1"
        in record.getMessage()
        for record in caplog.records
    )


@pytest.mark.asyncio
async def test_run_forever_survives_iteration_error_and_cancels_cleanly(
    scheduler_settings,
    monkeypatch,
    caplog,
):
    scheduler_settings.adsgram_scheduler_initial_delay_seconds = 0
    scheduler_settings.adsgram_scheduler_interval_seconds = 17

    scheduler = AdsGramOutboxScheduler(
        FakeSessionFactory()
    )

    run_count = 0
    sleep_calls: list[int] = []

    async def failing_run_once():
        nonlocal run_count
        run_count += 1
        raise RuntimeError("iteration failed")

    async def cancelling_sleep(delay: int):
        sleep_calls.append(delay)
        raise asyncio.CancelledError

    monkeypatch.setattr(
        scheduler,
        "run_once",
        failing_run_once,
    )
    monkeypatch.setattr(
        scheduler_module.asyncio,
        "sleep",
        cancelling_sleep,
    )

    with caplog.at_level(logging.INFO):
        with pytest.raises(asyncio.CancelledError):
            await scheduler.run_forever()

    assert run_count == 1
    assert sleep_calls == [17]

    messages = [
        record.getMessage()
        for record in caplog.records
    ]

    assert (
        "AdsGram outbox scheduler iteration failed."
        in messages
    )
    assert (
        "AdsGram outbox scheduler cancelled."
        in messages
    )