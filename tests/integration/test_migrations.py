"""Integration tests for the initial migration.

These tests run against a real TimescaleDB container.
They check upgrade, hypertables, retention policies, roles, grants,
and downgrade.
"""

import os

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from sonoran.db.hypertables import HYPERTABLES

EXPECTED_TABLES = {
    "node",
    "packet",
    "packet_seen",
    "traceroute",
    "text_message",
    "device_metrics",
    "environment_metrics",
    "air_quality_metrics",
    "power_metrics",
    "pax_metrics",
    "mesh_packet_metrics",
    "position_metrics",
    "neighbor_metrics",
    "node_config",
    "daily_snapshot",
}

ROLES = {"azmsh_ingest", "azmsh_api", "azmsh_jobs"}


def test_all_tables_exist(migrated_engine) -> None:  # type: ignore[no-untyped-def]
    with migrated_engine.connect() as conn:
        rows = conn.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        ).fetchall()
    existing = {row[0] for row in rows}
    assert EXPECTED_TABLES <= existing


def test_hypertables_registered(migrated_engine) -> None:  # type: ignore[no-untyped-def]
    with migrated_engine.connect() as conn:
        rows = conn.execute(
            text("SELECT hypertable_name FROM timescaledb_information.hypertables")
        ).fetchall()
    hypertables = {row[0] for row in rows}
    expected = {name for name, _, _ in HYPERTABLES}
    assert expected <= hypertables


def test_retention_policies_registered(migrated_engine) -> None:  # type: ignore[no-untyped-def]
    with migrated_engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT hypertable_name FROM timescaledb_information.jobs "
                "WHERE proc_name = 'policy_retention'"
            )
        ).fetchall()
    with_policy = {row[0] for row in rows}
    expected = {name for name, _, _ in HYPERTABLES}
    assert expected <= with_policy


def test_roles_exist(migrated_engine) -> None:  # type: ignore[no-untyped-def]
    with migrated_engine.connect() as conn:
        rows = conn.execute(text("SELECT rolname FROM pg_roles")).fetchall()
    existing = {row[0] for row in rows}
    assert ROLES <= existing


def test_api_role_is_select_only(migrated_engine) -> None:  # type: ignore[no-untyped-def]
    with migrated_engine.connect() as conn:
        privs = conn.execute(
            text(
                "SELECT privilege_type FROM information_schema.role_table_grants "
                "WHERE grantee = 'azmsh_api' AND table_name = 'packet'"
            )
        ).fetchall()
    assert {row[0] for row in privs} == {"SELECT"}


def test_ingest_role_has_write_only_access(migrated_engine) -> None:  # type: ignore[no-untyped-def]
    with migrated_engine.connect() as conn:
        privs = conn.execute(
            text(
                "SELECT privilege_type FROM information_schema.role_table_grants "
                "WHERE grantee = 'azmsh_ingest' AND table_name = 'packet'"
            )
        ).fetchall()
    granted = {row[0] for row in privs}
    assert {"INSERT", "UPDATE"} <= granted
    assert "SELECT" not in granted
    assert "DELETE" not in granted


def test_jobs_role_can_delete_daily_snapshots(migrated_engine) -> None:  # type: ignore[no-untyped-def]
    """The jobs role can delete daily snapshots for retention fallback."""
    with migrated_engine.connect() as conn:
        privs = conn.execute(
            text(
                "SELECT privilege_type FROM information_schema.role_table_grants "
                "WHERE grantee = 'azmsh_jobs' AND table_name = 'daily_snapshot'"
            )
        ).fetchall()
    assert "DELETE" in {row[0] for row in privs}


