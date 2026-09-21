"""Write RF messages to the database.

`sonoran-rf-ingest` runs as `azmsh_ingest`, which may INSERT and UPDATE
the RF tables and read only the columns a conflict target or an
`UPDATE ... WHERE` needs (revision 0013). So every upsert here is two
statements, `INSERT ... ON CONFLICT DO NOTHING` then an `UPDATE`, never
`ON CONFLICT DO UPDATE`, which needs table wide SELECT. See `AGENTS.md`
9.2.

The functions are pure of MQTT and of settings beyond the few numbers
they are given, so the tests call them with a session and a message.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import CursorResult, Executable, or_, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from sonoran.db.models import RfHeard, RfLatest, RfStation, RfTrack
from sonoran.rf.schema import AIRCRAFT_KINDS, ICAO, Batch, Observation, Status

# The receiver layer's resolution. Five minutes per thing per station is
# enough to draw where a station hears, and keeps `rf_heard` small.
HEARD_BUCKET = timedelta(minutes=5)


async def _inserted(session: AsyncSession, statement: Executable) -> bool:
    """Run an `INSERT ... ON CONFLICT DO NOTHING`; true when a row was added.

    The affected row count says whether the key was new, without reading
    the table, the same way `ingest/dedup.py` claims a packet.
    """
    result = cast("CursorResult[Any]", await session.execute(statement))
    return bool(result.rowcount)


@dataclass
class Rules:
    """The few numbers the writer needs from the settings."""

    bucket: timedelta = timedelta(seconds=20)
    future_slack: timedelta = timedelta(seconds=60)
    past_slack: timedelta = timedelta(seconds=600)
    hidden: frozenset[str] = frozenset()


@dataclass
class Tally:
    """What happened to one message, for the log line and the tests."""

    stored: int = 0
    retimed: int = 0
    hidden: int = 0
    rejected: int = 0
    kind_not_stored: int = 0
    reasons: list[str] = field(default_factory=list)


def floor_time(when: datetime, step: timedelta) -> datetime:
    """Return the start of the bucket a time falls in."""
    seconds = step.total_seconds()
    epoch = when.timestamp()
    return datetime.fromtimestamp(epoch - (epoch % seconds), UTC)


def guarded_time(stamped: datetime, received: datetime, rules: Rules) -> tuple[datetime, bool]:
    """Return the time to store, and whether it was replaced.

    The receiver stamps each point, and receivers run NTP, so the stamp
    is trusted. A stamp too far ahead of our clock, or too far behind it,
    is a clock fault, and the point is stored at the time we received
    it instead. See the design, 5.3, and `AGENTS.md` 9.4.
    """
    if stamped > received + rules.future_slack or stamped < received - rules.past_slack:
        return received, True
    return stamped, False


async def store_status(session: AsyncSession, status: Status, received: datetime) -> None:
    """Record a station's heartbeat."""
    values = {
        "lat": status.lat,
        "lon": status.lon,
        "precision_m": status.precision_m,
        "kinds": list(status.kinds),
        "agent_version": status.agent_version,
        "heard": status.counts.heard,
        "sent": status.counts.sent,
        "dropped": status.counts.dropped,
        "last_seen": received,
    }
    inserted = await _inserted(
        session,
        insert(RfStation)
        .values(station_id=status.station, **values)
        .on_conflict_do_nothing(index_elements=["station_id"]),
    )
    if not inserted:
        await session.execute(
            update(RfStation).where(RfStation.station_id == status.station).values(**values)
        )


def _point(obs: Observation, when: datetime, station: str) -> dict[str, object]:
    return {
        "t": when,
        "lat": obs.lat,
        "lon": obs.lon,
        "alt_m": obs.alt_m,
        "alt_ref": obs.alt_ref,
        "gs_kn": obs.gs_kn,
        "track_deg": obs.track_deg,
        "rssi_db": obs.rssi_db,
        "station_id": station,
        "meta": obs.meta,
    }


async def _store_track(
    session: AsyncSession, kind: str, obs: Observation, bucket: datetime, point: dict[str, object]
) -> None:
    """Keep one point per thing per bucket: the one heard loudest."""
    inserted = await _inserted(
        session,
        insert(RfTrack)
        .values(kind=kind, thing_id=obs.id, bucket=bucket, **point)
        .on_conflict_do_nothing(index_elements=["kind", "thing_id", "bucket"]),
    )
    if inserted or obs.rssi_db is None:
        return
    await session.execute(
        update(RfTrack)
        .where(
            RfTrack.kind == kind,
            RfTrack.thing_id == obs.id,
            RfTrack.bucket == bucket,
            or_(RfTrack.rssi_db.is_(None), RfTrack.rssi_db < obs.rssi_db),
        )
        .values(**point)
    )


async def _store_heard(
    session: AsyncSession, station: str, kind: str, obs: Observation, when: datetime
) -> None:
    """Count one hearing, and keep the loudest one's position."""
    bucket = floor_time(when, HEARD_BUCKET)
    inserted = await _inserted(
        session,
        insert(RfHeard)
        .values(
            station_id=station,
            kind=kind,
            thing_id=obs.id,
            bucket=bucket,
            heard=1,
            best_rssi_db=obs.rssi_db,
            lat=obs.lat,
            lon=obs.lon,
        )
        .on_conflict_do_nothing(index_elements=["station_id", "kind", "thing_id", "bucket"]),
    )
    if inserted:
        return
    key = (
        RfHeard.station_id == station,
        RfHeard.kind == kind,
        RfHeard.thing_id == obs.id,
        RfHeard.bucket == bucket,
    )
    await session.execute(update(RfHeard).where(*key).values(heard=RfHeard.heard + 1))
    if obs.rssi_db is not None:
        await session.execute(
            update(RfHeard)
            .where(
                *key,
                or_(RfHeard.best_rssi_db.is_(None), RfHeard.best_rssi_db < obs.rssi_db),
            )
            .values(best_rssi_db=obs.rssi_db, lat=obs.lat, lon=obs.lon)
        )


async def _store_latest(
    session: AsyncSession, kind: str, obs: Observation, point: dict[str, object]
) -> None:
    """Keep the newest point of each thing."""
    inserted = await _inserted(
        session,
        insert(RfLatest)
        .values(kind=kind, thing_id=obs.id, **point)
        .on_conflict_do_nothing(index_elements=["kind", "thing_id"]),
    )
    if inserted:
        return
    await session.execute(
        update(RfLatest)
        .where(
            RfLatest.kind == kind,
            RfLatest.thing_id == obs.id,
            RfLatest.t < point["t"],
        )
        .values(**point)
    )


async def store_batch(
    session: AsyncSession, batch: Batch, received: datetime, rules: Rules
) -> Tally:
    """Store one batch of observations. Returns what happened to each."""
    tally = Tally()
    if batch.kind not in AIRCRAFT_KINDS:
        # Phase 1 stores aircraft only. The rest waits for its phase.
        tally.kind_not_stored = len(batch.obs)
        return tally
    for obs in batch.obs:
        if not ICAO.match(obs.id):
            tally.rejected += 1
            tally.reasons.append(f"not an aircraft address: {obs.id!r}")
            continue
        if obs.id in rules.hidden:
            tally.hidden += 1
            continue
        when, retimed = guarded_time(obs.t, received, rules)
        tally.retimed += int(retimed)
        point = _point(obs, when, batch.station)
        await _store_track(session, batch.kind, obs, floor_time(when, rules.bucket), point)
        await _store_heard(session, batch.station, batch.kind, obs, when)
        await _store_latest(session, batch.kind, obs, point)
        tally.stored += 1
    return tally
