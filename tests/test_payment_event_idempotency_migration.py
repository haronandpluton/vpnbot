from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError


MIGRATION_PATH = Path(
    "app/database/migrations/versions/"
    "9c1f4b8a2d7e_add_payment_event_provider_idempotency.py"
)

CONSTRAINT_NAME = "uq_payment_events_provider_external_event_id"


def load_migration():
    spec = spec_from_file_location(
        "payment_event_provider_idempotency_migration",
        MIGRATION_PATH,
    )
    module = module_from_spec(spec)

    assert spec.loader is not None
    spec.loader.exec_module(module)

    return module


def run_migration(connection, direction: str) -> None:
    migration = load_migration()
    context = MigrationContext.configure(connection)
    migration.op = Operations(context)

    getattr(migration, direction)()


def create_payment_events_table(connection) -> None:
    connection.exec_driver_sql(
        """
        CREATE TABLE payment_events (
            id INTEGER PRIMARY KEY,
            provider VARCHAR(50) NOT NULL,
            external_event_id VARCHAR(255),
            processing_status VARCHAR(50),
            error_message TEXT
        )
        """
    )


def test_provider_idempotency_migration_upgrade_on_sqlite() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)

    with engine.begin() as connection:
        create_payment_events_table(connection)

        connection.exec_driver_sql(
            """
            INSERT INTO payment_events (
                id,
                provider,
                external_event_id,
                processing_status,
                error_message
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                (1, "cryptobot", "event-42", None, None),
                (2, "cryptobot", "event-42", None, None),
                (3, "volet", "event-42", None, None),
            ],
        )

        run_migration(connection, "upgrade")

        rows = connection.exec_driver_sql(
            """
            SELECT
                id,
                provider,
                external_event_id,
                processing_status,
                error_message
            FROM payment_events
            ORDER BY id
            """
        ).fetchall()

        assert rows[0] == (
            1,
            "cryptobot",
            "event-42",
            None,
            None,
        )

        assert rows[1] == (
            2,
            "cryptobot",
            None,
            "duplicate_migration",
            "Duplicate external event normalized before unique constraint",
        )

        assert rows[2] == (
            3,
            "volet",
            "event-42",
            None,
            None,
        )

        indexes = {
            index["name"]: index
            for index in inspect(connection).get_indexes("payment_events")
        }

        assert CONSTRAINT_NAME in indexes
        assert indexes[CONSTRAINT_NAME]["unique"] == 1
        assert indexes[CONSTRAINT_NAME]["column_names"] == [
            "provider",
            "external_event_id",
        ]

        # The same external event ID from another provider is valid.
        connection.exec_driver_sql(
            """
            INSERT INTO payment_events (
                id,
                provider,
                external_event_id
            )
            VALUES (?, ?, ?)
            """,
            (4, "telegram_stars", "event-42"),
        )

        # The same provider + external event ID must remain idempotent.
        with pytest.raises(IntegrityError):
            with connection.begin_nested():
                connection.exec_driver_sql(
                    """
                    INSERT INTO payment_events (
                        id,
                        provider,
                        external_event_id
                    )
                    VALUES (?, ?, ?)
                    """,
                    (5, "cryptobot", "event-42"),
                )

    engine.dispose()


def test_provider_idempotency_migration_downgrade_on_sqlite() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)

    with engine.begin() as connection:
        create_payment_events_table(connection)

        run_migration(connection, "upgrade")

        indexes_before = {
            index["name"]
            for index in inspect(connection).get_indexes("payment_events")
        }

        assert CONSTRAINT_NAME in indexes_before

        run_migration(connection, "downgrade")

        indexes_after = {
            index["name"]
            for index in inspect(connection).get_indexes("payment_events")
        }

        assert CONSTRAINT_NAME not in indexes_after

        connection.exec_driver_sql(
            """
            INSERT INTO payment_events (
                id,
                provider,
                external_event_id
            )
            VALUES (?, ?, ?)
            """,
            [
                (1, "cryptobot", "event-42"),
                (2, "cryptobot", "event-42"),
            ],
        )

        count = connection.exec_driver_sql(
            """
            SELECT COUNT(*)
            FROM payment_events
            WHERE provider = 'cryptobot'
              AND external_event_id = 'event-42'
            """
        ).scalar_one()

        assert count == 2

    engine.dispose()
