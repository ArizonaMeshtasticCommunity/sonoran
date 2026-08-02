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
