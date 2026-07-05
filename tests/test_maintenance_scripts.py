from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

import scripts.expire_orders_once as expire_orders_script
import scripts.expire_subscriptions_once as expire_subscriptions_script
import scripts.export_subscriptions_meta as export_meta_script
import scripts.run_polling_once as run_polling_once_script


class FakeSessionContext:
    def __init__(self, session="session") -> None:
        self.session = session
        self.enter_count = 0
        self.exit_count = 0

    async def __aenter__(self):
        self.enter_count += 1
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        self.exit_count += 1
        return False


class FakeOrderExpirationService:
    instances: list["FakeOrderExpirationService"] = []

    def __init__(self, session) -> None:
        self.session = session
        self.__class__.instances.append(self)

    async def expire_due_orders(self):
        return SimpleNamespace(
            status="expired",
            checked_at=datetime(2026, 7, 5, 12, 0, tzinfo=timezone.utc),
            expired_count=1,
            expired_items=[
                SimpleNamespace(
                    order_id=23,
                    user_id=7,
                    old_status="waiting_payment",
                    new_status="expired",
                    expires_at=datetime(2026, 7, 5, 11, 59, tzinfo=timezone.utc),
                )
            ],
        )


class FakeSubscriptionExpirationService:
    instances: list["FakeSubscriptionExpirationService"] = []

    def __init__(self, session) -> None:
        self.session = session
        self.calls: list[dict] = []
        self.__class__.instances.append(self)

    async def expire_due_subscriptions(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            status="expired",
            checked_at=datetime(2026, 7, 5, 12, 0, tzinfo=timezone.utc),
            expired_count=1,
            sync_status="sync_failed",
            sync_error="scp failed",
            expired_items=[
                SimpleNamespace(
                    subscription_id=51,
                    user_id=7,
                    uuid="uuid-1",
                    expires_at=datetime(2026, 7, 5, 11, 59, tzinfo=timezone.utc),
                )
            ],
        )


class FakePaymentPollingLoop:
    instances: list["FakePaymentPollingLoop"] = []

    def __init__(self, session) -> None:
        self.session = session
        self.run_once_count = 0
        self.__class__.instances.append(self)

    async def run_once(self):
        self.run_once_count += 1
        return ["result-1", "result-2"]


class FakeScalars:
    def __init__(self, rows) -> None:
        self.rows = rows

    def all(self):
        return self.rows


class FakeExecuteResult:
    def __init__(self, rows) -> None:
        self.rows = rows

    def scalars(self):
        return FakeScalars(self.rows)


class FakeExportSession:
    def __init__(self, rows) -> None:
        self.rows = rows
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        return FakeExecuteResult(self.rows)


@pytest.mark.asyncio
async def test_run_polling_once_script_uses_session_and_prints_result_count(
    monkeypatch,
    capsys,
):
    FakePaymentPollingLoop.instances = []
    session_context = FakeSessionContext(session="polling-session")

    monkeypatch.setattr(run_polling_once_script, "SessionLocal", lambda: session_context)
    monkeypatch.setattr(
        run_polling_once_script,
        "PaymentPollingLoop",
        FakePaymentPollingLoop,
    )

    await run_polling_once_script.main()

    assert session_context.enter_count == 1
    assert session_context.exit_count == 1
    loop = FakePaymentPollingLoop.instances[0]
    assert loop.session == "polling-session"
    assert loop.run_once_count == 1

    output = capsys.readouterr().out
    assert "START POLLING (ONE-SHOT)" in output
    assert "POLLING FINISHED" in output
    assert "results_count = 2" in output


@pytest.mark.asyncio
async def test_expire_orders_once_script_calls_service_and_prints_expired_items(
    monkeypatch,
    capsys,
):
    FakeOrderExpirationService.instances = []
    session_context = FakeSessionContext(session="orders-session")

    monkeypatch.setattr(expire_orders_script, "session_factory", lambda: session_context)
    monkeypatch.setattr(
        expire_orders_script,
        "OrderExpirationService",
        FakeOrderExpirationService,
    )

    await expire_orders_script.main()

    assert session_context.enter_count == 1
    assert session_context.exit_count == 1
    service = FakeOrderExpirationService.instances[0]
    assert service.session == "orders-session"

    output = capsys.readouterr().out
    assert "status: expired" in output
    assert "expired_count: 1" in output
    assert "expired order_id=23 user_id=7 waiting_payment->expired" in output


@pytest.mark.asyncio
async def test_expire_subscriptions_once_script_enables_metadata_sync_and_prints_errors(
    monkeypatch,
    capsys,
):
    FakeSubscriptionExpirationService.instances = []
    session_context = FakeSessionContext(session="subscriptions-session")

    monkeypatch.setattr(
        expire_subscriptions_script,
        "session_factory",
        lambda: session_context,
    )
    monkeypatch.setattr(
        expire_subscriptions_script,
        "SubscriptionExpirationService",
        FakeSubscriptionExpirationService,
    )

    await expire_subscriptions_script.main()

    assert session_context.enter_count == 1
    assert session_context.exit_count == 1
    service = FakeSubscriptionExpirationService.instances[0]
    assert service.session == "subscriptions-session"
    assert service.calls == [{"sync_metadata": True}]

    output = capsys.readouterr().out
    assert "status: expired" in output
    assert "expired_count: 1" in output
    assert "sync_status: sync_failed" in output
    assert "sync_error: scp failed" in output
    assert "expired subscription_id=51 user_id=7 uuid=uuid-1" in output


def test_export_subscriptions_meta_timestamp_helper_treats_naive_datetime_as_utc():
    naive = datetime(2026, 8, 5, 12, 0)
    aware = datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc)

    assert export_meta_script.to_unix_timestamp(naive) == export_meta_script.to_unix_timestamp(
        aware
    )


@pytest.mark.asyncio
async def test_export_subscriptions_meta_script_writes_happ_metadata_json(
    monkeypatch,
    tmp_path,
    capsys,
):
    rows = [
        SimpleNamespace(
            uuid="uuid-active",
            expires_at=datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc),
        ),
        SimpleNamespace(
            uuid="uuid-expired",
            expires_at=datetime(2026, 7, 5, 12, 0),
        ),
    ]
    fake_session = FakeExportSession(rows)
    session_context = FakeSessionContext(session=fake_session)
    output_path = tmp_path / "subscriptions_meta.generated.json"

    monkeypatch.setattr(export_meta_script, "SessionLocal", lambda: session_context)
    monkeypatch.setattr(export_meta_script, "OUTPUT_PATH", output_path)

    await export_meta_script.main()

    assert session_context.enter_count == 1
    assert session_context.exit_count == 1
    assert len(fake_session.statements) == 1
    assert output_path.exists()

    data = json.loads(output_path.read_text(encoding="utf-8"))
    assert set(data) == {"uuid-active", "uuid-expired"}
    assert data["uuid-active"] == {
        "expire": export_meta_script.to_unix_timestamp(rows[0].expires_at),
        "upload": 0,
        "download": 0,
        "total": 0,
    }
    assert data["uuid-expired"] == {
        "expire": export_meta_script.to_unix_timestamp(rows[1].expires_at),
        "upload": 0,
        "download": 0,
        "total": 0,
    }

    output = capsys.readouterr().out
    assert "Exported 2 subscriptions" in output
    assert f"Saved to: {output_path}" in output