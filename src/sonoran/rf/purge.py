"""`sonoran-rf-purge`: remove one RF station's data, for an operator.

For a station that sent bad data: revoke its login first (the Discord
`/rf token revoke` or `/rf location delete`), then purge what it left::

    docker compose run --rm migrate sonoran-rf-purge <station>          # dry run
    docker compose run --rm migrate sonoran-rf-purge <station> --yes    # delete

It runs as the database owner (`DATABASE_URL_MIGRATE`), because no
application role may delete. It removes the station from every RF
table in one transaction. A "latest position" the station held is put
back from another station's newest point of the same thing, where one
is still kept, so a plane heard by others does not vanish from the map.

What it cannot undo: a shared track point the station won (the loudest
hearing wins, `store.py`) replaced another station's point for that
20 s, and that point is gone.

The broker keeps the station's last heartbeat as a retained message,
and the ingest reads it again when it reconnects. The registrar clears
it for a revoked minted login; for a login made by hand, the command
prints the broker call that clears it.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from typing import Any, cast

from sqlalchemy import CursorResult, create_engine, delete, func, insert, select, tuple_
from sqlalchemy.engine import Connection

from sonoran.db.models import (
    RfHeard,
    RfLatest,
    RfSource,
    RfSpectrum,
    RfSpectrumHour,
    RfStation,
    RfTrack,
)
from sonoran.rf.schema import NO_SOURCE, STATION_ID

# Every table that holds a station's rows, by its station column.
TABLES: tuple[tuple[str, Any], ...] = (
    ("rf_track", RfTrack),
    ("rf_latest", RfLatest),
    ("rf_heard", RfHeard),
    ("rf_spectrum", RfSpectrum),
    ("rf_spectrum_hour", RfSpectrumHour),
    ("rf_source", RfSource),
    ("rf_station", RfStation),
)


@dataclass
class Report:
    counts: dict[str, int]
    restored: int
    sources: list[str]


def survey(conn: Connection, station: str) -> Report:
    """Count what the station has, and name its sources."""
    counts = {
        name: int(
            conn.execute(
                select(func.count()).select_from(model).where(model.station_id == station)
            ).scalar_one()
        )
        for name, model in TABLES
    }
    sources = [
        row[0]
        for row in conn.execute(
            select(RfSource.source).where(RfSource.station_id == station).order_by(RfSource.source)
        )
    ]
    return Report(counts, 0, sources)


def purge(conn: Connection, station: str) -> Report:
    """Delete the station's rows. The caller owns the transaction."""
    report = survey(conn, station)
    held = list(
        conn.execute(
            select(RfLatest.kind, RfLatest.thing_id).where(RfLatest.station_id == station)
        ).tuples()
    )
    for _, model in TABLES:
        conn.execute(delete(model).where(model.station_id == station))
    if held:
        # The newest point of each thing from any other station, from the
        # tracks that are still kept.
        newest = (
            select(
                RfTrack.kind,
                RfTrack.thing_id,
                RfTrack.t,
                RfTrack.lat,
                RfTrack.lon,
                RfTrack.alt_m,
                RfTrack.alt_ref,
                RfTrack.gs_kn,
                RfTrack.track_deg,
                RfTrack.rssi_db,
                RfTrack.station_id,
                RfTrack.meta,
            )
            .where(tuple_(RfTrack.kind, RfTrack.thing_id).in_(held))
            .distinct(RfTrack.kind, RfTrack.thing_id)
            .order_by(RfTrack.kind, RfTrack.thing_id, RfTrack.t.desc())
        )
        result = cast(
            "CursorResult[Any]",
            conn.execute(
                insert(RfLatest).from_select(
                    [
                        "kind",
                        "thing_id",
                        "t",
                        "lat",
                        "lon",
                        "alt_m",
                        "alt_ref",
                        "gs_kn",
                        "track_deg",
                        "rssi_db",
                        "station_id",
                        "meta",
                    ],
                    newest,
                )
            ),
        )
        report.restored = result.rowcount or 0
    return report


def retained_topics(station: str, sources: list[str]) -> list[str]:
    """The retained topics the broker may still hold for the station."""
    topics = [f"rf/v1/{station}/status", f"rf/v1/{station}/registry"]
    topics += [f"rf/v1/{station}/status/{s}" for s in sources if s != NO_SOURCE]
    return topics


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="sonoran-rf-purge",
        description="Remove one RF station's data. A dry run unless --yes.",
    )
    parser.add_argument("station", help="the station id, such as tempe-roof")
    parser.add_argument("--yes", action="store_true", help="delete; without it, only count")
    args = parser.parse_args(argv)
    if not STATION_ID.match(args.station):
        print(f"{args.station!r} is not a station id", file=sys.stderr)
        return 2
    url = os.environ.get("DATABASE_URL_MIGRATE")
    if not url:
        print("DATABASE_URL_MIGRATE is not set; run it in the migrate service", file=sys.stderr)
        return 2
    engine = create_engine(url.replace("+asyncpg", "+psycopg"))
    try:
        with engine.begin() as conn:
            report = purge(conn, args.station) if args.yes else survey(conn, args.station)
            if args.yes and not any(report.counts.values()):
                print(f"{args.station}: nothing to remove")
                return 1
    finally:
        engine.dispose()
    verb = "removed" if args.yes else "would remove"
    print(f"{args.station}: {verb}")
    for name, count in report.counts.items():
        print(f"  {count:>8}  {name}")
    if args.yes:
        print(f"  {report.restored:>8}  latest positions put back from other stations")
    else:
        print("Nothing was deleted. Run again with --yes to delete.")
    print("Retained messages the broker may still hold (cleared for a revoked minted login;")
    print("for a login made by hand, clear each with the broker's API):")
    for topic in retained_topics(args.station, report.sources):
        print(f"  {topic}")
    return 0


def run() -> None:
    """Console script entry point."""
    sys.exit(main())
