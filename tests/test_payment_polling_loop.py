from __future__ import annotations

import pytest

from app.payment_polling.loop import PaymentPollingLoop


class FakeAdapter:
    def __init__(
        self,
        *,
        name: str,
        transactions=None,
        error: Exception | None = None,
    ) -> None:
        self.name = name
        self.transactions = transactions or []
        self.error = error
        self.fetch_count = 0

    async def fetch_transactions(self):
        self.fetch_count += 1

        if self.error is not None:
            raise self.error

        return self.transactions


class FakeRegistry:
    def __init__(self, adapters) -> None:
        self.adapters = adapters
        self.get_active_adapters_count = 0

    def get_active_adapters(self):
        self.get_active_adapters_count += 1
        return self.adapters


class FakeProcessor:
    def __init__(self, *, results_by_call=None, error: Exception | None = None) -> None:
        self.results_by_call = list(results_by_call or [])
        self.error = error
        self.calls = []

    async def process_transactions(self, transactions):
        self.calls.append(transactions)

        if self.error is not None:
            raise self.error

        if self.results_by_call:
            return self.results_by_call.pop(0)

        return []


def make_loop(*, adapters, processor: FakeProcessor | None = None):
    loop = PaymentPollingLoop.__new__(PaymentPollingLoop)
    loop.session = object()
    loop.registry = FakeRegistry(adapters)
    loop.processor = processor or FakeProcessor()
    return loop


@pytest.mark.asyncio
async def test_run_once_returns_empty_list_when_no_active_adapters():
    processor = FakeProcessor()
    loop = make_loop(adapters=[], processor=processor)

    result = await loop.run_once()

    assert result == []
    assert loop.registry.get_active_adapters_count == 1
    assert processor.calls == []


@pytest.mark.asyncio
async def test_run_once_fetches_transactions_and_extends_processor_results(capsys):
    adapter = FakeAdapter(name="mock", transactions=["tx-1", "tx-2"])
    processor = FakeProcessor(results_by_call=[["result-1", "result-2"]])
    loop = make_loop(adapters=[adapter], processor=processor)

    result = await loop.run_once()

    assert result == ["result-1", "result-2"]
    assert adapter.fetch_count == 1
    assert processor.calls == [["tx-1", "tx-2"]]

    output = capsys.readouterr().out
    assert "ADAPTER FETCHED:" in output
    assert "adapter = mock" in output
    assert "transactions_count = 2" in output


@pytest.mark.asyncio
async def test_run_once_aggregates_results_from_multiple_adapters():
    first = FakeAdapter(name="first", transactions=["tx-1"])
    second = FakeAdapter(name="second", transactions=["tx-2", "tx-3"])
    processor = FakeProcessor(
        results_by_call=[
            ["first-result"],
            ["second-result-1", "second-result-2"],
        ]
    )
    loop = make_loop(adapters=[first, second], processor=processor)

    result = await loop.run_once()

    assert result == ["first-result", "second-result-1", "second-result-2"]
    assert first.fetch_count == 1
    assert second.fetch_count == 1
    assert processor.calls == [["tx-1"], ["tx-2", "tx-3"]]


@pytest.mark.asyncio
async def test_run_once_logs_fetch_error_and_continues_with_next_adapter(capsys):
    failing = FakeAdapter(name="failing", error=RuntimeError("fetch failed"))
    working = FakeAdapter(name="working", transactions=["tx-ok"])
    processor = FakeProcessor(results_by_call=[["ok-result"]])
    loop = make_loop(adapters=[failing, working], processor=processor)

    result = await loop.run_once()

    assert result == ["ok-result"]
    assert failing.fetch_count == 1
    assert working.fetch_count == 1
    assert processor.calls == [["tx-ok"]]

    output = capsys.readouterr().out
    assert "ADAPTER ERROR:" in output
    assert "adapter = failing" in output
    assert "RuntimeError('fetch failed')" in output
    assert "adapter = working" in output


@pytest.mark.asyncio
async def test_run_once_logs_processor_error_and_continues_with_next_adapter(capsys):
    first = FakeAdapter(name="first", transactions=["tx-bad"])
    second = FakeAdapter(name="second", transactions=["tx-ok"])

    class FailingOnceProcessor(FakeProcessor):
        async def process_transactions(self, transactions):
            self.calls.append(transactions)

            if len(self.calls) == 1:
                raise RuntimeError("processor failed")

            return ["ok-result"]

    processor = FailingOnceProcessor()
    loop = make_loop(adapters=[first, second], processor=processor)

    result = await loop.run_once()

    assert result == ["ok-result"]
    assert processor.calls == [["tx-bad"], ["tx-ok"]]

    output = capsys.readouterr().out
    assert "ADAPTER ERROR:" in output
    assert "adapter = first" in output
    assert "RuntimeError('processor failed')" in output
    assert "adapter = second" in output