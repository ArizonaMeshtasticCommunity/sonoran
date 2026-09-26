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

from sonoran.db.models import RfHeard, RfLatest, RfSpectrum, RfStation, RfTrack
from sonoran.rf.schema import (
    APRS_ALIAS,
    APRS_OBJECT,
    APRS_STATION,
    HEARD_PRECISION_M,
    STORED_KINDS,
    THING_ID,
    Batch,
    Observation,
    Spectrum,
    Status,
)

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
    # rtl_433 model names that may be stored, lower case. Empty means
    # none: see `ism_model`.
    ism_allow: frozenset[str] = frozenset()


@dataclass
class Tally:
    """What happened to one message, for the log line and the tests."""

    stored: int = 0
    retimed: int = 0
    hidden: int = 0
    not_allowed: int = 0
    # Stored on the map, but not counted as heard by the station.
    relayed: int = 0
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


# The spectrum grid: one row per station per minute (design 4.2).
SPECTRUM_MINUTE = timedelta(minutes=1)


async def store_spectrum(
    session: AsyncSession, spectrum: Spectrum, received: datetime, rules: Rules
) -> bool:
    """Store one minute of the band. True when it was new.

    The minute is the station's own `t`, floored to the minute, unless
    its clock is out, when it is the minute we received it in, as for
    every other RF point (design 5.3). A second message for the same
    station and minute is a repeat and is ignored.
    """
    stamped, _ = guarded_time(spectrum.t, received, rules)
    return await _inserted(
        session,
        insert(RfSpectrum)
        .values(
            station_id=spectrum.station,
            t=floor_time(stamped, SPECTRUM_MINUTE),
            f_start_hz=spectrum.f_start_hz,
            bin_hz=spectrum.bin_hz,
            sweeps=spectrum.sweeps,
            gain_db=spectrum.gain_db,
            p50=list(spectrum.p50),
            p95=list(spectrum.p95),
            peak=list(spectrum.peak),
            busy=list(spectrum.busy),
            received_at=received,
        )
        .on_conflict_do_nothing(index_elements=["station_id", "t"]),
    )


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


@dataclass(frozen=True)
class Hearing:
    """One thing a station heard itself, for `rf_heard`.

    `lat` and `lon` are None when the hearing places nothing: a
    digipeater named in a path, whose position comes from its own
    beacons when the layer is read, or a sender that blurred its
    position past the size of a cell.
    """

    thing_id: str
    rssi_db: float | None
    lat: float | None
    lon: float | None


async def _store_heard(
    session: AsyncSession, station: str, kind: str, hearing: Hearing, when: datetime
) -> None:
    """Count one hearing, and keep the loudest one's position."""
    bucket = floor_time(when, HEARD_BUCKET)
    inserted = await _inserted(
        session,
        insert(RfHeard)
        .values(
            station_id=station,
            kind=kind,
            thing_id=hearing.thing_id,
            bucket=bucket,
            heard=1,
            best_rssi_db=hearing.rssi_db,
            lat=hearing.lat,
            lon=hearing.lon,
        )
        .on_conflict_do_nothing(index_elements=["station_id", "kind", "thing_id", "bucket"]),
    )
    if inserted:
        return
    key = (
        RfHeard.station_id == station,
        RfHeard.kind == kind,
        RfHeard.thing_id == hearing.thing_id,
        RfHeard.bucket == bucket,
    )
    await session.execute(update(RfHeard).where(*key).values(heard=RfHeard.heard + 1))
    placed = {"lat": hearing.lat, "lon": hearing.lon} if hearing.lat is not None else {}
    if hearing.rssi_db is not None:
        # A louder hearing that places nothing must not erase a position
        # an earlier hearing gave.
        await session.execute(
            update(RfHeard)
            .where(
                *key,
                or_(RfHeard.best_rssi_db.is_(None), RfHeard.best_rssi_db < hearing.rssi_db),
            )
            .values(best_rssi_db=hearing.rssi_db, **placed)
        )
    if placed:
        await session.execute(update(RfHeard).where(*key, RfHeard.lat.is_(None)).values(**placed))


def credited(via: str) -> bool:
    """True when `via` names a real station, not a path alias."""
    return bool(APRS_STATION.match(via)) and not APRS_ALIAS.match(via)


