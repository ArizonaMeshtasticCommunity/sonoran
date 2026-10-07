"""Read-only RF map endpoints. See `docs/design/rf-map.md` section 6.

Everything here is what the community's own receivers heard. Nothing is
fetched, and a thing that is not in these answers was not heard by us.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import Float, and_, case, cast, func, or_, select, tuple_
from sqlalchemy.dialects.postgresql import aggregate_order_by
from sqlalchemy.ext.asyncio import AsyncSession

from sonoran.api.dependencies import get_session
from sonoran.db.models import (
    RfCustom,
    RfHeard,
    RfHiddenMod,
    RfLatest,
    RfSource,
    RfSpectrum,
    RfSpectrumHour,
    RfStation,
    RfTrack,
    RfTrust,
)
from sonoran.radio.channels import US_END_HZ, US_START_HZ, all_channels, custom_channel
from sonoran.rf.guard import ANY_SOURCE, NEW, QUARANTINED, TRUST_NAMES
from sonoran.rf.schema import (
    HEARD_PRECISION_M,
    KINDS,
    NAME,
    NO_SOURCE,
    STATION_ID,
    STORED_KINDS,
)
from sonoran.rf.spectrum_sql import bin_rows

router = APIRouter(prefix="/api/rf", tags=["rf"])

KIND = "^(adsb|uat|aprs|sonde|ism)$"
# A station that has not sent a heartbeat for this long is shown as
# silent. The agent sends one a minute (design 3.3).
ONLINE = timedelta(minutes=5)
# A source silent for longer no longer adds its kinds to its location.
SOURCE_FRESH = timedelta(hours=24)
# The receiver layer's grid, in degrees: about 2 km in Arizona. Fine
# enough to draw where a station hears, coarse enough to send a day.
CELL_DEG = 0.02


def _hidden(request: Request) -> list[str]:
    """Things never shown, even if an older row holds them (design 8)."""
    return [item.lower() for item in request.app.state.settings.rf_hidden_ids]


def _point(row: RfLatest | RfTrack) -> dict[str, object]:
    return {
        "t": row.t,
        "lat": row.lat,
        "lon": row.lon,
        "alt_m": row.alt_m,
        "alt_ref": row.alt_ref,
        "gs_kn": row.gs_kn,
        "track_deg": row.track_deg,
        "rssi_db": row.rssi_db,
        "station": row.station_id,
    }


@router.get("/kinds")
async def kinds() -> dict[str, list[str]]:
    """Return every kind a station may send, and the ones stored today.

    The RF page draws its source list from this, so a source whose phase
    has not landed reads as "not stored yet", never as an empty sky.
    """
    return {
        "known": list(KINDS),
        "stored": sorted(STORED_KINDS),
        "views": ["spectrum", "sweeps", "custom"],
    }


def _online(last_seen: datetime | None, now: datetime) -> bool:
    return last_seen is not None and now - last_seen <= ONLINE


def _counts(row: RfStation | RfSource) -> dict[str, int | None]:
    return {"heard": row.heard, "sent": row.sent, "dropped": row.dropped}


def _sources(station: RfStation, rows: list[RfSource], now: datetime) -> list[dict[str, object]]:
    """Return a location's sources: each one that sent a heartbeat, and
    each one in the registry that has not sent one yet."""
    registered = set(station.registered_sources or [])
    out: list[dict[str, object]] = [
        {
            # None is an agent that sends no source.
            "source": None if row.source == NO_SOURCE else row.source,
            "kinds": row.kinds or [],
            "agent_version": row.agent_version,
            "last_seen": row.last_seen,
            "online": _online(row.last_seen, now),
            "counts": _counts(row),
            "registered": row.source in registered,
            # What the source says it sweeps, and how (#324). Reported by
            # the station: a claim, shown as one.
            "sweeps": row.sweeps or [],
        }
        for row in rows
    ]
    heard_from = {row.source for row in rows}
    for name in sorted(registered - heard_from):
        out.append(
            {
                "source": name,
                "kinds": [],
                "agent_version": None,
                "last_seen": None,
                "online": False,
                "counts": {"heard": None, "sent": None, "dropped": None},
                "registered": True,
                "sweeps": [],
            }
        )
    return out


def _summed(rows: list[RfSource], now: datetime) -> dict[str, int | None]:
    """The counts of a location: the sum over its sources that report now."""
    live = [row for row in rows if _online(row.last_seen, now)]
    if not live:
        return {"heard": None, "sent": None, "dropped": None}
    return {
        name: sum(getattr(row, name) or 0 for row in live) for name in ("heard", "sent", "dropped")
    }


@router.get("/stations")
async def stations(session: AsyncSession = Depends(get_session)) -> list[dict[str, object]]:
    """Return every location, its rounded position, and its sources.

    A location is one station on the map (#305). Its kinds are those of
    every source heard from in the last day, and its counts are the sum
    over the sources that report now.
    """
    now = datetime.now(UTC)
    trust = await _trust(session)
    rows = (await session.scalars(select(RfStation).order_by(RfStation.station_id))).all()
    by_station: dict[str, list[RfSource]] = {}
    for source in (
        await session.scalars(select(RfSource).order_by(RfSource.station_id, RfSource.source))
    ).all():
        by_station.setdefault(source.station_id, []).append(source)
    # The newest minute of the band each station sent in the last day.
    # A heartbeat lists the kinds a station serves, but a sweeper runs
    # beside the agent and is known by what it sends, not what it says.
    swept: dict[str, datetime] = {
        station: last
        for station, last in (
            await session.execute(
                select(RfSpectrum.station_id, func.max(RfSpectrum.t))
                .where(RfSpectrum.t >= now - timedelta(hours=24))
                .group_by(RfSpectrum.station_id)
            )
        ).all()
    }
    out: list[dict[str, object]] = []
    for row in rows:
        sources = by_station.get(row.station_id, [])
        if sources:
            fresh = [s for s in sources if now - s.last_seen <= SOURCE_FRESH]
            kinds = sorted({kind for s in fresh for kind in (s.kinds or [])})
            counts = _summed(sources, now)
        else:
            # A station whose last heartbeat came before #305.
            kinds = row.kinds or []
            counts = _counts(row)
        out.append(
            {
                "station": row.station_id,
                "display_name": row.display_name,
                "owner": row.owner,
                "registered": row.registry_at is not None,
                "lat": row.lat,
                "lon": row.lon,
                # The agent rounded the position by this much before sending it.
                "precision_m": row.precision_m,
                "kinds": kinds,
                "agent_version": row.agent_version,
                "last_seen": row.last_seen,
                "online": _online(row.last_seen, now),
                # Since the heartbeat before: a thinned picture says so.
                "counts": counts,
                "spectrum_last": swept.get(row.station_id),
                "sources": _sources(row, sources, now),
                # Set by an operator, never by the station (#324).
                "trust": TRUST_NAMES[trust.get((row.station_id, ANY_SOURCE), NEW)],
            }
        )
    return out


async def _trust(session: AsyncSession) -> dict[tuple[str, str], int]:
    """Every level an operator set: (station, source or `*`) -> level."""
    rows = (await session.execute(select(RfTrust.station_id, RfTrust.source, RfTrust.trust))).all()
    return {(station, source): int(level) for station, source, level in rows}


# The most custom points sent at once. The page clusters past its own cap.
CUSTOM_MAX = 5000


@router.get("/custom")
async def custom(
    response: Response,
    minutes: int = Query(default=60, ge=1, le=1440),
    station: str | None = Query(default=None, pattern=STATION_ID.pattern),
    mod: str | None = Query(default=None, pattern=NAME.pattern),
    limit: int = Query(default=2000, ge=1, le=CUSTOM_MAX),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, object]]:
    """Return the newest point of each thing members' mods heard (#324).

    Every point is the claim of one station's mod, unverified, and never
    part of a shared layer. A mod an operator hid, and every mod of a
    quarantined station or source, is left out.

    `placement` says where a point may be drawn: `reported`, at the
    position the mod sent; `heard_here`, at the station's rounded
    position, given here with its rounding; `none`, the table only.
    `t` is the mod's time after the clock guard, `sent_t` the time it
    sent, and `received_at` ours, so a wrong clock shows.

    Capped by `limit`; the count of the whole window is in
    `X-Total-Count`.
    """
    since = datetime.now(UTC) - timedelta(minutes=minutes)
    where: list[Any] = [RfCustom.t >= since]
    if station:
        where.append(RfCustom.station_id == station)
    if mod:
        where.append(RfCustom.mod == mod)
    hidden = (await session.execute(select(RfHiddenMod.station_id, RfHiddenMod.mod))).all()
    if hidden:
        where.append(tuple_(RfCustom.station_id, RfCustom.mod).not_in([tuple(h) for h in hidden]))
    levels = await _trust(session)
    quarantined = [key for key, level in levels.items() if level == QUARANTINED]
    stations_out = [name for name, source in quarantined if source == ANY_SOURCE]
    sources_out = [(name, source) for name, source in quarantined if source != ANY_SOURCE]
    if stations_out:
        where.append(RfCustom.station_id.not_in(stations_out))
    if sources_out:
        where.append(tuple_(RfCustom.station_id, RfCustom.source).not_in(sources_out))
    newest = (
        select(RfCustom)
        .where(*where)
        .distinct(RfCustom.station_id, RfCustom.mod, RfCustom.thing_id)
        .order_by(RfCustom.station_id, RfCustom.mod, RfCustom.thing_id, RfCustom.t.desc())
        .subquery()
    )
    total = await session.scalar(select(func.count()).select_from(newest))
    rows = (
        await session.execute(
            select(
                newest,
                RfStation.lat.label("station_lat"),
                RfStation.lon.label("station_lon"),
                RfStation.precision_m.label("station_precision_m"),
            )
            .outerjoin(RfStation, RfStation.station_id == newest.c.station_id)
            .order_by(newest.c.t.desc())
            .limit(limit)
        )
    ).all()
    response.headers["X-Total-Count"] = str(total or 0)
    out: list[dict[str, object]] = []
    for row in rows:
        # By name: a Row's `t` is the Row itself, as a tuple.
        item = row._mapping
        here = item["placement"] == "heard_here"
        out.append(
            {
                "station": item["station_id"],
                "source": None if item["source"] == NO_SOURCE else item["source"],
                "mod": item["mod"],
                "id": item["thing_id"],
                "t": item["t"],
                "sent_t": item["sent_t"],
                "received_at": item["received_at"],
                "placement": item["placement"],
                "lat": item["station_lat"] if here else item["lat"],
                "lon": item["station_lon"] if here else item["lon"],
                "precision_m": item["station_precision_m"] if here else None,
                "meta": item["meta"] or {},
            }
        )
    return out


@router.get("/latest")
async def latest(
    request: Request,
    response: Response,
    kind: str | None = Query(default=None, pattern=KIND),
    minutes: int = Query(default=5, ge=1, le=60),
    limit: int = Query(default=2000, ge=1, le=5000),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, object]]:
    """Return the newest point of everything heard in the window.

    Capped by `limit`; the count of the whole window is in
    `X-Total-Count`, so a capped answer never reads as a quiet sky.
    """
    since = datetime.now(UTC) - timedelta(minutes=minutes)
    where = [RfLatest.t >= since]
    if kind:
        where.append(RfLatest.kind == kind)
    hidden = _hidden(request)
    if hidden:
        where.append(RfLatest.thing_id.not_in(hidden))
    total = await session.scalar(select(func.count()).select_from(RfLatest).where(*where))
    rows = (
        await session.scalars(
            select(RfLatest).where(*where).order_by(RfLatest.t.desc()).limit(limit)
        )
    ).all()
    response.headers["X-Total-Count"] = str(total or 0)
    return [
        {"kind": row.kind, "id": row.thing_id, **_point(row), "meta": row.meta or {}}
        for row in rows
    ]


@router.get("/track/{kind}/{thing_id}")
async def track(
    request: Request,
    kind: str,
    thing_id: str,
    hours: int = Query(default=1, ge=1, le=48),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    """Return one thing's track over the last hours, oldest first."""
    thing_id = thing_id.lower()
    if kind not in KINDS or thing_id in _hidden(request):
        raise HTTPException(status_code=404, detail="nothing heard")
    since = datetime.now(UTC) - timedelta(hours=hours)
    rows = (
        await session.scalars(
            select(RfTrack)
            .where(RfTrack.kind == kind, RfTrack.thing_id == thing_id, RfTrack.bucket >= since)
            .order_by(RfTrack.bucket.asc())
        )
    ).all()
    return {"kind": kind, "id": thing_id, "hours": hours, "points": [_point(r) for r in rows]}


@router.get("/heard/{station}")
async def heard(
    station: str,
    kind: str = Query(default="adsb", pattern=KIND),
    hours: int = Query(default=24, ge=1, le=336),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    """Return where one station has heard things, on a grid of about 2 km.

    Measured, not modelled: each cell is a place a thing was when this
    station heard it, with the best level and how many hearings. The
    receiver layer is drawn from it (design 7.2).
    """
    if not STATION_ID.match(station):
        raise HTTPException(status_code=422, detail="not a station id")
    since = datetime.now(UTC) - timedelta(hours=hours)
    # A hearing with no position of its own is a digipeater named in an
    # APRS path (design 5.1). It is placed where that station's own
    # beacons put it, unless those beacons blur it past a cell.
    own_precision = cast(RfLatest.meta["precision_m"].astext, Float)
    placeable = or_(own_precision.is_(None), own_precision <= HEARD_PRECISION_M)
    lat = case((RfHeard.lat.is_not(None), RfHeard.lat), (placeable, RfLatest.lat))
    lon = case((RfHeard.lat.is_not(None), RfHeard.lon), (placeable, RfLatest.lon))
    cell_lat = func.round(lat / CELL_DEG) * CELL_DEG
    cell_lon = func.round(lon / CELL_DEG) * CELL_DEG
    rows = (
        await session.execute(
            select(
                cell_lat.label("lat"),
                cell_lon.label("lon"),
                func.max(RfHeard.best_rssi_db).label("best_rssi_db"),
                func.sum(RfHeard.heard).label("heard"),
            )
            .select_from(RfHeard)
            .outerjoin(
                RfLatest,
                and_(RfLatest.kind == RfHeard.kind, RfLatest.thing_id == RfHeard.thing_id),
            )
            .where(
                RfHeard.station_id == station,
                RfHeard.kind == kind,
                RfHeard.bucket >= since,
                lat.is_not(None),
            )
            .group_by(cell_lat, cell_lon)
        )
    ).all()
    return {
        "station": station,
        "kind": kind,
        "hours": hours,
        "cell_deg": CELL_DEG,
        "cells": [
            {
                "lat": round(float(row.lat), 4),
                "lon": round(float(row.lon), 4),
                "best_rssi_db": None if row.best_rssi_db is None else float(row.best_rssi_db),
                "heard": int(row.heard or 0),
            }
            for row in rows
        ],
    }


# The most rows a waterfall is sent. Longer windows are bucketed to fit.
SPECTRUM_MAX_ROWS = 240


# Windows longer than this read the hourly rollup (`rf_spectrum_hour`),
# one row an hour, instead of every minute.
SPECTRUM_MINUTE_HOURS = 24
# Full resolution: one row per minute, for a span this long, starting
# anywhere in the last `FULL_RESOLUTION_DAYS`. Short enough to stay cheap
# at any bin width; long enough to see a transmission come and go.
FULL_RESOLUTION_HOURS = 2
FULL_RESOLUTION_DAYS = 3


# `time_bucket`'s origin for intervals shorter than a month, so the rows
# filled in here start where the database's buckets start.
BUCKET_ORIGIN = datetime(2000, 1, 3, tzinfo=UTC)
# A range, as the page names it: `source:f_start_hz:bin_hz:bins`. The
# source is `-` for an agent that sends none (`NO_SOURCE`).
RANGE_ID = r"^(?:-|[a-z0-9][a-z0-9-]{0,15}):[0-9]{1,10}:[0-9]{1,8}:[0-9]{1,4}$"


@dataclass(frozen=True)
class SweptRange:
    """One range of one station: what a waterfall shows (#324)."""

    source: str
    f_start_hz: int
    bin_hz: int
    bins: int

    @classmethod
    def parse(cls, text: str) -> SweptRange:
        source, f_start, bin_hz, bins = text.split(":")
        return cls(source, int(f_start), int(bin_hz), int(bins))

    @property
    def id(self) -> str:
        return f"{self.source}:{self.f_start_hz}:{self.bin_hz}:{self.bins}"

    def describe(self, name: str | None = None) -> dict[str, object]:
        return {
            "id": self.id,
            # None is an agent that sends no source.
            "source": None if self.source == NO_SOURCE else self.source,
            "name": name,
            "f_start_hz": self.f_start_hz,
            "f_end_hz": self.f_start_hz + self.bins * self.bin_hz,
            "bin_hz": self.bin_hz,
            "bins": self.bins,
        }


def _ints(values: Any) -> list[int | None]:
    return [None if v is None else int(v) for v in values]


def _bucket_start(when: datetime, step: timedelta) -> datetime:
    """The start of the `time_bucket` that `when` falls in."""
    return BUCKET_ORIGIN + ((when - BUCKET_ORIGIN) // step) * step


def _filled(
    rows: dict[datetime, dict[str, object]], first: datetime, until: datetime, step: timedelta
) -> list[dict[str, object]]:
    """Every row from `first` until `until`, oldest first.

    A row with no minute of the range is sent as `{"t", "minutes": 0}`,
    so the page draws it as "not swept" and never closes the gap. A
    dongle that takes turns between ranges sweeps each one only part of
    the time; a burst while it was elsewhere was not heard, and a quiet
    row would say it was (#324).
    """
    out: list[dict[str, object]] = []
    when = first
    while when < until:
        out.append(rows.get(when) or {"t": when, "minutes": 0})
        when += step
    return out


def _spectrum_rows(rows: Any, with_peak_min: bool) -> dict[datetime, dict[str, object]]:
    """Rows as the page reads them, by start time. Each tuple is
    (t, p50, p95, busy, minutes, peak, peak_min)."""
    out: dict[datetime, dict[str, object]] = {}
    for when, p50, p95, busy, minutes, peak, peak_min in rows:
        row: dict[str, object] = {
            "t": when,
            "minutes": int(minutes),
            "p50": _ints(p50),
            "p95": _ints(p95),
            "busy": _ints(busy),
            "peak": _ints(peak),
        }
        if with_peak_min:
            # Minutes from the start of the row to each bin's loudest moment.
            row["peak_min"] = _ints(peak_min)
        out[when] = row
    return out


@router.get("/spectrum/{station}/ranges")
async def spectrum_ranges(
    station: str,
    days: int = Query(default=7, ge=1, le=14),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    """Return every range a station swept in the last days, newest first.

    The waterfall's picker reads this. A station with two dongles, or
    one that takes turns, has more than one (#324).
    """
    if not STATION_ID.fullmatch(station):
        raise HTTPException(status_code=422, detail="not a station id")
    since = datetime.now(UTC) - timedelta(days=days)
    rows = (
        await session.execute(
            select(
                RfSpectrum.source,
                RfSpectrum.f_start_hz,
                RfSpectrum.bin_hz,
                RfSpectrum.bins,
                func.max(RfSpectrum.name),
                func.max(RfSpectrum.t),
                func.count(),
            )
            .where(RfSpectrum.station_id == station, RfSpectrum.t >= since)
            .group_by(RfSpectrum.source, RfSpectrum.f_start_hz, RfSpectrum.bin_hz, RfSpectrum.bins)
            .order_by(func.max(RfSpectrum.t).desc())
        )
    ).all()
    return {
        "station": station,
        "days": days,
        "ranges": [
            {
                **SweptRange(source, f_start, bin_hz, bins).describe(name),
                "newest": newest,
                "minutes": int(minutes),
            }
            for source, f_start, bin_hz, bins, name, newest, minutes in rows
        ],
    }


@router.get("/spectrum/{station}")
async def spectrum(
    station: str,
    hours: int = Query(default=6, ge=1, le=168),
    start: datetime | None = Query(default=None),
    range_id: str | None = Query(default=None, alias="range", pattern=RANGE_ID),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    """Return one station's minutes of one swept range, for the waterfall.

    Design 7.4. One station at a time: levels are relative to that
    station's own dongle and never compare two stations (design 3.5).

    Per bin, each row has:

    - `p50`, the median over the minute's sweeps: the noise floor. A
      LoRa packet is a burst, and a channel is keyed for a minority of
      the time, so a burst does not move the median. This is the view
      that shows noise rather than our own traffic.
    - `p95`: the bursts on top of it, ours and anybody else's.
    - `peak`: the loudest single moment, and, for a row longer than a
      minute, `peak_min`, how many minutes into the row it happened.
    - `busy`: the share of sweeps the bin stood 6 dB above its median.

    Each row also has `minutes`, how many minutes of the range it holds.
    A row with none is not swept: it carries no levels (`_filled`).

    A window longer than `SPECTRUM_MAX_ROWS` minutes is cut into equal
    buckets in the database, so a day is a few hundred rows and not
    1,440 (`rf/spectrum_sql.py`). A window longer than
    `SPECTRUM_MINUTE_HOURS` reads the hourly rollup instead, one row an
    hour, built the same way by the jobs process. It ends at the last
    hour the rollup has finished.

    With `start`, `hours` is ignored: the answer is
    `FULL_RESOLUTION_HOURS` from `start`, one row per minute. `start`
    must lie in the last `FULL_RESOLUTION_DAYS`.

    `range` picks one of the station's ranges, as
    `/api/rf/spectrum/{station}/ranges` names it. Without it, the range
    of the newest minute in the window is used. Two ranges are never
    mixed in one picture.
    """
    if not STATION_ID.fullmatch(station):
        raise HTTPException(status_code=422, detail="not a station id")
    chosen = SweptRange.parse(range_id) if range_id else None
    now = datetime.now(UTC)
    if start is not None:
        if start.tzinfo is None:
            raise HTTPException(status_code=422, detail="start needs a time zone")
        if not now - timedelta(days=FULL_RESOLUTION_DAYS) <= start <= now:
            raise HTTPException(
                status_code=422,
                detail=f"start must lie in the last {FULL_RESOLUTION_DAYS} days",
            )
        answer = await _spectrum_minutes(
            session, station, chosen, start, start + timedelta(hours=FULL_RESOLUTION_HOURS), 1
        )
        return {**answer, "hours": FULL_RESOLUTION_HOURS, "start": start}
    if hours > SPECTRUM_MINUTE_HOURS:
        return {
            **await _spectrum_hours(session, station, chosen, now - timedelta(hours=hours)),
            "hours": hours,
        }
    minutes = max(1, -(-hours * 60 // SPECTRUM_MAX_ROWS))
    answer = await _spectrum_minutes(
        session, station, chosen, now - timedelta(hours=hours), now, minutes
    )
    return {**answer, "hours": hours}


def _in_range(model: type[RfSpectrum] | type[RfSpectrumHour], chosen: SweptRange) -> list[Any]:
    return [
        model.source == chosen.source,
        model.f_start_hz == chosen.f_start_hz,
        model.bin_hz == chosen.bin_hz,
        model.bins == chosen.bins,
    ]


async def _spectrum_minutes(
    session: AsyncSession,
    station: str,
    chosen: SweptRange | None,
    since: datetime,
    until: datetime,
    minutes: int,
) -> dict[str, object]:
    """The waterfall from the minutes in [since, until), in rows of `minutes`."""
    window = [RfSpectrum.station_id == station, RfSpectrum.t >= since, RfSpectrum.t < until]
    if chosen is not None:
        window += _in_range(RfSpectrum, chosen)
    layout = (
        await session.execute(
            select(
                RfSpectrum.source,
                RfSpectrum.f_start_hz,
                RfSpectrum.bin_hz,
                RfSpectrum.bins,
                RfSpectrum.name,
                RfSpectrum.gain_db,
                RfSpectrum.sweeps,
                RfSpectrum.t,
            )
            .where(*window)
            .order_by(RfSpectrum.t.desc())
            .limit(1)
        )
    ).first()
    if layout is None:
        return {"station": station, "bucket_minutes": minutes, "rows": []}
    source, f_start, bin_hz, bins, name, gain_db, sweeps, newest = layout
    swept = SweptRange(source, f_start, bin_hz, bins)
    step = timedelta(minutes=minutes)
    rows = (
        await session.execute(
            bin_rows(
                func.time_bucket(step, RfSpectrum.t),
                *window[:3],
                *_in_range(RfSpectrum, swept),
            )
        )
    ).all()
    return {
        "station": station,
        "range": swept.describe(name),
        "bucket_minutes": minutes,
        "f_start_hz": f_start,
        "bin_hz": bin_hz,
        "bins": bins,
        "gain_db": gain_db,
        "sweeps_per_minute": sweeps,
        "newest": newest,
        "rows": _filled(
            _spectrum_rows(rows, with_peak_min=minutes > 1),
            _bucket_start(since, step),
            until,
            step,
        ),
    }


async def _spectrum_hours(
    session: AsyncSession, station: str, chosen: SweptRange | None, since: datetime
) -> dict[str, object]:
    """The waterfall from the hourly rollup: one row per hour, oldest first."""
    window = [RfSpectrumHour.station_id == station, RfSpectrumHour.t >= since]
    if chosen is not None:
        window += _in_range(RfSpectrumHour, chosen)
    layout = (
        await session.execute(
            select(
                RfSpectrumHour.source,
                RfSpectrumHour.f_start_hz,
                RfSpectrumHour.bin_hz,
                RfSpectrumHour.bins,
                RfSpectrumHour.gain_db,
                RfSpectrumHour.t,
            )
            .where(*window)
            .order_by(RfSpectrumHour.t.desc())
            .limit(1)
        )
    ).first()
    if layout is None:
        return {"station": station, "bucket_minutes": 60, "rows": []}
    source, f_start, bin_hz, bins, gain_db, newest = layout
    swept = SweptRange(source, f_start, bin_hz, bins)
    rows = (
        await session.execute(
            select(
                RfSpectrumHour.t,
                RfSpectrumHour.p50,
                RfSpectrumHour.p95,
                RfSpectrumHour.busy,
                RfSpectrumHour.minutes,
                RfSpectrumHour.peak,
                RfSpectrumHour.peak_min,
            )
            .where(*window[:2], *_in_range(RfSpectrumHour, swept))
            .order_by(RfSpectrumHour.t)
        )
    ).all()
    latest = (
        await session.execute(
            select(RfSpectrum.sweeps, RfSpectrum.name)
            .where(
                RfSpectrum.station_id == station,
                RfSpectrum.t >= since,
                *_in_range(RfSpectrum, swept),
            )
            .order_by(RfSpectrum.t.desc())
            .limit(1)
        )
    ).first()
    sweeps, name = latest if latest is not None else (None, None)
    hour = timedelta(hours=1)
    return {
        "station": station,
        "range": swept.describe(name),
        "bucket_minutes": 60,
        "f_start_hz": f_start,
        "bin_hz": bin_hz,
        "bins": bins,
        "gain_db": gain_db,
        "sweeps_per_minute": sweeps,
        # The start of the newest finished hour: the window ends there.
        "newest": newest,
        "rows": _filled(
            _spectrum_rows(rows, with_peak_min=True),
            _bucket_start(since, hour),
            newest + hour,
            hour,
        ),
    }


@router.get("/sweeps")
async def sweeps(
    hours: int = Query(default=24, ge=1, le=336),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    """Return every range any station swept in the window, and how.

    The "what is being swept" chart reads this (#324). Each range is what
    a station measured. `reported` is what its source said it runs, when
    it said so: the tool, the gain and the exact command. That is a
    claim by the station, shown as one. A range a source reports and has
    sent no minute of is listed with `minutes: 0`.
    """
    now = datetime.now(UTC)
    since = now - timedelta(hours=hours)
    measured = (
        await session.execute(
            select(
                RfSpectrum.station_id,
                RfSpectrum.source,
                RfSpectrum.f_start_hz,
                RfSpectrum.bin_hz,
                RfSpectrum.bins,
                func.max(RfSpectrum.name),
                func.max(RfSpectrum.t),
                func.count(),
                func.array_agg(aggregate_order_by(RfSpectrum.gain_db, RfSpectrum.t.desc()))[1],
            )
            .where(RfSpectrum.t >= since)
            .group_by(
                RfSpectrum.station_id,
                RfSpectrum.source,
                RfSpectrum.f_start_hz,
                RfSpectrum.bin_hz,
                RfSpectrum.bins,
            )
        )
    ).all()
    names = {
        row.station_id: row.display_name for row in (await session.scalars(select(RfStation))).all()
    }
    reports: dict[tuple[str, str], list[dict[str, Any]]] = {
        (row.station_id, row.source): list(row.sweeps or [])
        for row in (
            await session.scalars(
                select(RfSource).where(
                    RfSource.sweeps.is_not(None), RfSource.last_seen >= now - SOURCE_FRESH
                )
            )
        ).all()
    }
    used: set[tuple[str, str, int]] = set()
    out: list[dict[str, object]] = []
    for station, source, f_start, bin_hz, bins, name, newest, minutes, gain in measured:
        found = None
        for index, report in enumerate(reports.get((station, source), [])):
            if report.get("f_start_hz") == f_start and report.get("bin_hz") == bin_hz:
                found = report
                used.add((station, source, index))
                break
        out.append(
            {
                "station": station,
                "display_name": names.get(station),
                **SweptRange(source, f_start, bin_hz, bins).describe(name),
                "gain_db": gain,
                "newest": newest,
                "minutes": int(minutes),
                "reported": found,
            }
        )
    for (station, source), items in reports.items():
        for index, report in enumerate(items):
            if (station, source, index) in used:
                continue
            f_start, f_end, bin_hz = report["f_start_hz"], report["f_end_hz"], report["bin_hz"]
            out.append(
                {
                    "station": station,
                    "display_name": names.get(station),
                    "id": None,
                    "source": None if source == NO_SOURCE else source,
                    "name": report.get("name"),
                    "f_start_hz": f_start,
                    "f_end_hz": f_end,
                    "bin_hz": bin_hz,
                    "bins": None,
                    "gain_db": report.get("gain_db"),
                    "newest": None,
                    "minutes": 0,
                    "reported": report,
                }
            )
    # Low to high, as the chart draws them.
    order = sorted(range(len(out)), key=lambda i: (str(out[i]["f_start_hz"]).zfill(10), i))
    return {"hours": hours, "ranges": [out[i] for i in order]}


@router.get("/channels")
async def channels(request: Request) -> dict[str, object]:
    """Return where each Meshtastic preset's default channel sits in the band,
    and every channel this mesh set itself (`RF_CUSTOM_CHANNELS`).

    Computed the way the firmware computes it (`sonoran.radio.channels`),
    for the US region, so the waterfall's marks are never typed by hand.
    """
    custom = [custom_channel(spec) for spec in request.app.state.settings.rf_custom_channels]
    return {
        "region": "US",
        "start_hz": US_START_HZ,
        "end_hz": US_END_HZ,
        "channels": [
            {
                "name": item.name,
                "label": item.label,
                "bandwidth_hz": item.bandwidth_hz,
                "slot": item.slot,
                "centre_hz": item.centre_hz,
                "low_hz": item.low_hz,
                "high_hz": item.high_hz,
                "custom": item.custom,
            }
            for item in sorted([*all_channels(), *custom], key=lambda c: c.centre_hz)
        ],
    }