def test_insert_uses_boolean_server_defaults(migrated_engine) -> None:  # type: ignore[no-untyped-def]
    """Raw SQL inserts use false for omitted required Boolean columns."""
    inserts = (
        text(
            "INSERT INTO node (node_num, node_id, first_seen, updated_at) "
            "VALUES (1, '!00000001', '2026-08-01T12:00:00Z', '2026-08-01T12:00:00Z')"
        ),
        text(
            "INSERT INTO packet (from_node_num, packet_id, portnum, first_seen_at) "
            "VALUES (1, 100, 1, '2026-08-01T12:00:00Z')"
        ),
        text(
            "INSERT INTO text_message (from_node_num, to_node_num, body, seen_at) "
            "VALUES (1, 2, 'test', '2026-08-01T12:00:00Z')"
        ),
    )
    with migrated_engine.connect() as conn:
        for insert in inserts:
            conn.execute(insert)
        conn.commit()
        node_values = conn.execute(
            text("SELECT is_licensed, is_mqtt_gateway FROM node WHERE node_num = 1")
        ).one()
        want_ack = conn.execute(
            text("SELECT want_ack FROM packet WHERE from_node_num = 1 AND packet_id = 100")
        ).scalar_one()
        emoji = conn.execute(
            text("SELECT emoji FROM text_message WHERE from_node_num = 1 AND body = 'test'")
        ).scalar_one()
    assert node_values == (False, False)
    assert want_ack is False
    assert emoji is False


def test_dedup_unique_key(migrated_engine) -> None:  # type: ignore[no-untyped-def]
    """The dedup key rejects a duplicate packet."""
    insert = text(
        "INSERT INTO packet (from_node_num, packet_id, portnum, first_seen_at) "
        "VALUES (1, 101, 1, '2026-08-01T12:00:00Z')"
    )
    with migrated_engine.connect() as conn:
        conn.execute(insert)
        conn.commit()
        with pytest.raises(IntegrityError):
            with conn.begin_nested():
                conn.execute(insert)
        count = conn.execute(
            text("SELECT count(*) FROM packet WHERE from_node_num = 1 AND packet_id = 101")
        ).scalar_one()
    assert count == 1


def test_revision_downgrade_and_upgrade(timescale_url: str) -> None:  # type: ignore[no-untyped-def]
    """Each new schema revision can downgrade and upgrade."""
    config = Config("alembic.ini")
    os.environ["DATABASE_URL_MIGRATE"] = timescale_url

    command.downgrade(config, "0002")
    command.upgrade(config, "head")
    command.downgrade(config, "0001")
    command.upgrade(config, "head")


def test_downgrade_and_upgrade(timescale_url: str) -> None:  # type: ignore[no-untyped-def]
    """Downgrade to base removes the tables. Upgrade restores them."""
    config = Config("alembic.ini")
    os.environ["DATABASE_URL_MIGRATE"] = timescale_url

    command.downgrade(config, "base")
    from sqlalchemy import create_engine

    engine = create_engine(timescale_url)
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        ).fetchall()
    assert not (EXPECTED_TABLES & {row[0] for row in rows})

    command.upgrade(config, "head")
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        ).fetchall()
    assert EXPECTED_TABLES <= {row[0] for row in rows}
    engine.dispose()


# --- the role passwords ------------------------------------------------
#
# Revision 0001 used to default all three to `change_me`, and
# `.env.example` shipped that value in all three DSNs while never naming
# the variables that set the real ones. `tools/db_restore.sh` tells an
# operator to copy that file, so the documented first run gave a working
# deployment whose three least-privilege roles all had a password
# published in this repository. Nothing reported a fault, because from
# the outside there was not one.


def _fresh_database(timescale_url: str, name: str) -> str:
    """Make an empty database in the running container and return its URL.

    The migration only creates roles on a database it has not already
    migrated, so a test about what it refuses needs ground of its own.
    """
    from sqlalchemy import create_engine

    admin = create_engine(timescale_url)
    with admin.connect() as conn:
        autocommit = conn.execution_options(isolation_level="AUTOCOMMIT")
        autocommit.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
        autocommit.execute(text(f'CREATE DATABASE "{name}"'))
    admin.dispose()
    base, _ = timescale_url.rsplit("/", maxsplit=1)
    return f"{base}/{name}"


