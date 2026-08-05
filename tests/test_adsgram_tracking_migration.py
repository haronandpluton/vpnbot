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
    "b7d4e9a2c610_add_adsgram_tracking.py"
)


def load_migration():
    spec = spec_from_file_location(
        "adsgram_tracking_migration",
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


def create_dependency_tables(connection) -> None:
    connection.exec_driver_sql(
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY
        )
        """
    )
    connection.exec_driver_sql(
        """
        CREATE TABLE orders (
            id INTEGER PRIMARY KEY
        )
        """
    )


def indexes_by_name(
    connection,
    table_name: str,
) -> dict[str, dict]:
    return {
        index["name"]: index
        for index in inspect(connection).get_indexes(table_name)
    }


def test_upgrade_adds_first_touch_columns_and_conversion_outbox():
    engine = create_engine("sqlite:///:memory:", future=True)

    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        create_dependency_tables(connection)

        connection.exec_driver_sql(
            "INSERT INTO users (id) VALUES (10)"
        )
        connection.exec_driver_sql(
            "INSERT INTO orders (id) VALUES (20)"
        )

        run_migration(connection, "upgrade")

        inspector = inspect(connection)
        assert "adsgram_conversions" in inspector.get_table_names()

        user_columns = {
            column["name"]: column
            for column in inspector.get_columns("users")
        }
        assert user_columns["adsgram_campaign_id"]["nullable"] is True
        assert user_columns["adsgram_attributed_at"]["nullable"] is True

        assert indexes_by_name(connection, "users")[
            "ix_users_adsgram_campaign_id"
        ]["unique"] == 0

        conversion_columns = {
            column["name"]: column
            for column in inspector.get_columns(
                "adsgram_conversions"
            )
        }

        assert conversion_columns["status"]["default"] == "'pending'"
        assert conversion_columns["attempt_count"]["default"] == "'0'"
        assert conversion_columns["order_id"]["nullable"] is True
        assert conversion_columns["last_error"]["nullable"] is True

        foreign_keys = {
            tuple(foreign_key["constrained_columns"]): foreign_key
            for foreign_key in inspector.get_foreign_keys(
                "adsgram_conversions"
            )
        }

        assert foreign_keys[("user_id",)]["referred_table"] == "users"
        assert (
            foreign_keys[("user_id",)]["options"]["ondelete"]
            == "CASCADE"
        )

        assert foreign_keys[("order_id",)]["referred_table"] == "orders"
        assert (
            foreign_keys[("order_id",)]["options"]["ondelete"]
            == "SET NULL"
        )

        indexes = indexes_by_name(
            connection,
            "adsgram_conversions",
        )

        assert indexes[
            "ix_adsgram_conversions_idempotency_key"
        ]["unique"] == 1

        assert indexes[
            "ix_adsgram_conversions_status_next_attempt_at"
        ]["column_names"] == [
            "status",
            "next_attempt_at",
        ]

        connection.exec_driver_sql(
            """
            INSERT INTO adsgram_conversions (
                user_id,
                order_id,
                campaign_id,
                goal_type,
                idempotency_key
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                10,
                20,
                "campaign-1",
                2,
                "purchase:order:20",
            ),
        )

        row = connection.exec_driver_sql(
            """
            SELECT status, attempt_count
            FROM adsgram_conversions
            WHERE idempotency_key = 'purchase:order:20'
            """
        ).one()

        assert row == ("pending", 0)

        with pytest.raises(IntegrityError):
            with connection.begin_nested():
                connection.exec_driver_sql(
                    """
                    INSERT INTO adsgram_conversions (
                        user_id,
                        campaign_id,
                        goal_type,
                        idempotency_key
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (
                        10,
                        "campaign-1",
                        2,
                        "purchase:order:20",
                    ),
                )

        with pytest.raises(IntegrityError):
            with connection.begin_nested():
                connection.exec_driver_sql(
                    """
                    INSERT INTO adsgram_conversions (
                        user_id,
                        campaign_id,
                        goal_type,
                        idempotency_key
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (
                        10,
                        "campaign-1",
                        4,
                        "invalid-goal",
                    ),
                )

    engine.dispose()


def test_downgrade_removes_outbox_and_user_attribution_columns():
    engine = create_engine("sqlite:///:memory:", future=True)

    with engine.begin() as connection:
        create_dependency_tables(connection)

        run_migration(connection, "upgrade")
        run_migration(connection, "downgrade")

        inspector = inspect(connection)

        assert (
            "adsgram_conversions"
            not in inspector.get_table_names()
        )

        assert {
            column["name"]
            for column in inspector.get_columns("users")
        } == {"id"}

        assert inspector.get_table_names() == [
            "orders",
            "users",
        ]

    engine.dispose()