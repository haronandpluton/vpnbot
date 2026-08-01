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
    "c4a7e2d9b531_add_subscription_node_access.py"
)


def load_migration():
    spec = spec_from_file_location(
        "subscription_node_access_migration",
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


def create_subscriptions_table(connection) -> None:
    connection.exec_driver_sql(
        """
        CREATE TABLE subscriptions (
            id INTEGER PRIMARY KEY
        )
        """
    )


def indexes_by_name(connection) -> dict[str, dict]:
    return {
        index["name"]: index
        for index in inspect(connection).get_indexes(
            "subscription_node_access"
        )
    }


def test_upgrade_creates_node_state_table_constraints_and_indexes():
    engine = create_engine("sqlite:///:memory:", future=True)

    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        create_subscriptions_table(connection)
        connection.exec_driver_sql(
            "INSERT INTO subscriptions (id) VALUES (50)"
        )

        run_migration(connection, "upgrade")

        inspector = inspect(connection)
        assert "subscription_node_access" in inspector.get_table_names()

        columns = {
            column["name"]: column
            for column in inspector.get_columns(
                "subscription_node_access"
            )
        }
        assert columns["desired_state"]["default"] == "'enabled'"
        assert columns["actual_state"]["default"] == "'pending'"
        assert columns["retry_count"]["default"] == "'0'"
        assert columns["last_error"]["nullable"] is True
        assert columns["provisioned_at"]["nullable"] is True
        assert columns["disabled_at"]["nullable"] is True

        foreign_keys = inspector.get_foreign_keys(
            "subscription_node_access"
        )
        assert len(foreign_keys) == 1
        assert foreign_keys[0]["constrained_columns"] == [
            "subscription_id"
        ]
        assert foreign_keys[0]["referred_table"] == "subscriptions"
        assert foreign_keys[0]["referred_columns"] == ["id"]
        assert foreign_keys[0]["options"]["ondelete"] == "CASCADE"

        unique_constraints = {
            constraint["name"]: constraint
            for constraint in inspector.get_unique_constraints(
                "subscription_node_access"
            )
        }
        unique = unique_constraints[
            "uq_subscription_node_access_subscription_node"
        ]
        assert unique["column_names"] == [
            "subscription_id",
            "node_code",
        ]

        indexes = indexes_by_name(connection)
        assert set(indexes) == {
            "ix_subscription_node_access_actual_state",
            "ix_subscription_node_access_desired_state",
            "ix_subscription_node_access_node_code",
            "ix_subscription_node_access_subscription_states",
            "ix_subscription_node_access_subscription_id",
        }
        assert indexes[
            "ix_subscription_node_access_subscription_states"
        ]["column_names"] == ["subscription_id", "desired_state", "actual_state"]

        connection.exec_driver_sql(
            """
            INSERT INTO subscription_node_access (
                subscription_id,
                node_code
            ) VALUES (?, ?)
            """,
            (50, "frankfurt"),
        )

        row = connection.exec_driver_sql(
            """
            SELECT desired_state, actual_state, retry_count
            FROM subscription_node_access
            WHERE subscription_id = 50
              AND node_code = 'frankfurt'
            """
        ).one()
        assert row == ("enabled", "pending", 0)

        with pytest.raises(IntegrityError):
            with connection.begin_nested():
                connection.exec_driver_sql(
                    """
                    INSERT INTO subscription_node_access (
                        subscription_id,
                        node_code
                    ) VALUES (?, ?)
                    """,
                    (50, "frankfurt"),
                )

    engine.dispose()


def test_downgrade_removes_node_state_table_only():
    engine = create_engine("sqlite:///:memory:", future=True)

    with engine.begin() as connection:
        create_subscriptions_table(connection)
        run_migration(connection, "upgrade")
        run_migration(connection, "downgrade")

        assert inspect(connection).get_table_names() == ["subscriptions"]

    engine.dispose()