def test_a_missing_role_password_stops_the_migration(
    timescale_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No password, no migration. It used to be `change_me` and carry on.

    The refusal happens before any role statement runs, so a deployment
    that is missing one variable does not half-create its roles.
    """
    url = _fresh_database(timescale_url, "azmsh_missing_pw_test")
    monkeypatch.delenv("AZMSH_INGEST_PASSWORD", raising=False)
    monkeypatch.setenv("DATABASE_URL_MIGRATE", url)

    config = Config("alembic.ini")
    with pytest.raises(Exception) as caught:
        command.upgrade(config, "head")
    message = str(caught.value)
    assert "AZMSH_INGEST_PASSWORD" in message, message

    # Nothing of the schema was written. The migration refused rather
    # than leaving a database half built.
    from sqlalchemy import create_engine

    engine = create_engine(url)
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        ).fetchall()
    assert not (EXPECTED_TABLES & {row[0] for row in rows})
    engine.dispose()


def test_the_placeholder_password_stops_the_migration(
    timescale_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A copy of .env.example that was not edited must not deploy."""
    url = _fresh_database(timescale_url, "azmsh_placeholder_pw_test")
    monkeypatch.setenv("AZMSH_INGEST_PASSWORD", "change_me")
    monkeypatch.setenv("DATABASE_URL_MIGRATE", url)

    config = Config("alembic.ini")
    with pytest.raises(Exception) as caught:
        command.upgrade(config, "head")
    assert "AZMSH_INGEST_PASSWORD" in str(caught.value)


def test_an_awkward_password_is_a_value_and_not_grammar(timescale_url: str) -> None:
    """A quote in a password reaches PostgreSQL as a character.

    The password is interpolated into a `CREATE ROLE` statement, so this
    is the one place an operator's own choice of characters meets the
    parser. It is checked against a real server rather than by reading
    the escape, and on a role of its own: the three real roles already
    exist in this cluster and `IF NOT EXISTS` would skip them, so a test
    that used them would assert nothing at all.
    """
    import importlib.util
    from pathlib import Path
    from urllib.parse import quote

    from sqlalchemy import create_engine

    spec = importlib.util.spec_from_file_location(
        "sonoran_initial_migration_it",
        Path("src/sonoran/db/migrations/versions/0001_initial.py"),
    )
    assert spec is not None and spec.loader is not None
    initial = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(initial)

    # Every character that has ever broken one of these statements.
    password = "pa'ss\"w\\ord$$x -- ;"
    literal = initial._sql_literal(password)
    role = "azmsh_quote_test"

    admin = create_engine(timescale_url)
    try:
        with admin.connect() as conn:
            autocommit = conn.execution_options(isolation_level="AUTOCOMMIT")
            autocommit.execute(text(f"DROP ROLE IF EXISTS {role}"))
            # The same shape the migration uses: a dollar-quoted block
            # with the literal placed inside it.
            autocommit.execute(
                text(
                    f"DO {initial.ROLE_BLOCK_TAG} BEGIN "
                    f"CREATE ROLE {role} LOGIN PASSWORD {literal}; "
                    f"END {initial.ROLE_BLOCK_TAG};"
                )
            )
            # The role exists, and exactly one of it. A statement that
            # had been closed early would have left other objects too.
            count = conn.execute(
                text("SELECT count(*) FROM pg_roles WHERE rolname LIKE 'azmsh_quote%'")
            ).scalar_one()
            assert count == 1

        # And the password is the one that was asked for, character for
        # character. This is the assertion the escape exists to make
        # true: log in with it.
        _, address = timescale_url.split("@", maxsplit=1)
        as_role = create_engine(f"postgresql+psycopg://{role}:{quote(password, safe='')}@{address}")
        with as_role.connect() as conn:
            assert conn.execute(text("SELECT current_user")).scalar_one() == role
        as_role.dispose()
    finally:
        with admin.connect() as conn:
            conn.execution_options(isolation_level="AUTOCOMMIT").execute(
                text(f"DROP ROLE IF EXISTS {role}")
            )
        admin.dispose()