def hearings(kind: str, obs: Observation) -> list[Hearing]:
    """Return what the station itself heard, from one observation.

    Every kind but `aprs` is heard directly: a receiver decodes the
    aircraft or the sensor itself. APRS is not (design 5.1):

    - A packet heard with no digipeater (`direct`) is a hearing of the
      sender, at its own position.
    - A relayed packet was heard from `via`, the last digipeater, and
      its level is that digipeater's. The sender is not credited.
    - An object's position is not where its transmitter is. Only the
      station that sent it, `via`, is credited.
    - A position blurred past `HEARD_PRECISION_M` is counted but places
      no cell.

    `via` has no position in the message. Its row stores none, and the
    heard layer takes it from the digipeater's own beacons.
    """
    if kind != "aprs":
        return [Hearing(obs.id, obs.rssi_db, obs.lat, obs.lon)]
    found: list[Hearing] = []
    is_object = bool(APRS_OBJECT.match(obs.id))
    if obs.direct is True and not is_object:
        blurred = obs.precision_m is not None and obs.precision_m > HEARD_PRECISION_M
        lat, lon = (None, None) if blurred else (obs.lat, obs.lon)
        found.append(Hearing(obs.id, obs.rssi_db, lat, lon))
    elif obs.via and obs.via != obs.id and credited(obs.via):
        found.append(Hearing(obs.via, obs.rssi_db, None, None))
    return found


def stored_meta(kind: str, obs: Observation) -> dict[str, object] | None:
    """Return the `meta` to store: the agent's, plus the contract facts.

    Every kind carries `raw` there, for the RF tab's table. APRS also
    carries how it was heard. Each is set from its contract field and
    replaces any key of that name the agent put in `meta`, so a station
    cannot pass off its own text as the frame it sent.
    """
    meta = aprs_meta(obs) if kind == "aprs" else dict(obs.meta or {})
    meta.pop("raw", None)
    if obs.raw:
        meta["raw"] = obs.raw
    return meta or None


def aprs_meta(obs: Observation) -> dict[str, object]:
    """Return the stored `meta`, with how the packet was heard added.

    The RF tab reads these to say "heard through W7MOT-3" or "blurred to
    about 2 km". They are facts from the contract fields, so they
    replace any keys of the same name the agent put in `meta`.
    """
    meta: dict[str, object] = dict(obs.meta or {})
    meta["direct"] = obs.direct is True
    for key in ("via", "precision_m"):
        meta.pop(key, None)
    if obs.via and credited(obs.via):
        meta["via"] = obs.via
    if obs.precision_m:
        meta["precision_m"] = obs.precision_m
    return meta


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


def ism_model(obs: Observation) -> str | None:
    """Return the rtl_433 model of an `ism` observation, lower case.

    Returns None when the observation is malformed: no `meta["model"]`,
    or an id that does not begin with that model and `-`. The agent
    builds the id as `<model>-<device id>`. The model is read from
    `meta` and not split out of the id, because a model name can hold
    `-` itself, such as `Acurite-Tower`. Checking the id against it
    stops a reading that names an allowed model in `meta` and carries
    another device's id.
    """
    model = (obs.meta or {}).get("model")
    if not isinstance(model, str) or not model.strip():
        return None
    model = model.strip().lower()
    if not obs.id.startswith(model + "-"):
        return None
    return model


async def store_batch(
    session: AsyncSession, batch: Batch, received: datetime, rules: Rules
) -> Tally:
    """Store one batch of observations. Returns what happened to each."""
    tally = Tally()
    if batch.kind not in STORED_KINDS:
        # A kind the contract names and this sonoran does not store yet.
        tally.kind_not_stored = len(batch.obs)
        return tally
    id_rule = THING_ID[batch.kind]
    for obs in batch.obs:
        if not id_rule.match(obs.id):
            tally.rejected += 1
            tally.reasons.append(f"not a {batch.kind} id: {obs.id!r}")
            continue
        if obs.id in rules.hidden:
            tally.hidden += 1
            continue
        if batch.kind == "ism":
            # rtl_433 decodes tyre sensors, doorbells and car keys in the
            # neighbours' houses as easily as weather stations. So this
            # fails closed: an empty allow-list stores nothing, and the
            # match is the whole model name, never a prefix (design 8).
            model = ism_model(obs)
            if model is None:
                tally.rejected += 1
                tally.reasons.append(f"an ism id without a matching meta.model: {obs.id!r}")
                continue
            if model not in rules.ism_allow:
                tally.not_allowed += 1
                continue
        heard = hearings(batch.kind, obs)
        mapped = obs
        if batch.kind == "aprs":
            # The level belongs to whatever the station decoded. Unless
            # that was the sender itself, it is not the sender's.
            sender_heard = any(h.thing_id == obs.id for h in heard)
            if not sender_heard:
                tally.relayed += 1
            mapped = obs.model_copy(update={"rssi_db": obs.rssi_db if sender_heard else None})
        mapped = mapped.model_copy(update={"meta": stored_meta(batch.kind, obs)})
        when, retimed = guarded_time(obs.t, received, rules)
        tally.retimed += int(retimed)
        # The map takes every packet, relayed or not: the position is
        # the sender's own report.
        point = _point(mapped, when, batch.station)
        await _store_track(session, batch.kind, mapped, floor_time(when, rules.bucket), point)
        for hearing in heard:
            await _store_heard(session, batch.station, batch.kind, hearing, when)
        await _store_latest(session, batch.kind, mapped, point)
        tally.stored += 1
    return tally
