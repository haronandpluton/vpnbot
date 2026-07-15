from __future__ import annotations

import importlib
import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, func, inspect, select
from sqlalchemy.orm import sessionmaker

from app.config.payment_options import PAYMENT_OPTIONS
from app.database.base import Base
from app.database.models import PaymentOption


MIGRATION_PATH = Path("app/database/migrations/versions/120a64c0ed0a_initial_schema.py")

EXPECTED_TABLES = {
    "users",
    "payment_options",
    "orders",
    "payments",
    "payment_events",
    "subscriptions",
    "vpn_servers",
    "admin_actions",
    "system_errors",
}


class AsyncSessionAdapter:
    def __init__(self, sync_session) -> None:
        self.sync_session = sync_session
        self.commits = 0
        self.rollbacks = 0

    def add(self, instance) -> None:
        self.sync_session.add(instance)

    async def execute(self, statement):
        return self.sync_session.execute(statement)

    async def flush(self) -> None:
        self.sync_session.flush()

    async def commit(self) -> None:
        self.commits += 1
        self.sync_session.commit()

    async def rollback(self) -> None:
        self.rollbacks += 1
        self.sync_session.rollback()


class AsyncSessionContext:
    def __init__(self, sync_session_factory, registry: list[AsyncSessionAdapter]) -> None:
        self.sync_session_factory = sync_session_factory
        self.registry = registry
        self.sync_session = None
        self.adapter = None

    async def __aenter__(self):
        self.sync_session = self.sync_session_factory()
        self.adapter = AsyncSessionAdapter(self.sync_session)
        self.registry.append(self.adapter)
        return self.adapter

    async def __aexit__(self, exc_type, exc, tb) -> None:
        self.sync_session.close()


def load_initial_migration():
    spec = spec_from_file_location("initial_schema_migration", MIGRATION_PATH)
    module = module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def run_migration(connection, direction: str = "upgrade"):
    migration = load_initial_migration()
    context = MigrationContext.configure(connection)
    migration.op = Operations(context)
    getattr(migration, direction)()


def index_by_name(inspector, table: str) -> dict[str, dict]:
    return {index["name"]: index for index in inspector.get_indexes(table)}


def columns_by_name(inspector, table: str) -> dict[str, dict]:
    return {column["name"]: column for column in inspector.get_columns(table)}


def fk_targets(inspector, table: str, constrained_column: str) -> set[str]:
    targets = set()

    for fk in inspector.get_foreign_keys(table):
        if constrained_column not in fk["constrained_columns"]:
            continue

        for referred_table, referred_column in zip(
            [fk["referred_table"]] * len(fk["referred_columns"]),
            fk["referred_columns"],
            strict=True,
        ):
            targets.add(f"{referred_table}.{referred_column}")

    return targets


def test_initial_alembic_migration_upgrade_creates_core_tables_indexes_and_relations():
    engine = create_engine("sqlite:///:memory:", future=True)

    with engine.begin() as connection:
        run_migration(connection, "upgrade")
        inspector = inspect(connection)

        assert set(inspector.get_table_names()) == EXPECTED_TABLES

        assert columns_by_name(inspector, "orders")["status"]["default"] == "'created'"
        assert columns_by_name(inspector, "payments")["status"]["default"] == "'new'"
        assert (
            columns_by_name(inspector, "subscriptions")["status"]["default"]
            == "'inactive'"
        )
        assert columns_by_name(inspector, "system_errors")["retry_count"][
            "default"
        ] == "'0'"

        assert index_by_name(inspector, "users")["ix_users_telegram_id"]["unique"] == 1
        assert (
            index_by_name(inspector, "payment_options")["ix_payment_options_code"][
                "unique"
            ]
            == 1
        )
        assert index_by_name(inspector, "payments")["ix_payments_txid"]["unique"] == 1
        assert (
            index_by_name(inspector, "payments")["ix_payments_provider_payment_id"][
                "unique"
            ]
            == 1
        )
        assert (
            index_by_name(inspector, "subscriptions")["ix_subscriptions_uuid"]["unique"]
            == 1
        )
        assert (
            index_by_name(inspector, "vpn_servers")["ix_vpn_servers_name"]["unique"]
            == 1
        )

        assert fk_targets(inspector, "orders", "user_id") == {"users.id"}
        assert fk_targets(inspector, "orders", "payment_option_id") == {
            "payment_options.id"
        }
        assert fk_targets(inspector, "payments", "order_id") == {"orders.id"}
        assert fk_targets(inspector, "payments", "user_id") == {"users.id"}
        assert fk_targets(inspector, "payment_events", "payment_id") == {"payments.id"}
        assert fk_targets(inspector, "payment_events", "order_id") == {"orders.id"}
        assert fk_targets(inspector, "subscriptions", "vpn_server_id") == {
            "vpn_servers.id"
        }
        assert fk_targets(inspector, "admin_actions", "subscription_id") == {
            "subscriptions.id"
        }

    engine.dispose()


