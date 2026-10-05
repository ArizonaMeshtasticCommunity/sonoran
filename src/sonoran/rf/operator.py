"""`sonoran-rf-trust`: set how far a station is trusted, and hide a mod (#324).

The server never trusts the station. Every message is a claim from one
station and source, and the shared layers (one track and one "latest"
point per thing, across every station) decide between stations by a
trust level that only an operator sets, here::

    docker compose run --rm migrate sonoran-rf-trust list
    docker compose run --rm migrate sonoran-rf-trust set <station> trusted
    docker compose run --rm migrate sonoran-rf-trust set <station> quarantined --note "spoofs"
    docker compose run --rm migrate sonoran-rf-trust set <station> new --source pi5
    docker compose run --rm migrate sonoran-rf-trust hide-mod <station> <mod>
    docker compose run --rm migrate sonoran-rf-trust show-mod <station> <mod>
    docker compose run --rm migrate sonoran-rf-trust log [<station>]

- `new` is every station's level until an operator sets one.
- `trusted` wins a shared point against a `new` station.
- `quarantined` adds nothing to a shared layer. The station's own data is
  still stored, its mods are not shown, and the map says it is
  quarantined.

`--source` sets one source of a station; without it, the level is the
station's, for every source that has none of its own. `new` with no note
removes the row, so the station is back to the default.

The ingest reads the levels again every `RF_TRUST_REFRESH_SECONDS`. Every
change is written to `rf_operator_log`. It runs as the database owner
(`DATABASE_URL_MIGRATE`), because no application role may write these.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from datetime import UTC, datetime

from sqlalchemy import create_engine, delete, insert, select, update
from sqlalchemy.engine import Connection

from sonoran.db.models import RfHiddenMod, RfOperatorLog, RfTrust
from sonoran.rf.guard import ANY_SOURCE, NEW, TRUST_LEVELS, TRUST_NAMES
from sonoran.rf.schema import NAME, SOURCE_ID, STATION_ID

MAX_NOTE = 200


def actor_name() -> str:
    """Who is running the command: the sudo user, else the login."""
    return os.environ.get("SUDO_USER") or os.environ.get("USER") or getpass.getuser()


def log_action(conn: Connection, actor: str, action: str, station: str, detail: str) -> None:
    """Write one line to `rf_operator_log`."""
    conn.execute(
        insert(RfOperatorLog).values(
            at=datetime.now(UTC), actor=actor, action=action, station_id=station, detail=detail
        )
    )


def set_trust(
    conn: Connection, station: str, source: str, level: int, note: str | None, actor: str
) -> str:
    """Set a level, log it, and return what changed, in words."""
    now = datetime.now(UTC)
    key = (RfTrust.station_id == station, RfTrust.source == source)
    old = conn.execute(select(RfTrust.trust).where(*key)).scalar_one_or_none()
    before = TRUST_NAMES[NEW if old is None else int(old)]
    if level == NEW and not note:
        conn.execute(delete(RfTrust).where(*key))
    elif old is None:
        conn.execute(
            insert(RfTrust).values(
                station_id=station, source=source, trust=level, note=note, set_at=now
            )
        )
    else:
        conn.execute(update(RfTrust).where(*key).values(trust=level, note=note, set_at=now))
    who = station if source == ANY_SOURCE else f"{station}/{source}"
    change = f"{who}: {before} -> {TRUST_NAMES[level]}" + (f" ({note})" if note else "")
    log_action(conn, actor, "trust", station, change)
    return change


def hide_mod(
    conn: Connection, station: str, mod: str, hidden: bool, note: str | None, actor: str
) -> str:
    """Hide a mod from every viewer, or show it again. Logged."""
    key = (RfHiddenMod.station_id == station, RfHiddenMod.mod == mod)
    conn.execute(delete(RfHiddenMod).where(*key))
    if hidden:
        conn.execute(
            insert(RfHiddenMod).values(
                station_id=station, mod=mod, note=note, set_at=datetime.now(UTC)
            )
        )
    change = f"{station}/{mod}: {'hidden' if hidden else 'shown'}" + (f" ({note})" if note else "")
    log_action(conn, actor, "hide mod" if hidden else "show mod", station, change)
    return change


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sonoran-rf-trust",
        description="Set RF station trust levels and hide members' mods. Every change is logged.",
    )
    parser.add_argument("--by", help="who asked for it, for the log; default the user")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="every level an operator set, and every hidden mod")
    level = commands.add_parser("set", help="set a station's or a source's trust level")
    level.add_argument("station")
    level.add_argument("level", choices=sorted(TRUST_LEVELS))
    level.add_argument("--source", help="one source of the station; default all of them")
    level.add_argument("--note", help="why, for the log")
    for name, text in (("hide-mod", "hide a mod from everyone"), ("show-mod", "show it again")):
        mod = commands.add_parser(name, help=text)
        mod.add_argument("station")
        mod.add_argument("mod")
        mod.add_argument("--note", help="why, for the log")
    log = commands.add_parser("log", help="the operator log, newest first")
    log.add_argument("station", nargs="?")
    log.add_argument("--limit", type=int, default=50)
    return parser


def _check(args: argparse.Namespace) -> str | None:
    station = getattr(args, "station", None)
    if station is not None and not STATION_ID.match(station):
        return f"{station!r} is not a station id"
    source = getattr(args, "source", None)
    if source is not None and not SOURCE_ID.match(source):
        return f"{source!r} is not a source id"
    mod = getattr(args, "mod", None)
    if mod is not None and not NAME.match(mod):
        return f"{mod!r} is not a mod name"
    note = getattr(args, "note", None)
    if note is not None and len(note) > MAX_NOTE:
        return f"the note is longer than {MAX_NOTE} characters"
    return None


def _list(conn: Connection) -> None:
    rows = conn.execute(select(RfTrust).order_by(RfTrust.station_id, RfTrust.source)).scalars()
    print("Trust levels (every other station is new):")
    for row in rows:
        who = row.station_id if row.source == ANY_SOURCE else f"{row.station_id}/{row.source}"
        note = f"  {row.note}" if row.note else ""
        print(f"  {who:<40} {TRUST_NAMES.get(row.trust, row.trust)}{note}")
    print("Hidden mods:")
    for mod in conn.execute(select(RfHiddenMod).order_by(RfHiddenMod.station_id)).scalars():
        note = f"  {mod.note}" if mod.note else ""
        print(f"  {mod.station_id}/{mod.mod}{note}")


def _log(conn: Connection, station: str | None, limit: int) -> None:
    query = select(RfOperatorLog).order_by(RfOperatorLog.id.desc()).limit(max(1, limit))
    if station:
        query = query.where(RfOperatorLog.station_id == station)
    for row in conn.execute(query).scalars():
        print(f"{row.at:%Y-%m-%d %H:%M} UTC  {row.actor:<12} {row.action:<10} {row.detail}")


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    problem = _check(args)
    if problem:
        print(problem, file=sys.stderr)
        return 2
    url = os.environ.get("DATABASE_URL_MIGRATE")
    if not url:
        print("DATABASE_URL_MIGRATE is not set; run it in the migrate service", file=sys.stderr)
        return 2
    actor = args.by or actor_name()
    engine = create_engine(url.replace("+asyncpg", "+psycopg"))
    try:
        with engine.begin() as conn:
            if args.command == "list":
                _list(conn)
            elif args.command == "log":
                _log(conn, args.station, args.limit)
            elif args.command == "set":
                source = args.source or ANY_SOURCE
                level = TRUST_LEVELS[args.level]
                print(set_trust(conn, args.station, source, level, args.note, actor))
            else:
                hidden = args.command == "hide-mod"
                print(hide_mod(conn, args.station, args.mod, hidden, args.note, actor))
    finally:
        engine.dispose()
    return 0


def run() -> None:
    """Console script entry point."""
    sys.exit(main())
