from __future__ import annotations

from importlib import import_module


migration = import_module(
    "app.database.migrations.versions."
    "f56eb2e7770c_add_cryptobot_payment_notification_state"
)


class FakeOp:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple, dict]] = []

    def add_column(self, *args, **kwargs) -> None:
        self.calls.append(("add_column", args, kwargs))

    def create_index(self, *args, **kwargs) -> None:
        self.calls.append(("create_index", args, kwargs))

    def execute(self, *args, **kwargs) -> None:
        self.calls.append(("execute", args, kwargs))

    def drop_index(self, *args, **kwargs) -> None:
        self.calls.append(("drop_index", args, kwargs))

    def drop_column(self, *args, **kwargs) -> None:
        self.calls.append(("drop_column", args, kwargs))


def normalize_sql(value: object) -> str:
    return " ".join(str(value).lower().split())


def test_upgrade_backfills_only_activated_cryptobot_orders(
    monkeypatch,
):
    fake_op = FakeOp()
    monkeypatch.setattr(migration, "op", fake_op)

    migration.upgrade()

    execute_calls = [
        call
        for call in fake_op.calls
        if call[0] == "execute"
    ]
    assert len(execute_calls) == 1

    sql = normalize_sql(execute_calls[0][1][0])

    assert "provider = 'cryptobot'" in sql
    assert "event_type = 'invoice_paid'" in sql
    assert "processed is true" in sql
    assert "processing_status = 'confirmed'" in sql
    assert "payment_id is not null" in sql
    assert "notification_sent_at is null" in sql
    assert "exists (" in sql
    assert "orders.id = payment_events.order_id" in sql
    assert "orders.status = 'activated'" in sql
    assert "orders.activated_subscription_id is not null" in sql


def test_downgrade_removes_indexes_before_columns(monkeypatch):
    fake_op = FakeOp()
    monkeypatch.setattr(migration, "op", fake_op)

    migration.downgrade()

    assert [call[0] for call in fake_op.calls] == [
        "drop_index",
        "drop_index",
        "drop_column",
        "drop_column",
        "drop_column",
    ]