def test_initial_alembic_migration_downgrade_drops_created_domain_tables():
    engine = create_engine("sqlite:///:memory:", future=True)

    with engine.begin() as connection:
        run_migration(connection, "upgrade")
        assert set(inspect(connection).get_table_names()) == EXPECTED_TABLES

        run_migration(connection, "downgrade")
        assert set(inspect(connection).get_table_names()) == set()

    engine.dispose()


@pytest.mark.asyncio
async def test_seed_payment_options_creates_all_options_and_is_idempotent(
    monkeypatch,
    tmp_path,
):
    engine = create_engine(f"sqlite:///{tmp_path / 'seed.sqlite3'}", future=True)
    Base.metadata.create_all(engine)

    sync_session_factory = sessionmaker(
        bind=engine,
        expire_on_commit=False,
        autoflush=False,
        autocommit=False,
        future=True,
    )
    adapters: list[AsyncSessionAdapter] = []

    fake_session_module = SimpleNamespace(
        SessionLocal=lambda: AsyncSessionContext(sync_session_factory, adapters),
    )
    monkeypatch.setitem(sys.modules, "app.database.session", fake_session_module)
    sys.modules.pop("scripts.seed_payment_options", None)
    seed_module = importlib.import_module("scripts.seed_payment_options")

    await seed_module.seed_payment_options()
    await seed_module.seed_payment_options()

    with sync_session_factory() as session:
        rows = session.execute(
            select(PaymentOption).order_by(PaymentOption.sort_order.asc())
        ).scalars().all()

        assert len(rows) == len(PAYMENT_OPTIONS)
        assert {row.code for row in rows} == set(PAYMENT_OPTIONS)
        assert len({row.code for row in rows}) == len(PAYMENT_OPTIONS)
        assert session.execute(select(func.count(PaymentOption.id))).scalar_one() == len(
            PAYMENT_OPTIONS
        )
        assert (
            session.execute(
                select(PaymentOption).where(PaymentOption.code == "telegram_stars")
            )
            .scalar_one()
            .is_active
            is True
        )
        assert (
            session.execute(
                select(PaymentOption).where(PaymentOption.code == "usdt_trc20")
            )
            .scalar_one()
            .network.value
            == "TRC20"
        )

    assert len(adapters) == 2
    assert [adapter.commits for adapter in adapters] == [1, 1]
    assert [adapter.rollbacks for adapter in adapters] == [0, 0]

    with sync_session_factory() as session:
        option = session.execute(
            select(PaymentOption).where(PaymentOption.code == "usdt_trc20")
        ).scalar_one()
        option.display_name = "BROKEN"
        option.is_active = False
        session.commit()

    await seed_module.seed_payment_options()

    with sync_session_factory() as session:
        option = session.execute(
            select(PaymentOption).where(PaymentOption.code == "usdt_trc20")
        ).scalar_one()

        assert option.display_name == PAYMENT_OPTIONS["usdt_trc20"].display_name
        assert option.is_active == PAYMENT_OPTIONS["usdt_trc20"].is_active
        assert session.execute(select(func.count(PaymentOption.id))).scalar_one() == len(
            PAYMENT_OPTIONS
        )

    engine.dispose()