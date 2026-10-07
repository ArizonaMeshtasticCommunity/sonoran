"""The RF migrations, run over data that was there before them.

Every other migration test runs on an empty database, so it cannot see
what a migration does to rows already stored. Revision 0020 filled the
new `source` column with `-` for every stored spectrum minute, and on the
live deployment that hid a station's whole history behind a range one
minute long (2026-10-07). Revision 0021 repairs it. These tests put rows
in at the revision before, upgrade, and read the result through the API
the way the page does.
"""

import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from sonoran.api.app import create_app
from sonoran.config import Settings
from tests.integration.conftest import role_url

NOW = datetime.now(UTC).replace(second=0, microsecond=0)
ARRAYS = "'{-500,-500}', '{-460,-460}', '{-410,-410}', '{0,10}'"


@pytest.fixture
def at(timescale_url: str, migrated_engine) -> Iterator:  # type: ignore[no-untyped-def]
    """Move the schema to a revision; always leave it at head again."""
    migrated_engine.dispose()
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", timescale_url)
    os.environ["DATABASE_URL_MIGRATE"] = timescale_url
    engine = create_engine(timescale_url)
    with engine.begin() as conn:
        conn.execute(
            text("TRUNCATE rf_station, rf_source, rf_spectrum, rf_spectrum_hour, rf_custom")
        )

    def move(revision: str) -> None:
        engine.dispose()
        if revision == "head":
            command.upgrade(config, "head")
        else:
            command.downgrade(config, revision)

    try:
        yield move, engine
    finally:
        engine.dispose()
        command.upgrade(config, "head")
        migrated_engine.dispose()


def _source(conn, station: str, source: str) -> None:  # type: ignore[no-untyped-def]
    conn.execute(
        text(
            "INSERT INTO rf_station (station_id, last_seen) VALUES (:s, now()) "
            "ON CONFLICT DO NOTHING"
        ),
        {"s": station},
    )
    conn.execute(
        text("INSERT INTO rf_source (station_id, source, last_seen) VALUES (:s, :src, now())"),
        {"s": station, "src": source},
    )


def _old_minute(conn, station: str, minutes_ago: int) -> None:  # type: ignore[no-untyped-def]
    """A minute as the ingest before 0020 stored it: no source, no bins."""
    conn.execute(
        text(
            "INSERT INTO rf_spectrum (station_id, t, f_start_hz, bin_hz, sweeps, gain_db, "
            f"p50, p95, peak, busy, received_at) VALUES (:s, :t, 902000000, 25000, 12, 30, "
            f"{ARRAYS}, now())"
        ),
        {"s": station, "t": NOW - timedelta(minutes=minutes_ago)},
    )


def _sources(engine, station: str) -> list[str]:  # type: ignore[no-untyped-def]
    with engine.begin() as conn:
        return [
            row[0]
            for row in conn.execute(
                text("SELECT source FROM rf_spectrum WHERE station_id = :s ORDER BY t"),
                {"s": station},
            )
        ]


def test_a_stations_history_keeps_its_one_source_through_the_upgrade(
    timescale_url: str, at
) -> None:  # type: ignore[no-untyped-def]
    move, engine = at
    move("0019")
    with engine.begin() as conn:
        # One source, as every minted login has: its history is that source's.
        _source(conn, "one-source", "pi5")
        # An agent that sends no source: its rows stay `-`.
        _source(conn, "no-source", "-")
        # Two sources: which sent an old minute is not known, so it stays `-`.
        _source(conn, "two-sources", "pi-a")
        _source(conn, "two-sources", "pi-b")
        for station in ("one-source", "no-source", "two-sources"):
            for minutes_ago in (3, 2, 1):
                _old_minute(conn, station, minutes_ago)
    move("head")

    assert _sources(engine, "one-source") == ["pi5"] * 3
    assert _sources(engine, "no-source") == ["-"] * 3
    assert _sources(engine, "two-sources") == ["-"] * 3

    settings = Settings(_env_file=None, database_url_api=role_url(timescale_url, "azmsh_api"))
    with TestClient(create_app(settings)) as client:
        ranges = client.get("/api/rf/spectrum/one-source/ranges").json()["ranges"]
        waterfall = client.get("/api/rf/spectrum/one-source?hours=1").json()
    # One range, holding the whole history: what the page opens on.
    assert [(r["id"], r["minutes"]) for r in ranges] == [("pi5:902000000:25000:2", 3)]
    assert sum(1 for row in waterfall["rows"] if row["minutes"]) == 3


def test_a_minute_stored_twice_across_the_upgrade_is_kept_once(timescale_url: str, at) -> None:  # type: ignore[no-untyped-def]
    """The old ingest's copy and the new one's, of the same minute."""
    move, engine = at
    move("0020")
    with engine.begin() as conn:
        _source(conn, "one-source", "pi5")
        for source in ("-", "pi5"):
            conn.execute(
                text(
                    "INSERT INTO rf_spectrum (station_id, source, t, f_start_hz, bin_hz, bins, "
                    "sweeps, gain_db, p50, p95, peak, busy, received_at) VALUES "
                    f"('one-source', :src, :t, 902000000, 25000, 2, 12, 30, {ARRAYS}, now())"
                ),
                {"src": source, "t": NOW},
            )
    move("head")
    assert _sources(engine, "one-source") == ["pi5"]
