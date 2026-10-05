"""Read-only RF map endpoints. See `docs/design/rf-map.md` section 6.

Everything here is what the community's own receivers heard. Nothing is
fetched, and a thing that is not in these answers was not heard by us.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import Float, and_, case, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from sonoran.api.dependencies import get_session
from sonoran.db.models import (
    RfHeard,
    RfLatest,
    RfSource,
    RfSpectrum,
    RfSpectrumHour,
    RfStation,
    RfTrack,
)
from sonoran.radio.channels import US_END_HZ, US_START_HZ, all_channels
from sonoran.rf.schema import HEARD_PRECISION_M, KINDS, NO_SOURCE, STATION_ID, STORED_KINDS
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
    return {"known": list(KINDS), "stored": sorted(STORED_KINDS), "views": ["spectrum"]}


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


def _spectrum_rows(rows: Any, with_peak_min: bool) -> list[dict[str, object]]:
    """Rows as the page reads them. Each tuple is (t, p50, p95, busy, peak, peak_min)."""

    def ints(values: Any) -> list[int | None]:
        return [None if v is None else int(v) for v in values]

    out: list[dict[str, object]] = []
    for when, p50, p95, busy, peak, peak_min in rows:
        row: dict[str, object] = {
            "t": when,
            "p50": ints(p50),
            "p95": ints(p95),
            "busy": ints(busy),
            "peak": ints(peak),
        }
        if with_peak_min:
            # Minutes from the start of the row to each bin's loudest moment.
            row["peak_min"] = ints(peak_min)
        out.append(row)
    return out


@router.get("/spectrum/{station}")
async def spectrum(
    station: str,
    hours: int = Query(default=6, ge=1, le=168),
    start: datetime | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    """Return one station's minutes of the 900 MHz band, for the waterfall.

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

    A window longer than `SPECTRUM_MAX_ROWS` minutes is cut into equal
    buckets in the database, so a day is a few hundred rows and not
    1,440 (`rf/spectrum_sql.py`). A window longer than
    `SPECTRUM_MINUTE_HOURS` reads the hourly rollup instead, one row an
    hour, built the same way by the jobs process. It ends at the last
    hour the rollup has finished.

    With `start`, `hours` is ignored: the answer is
    `FULL_RESOLUTION_HOURS` from `start`, one row per minute. `start`
    must lie in the last `FULL_RESOLUTION_DAYS`.

    Only rows with the station's newest bin layout in the window are
    used. A change of sweep range starts a new picture rather than
    mixing two.
    """
    if not STATION_ID.fullmatch(station):
        raise HTTPException(status_code=422, detail="not a station id")
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
            session, station, start, start + timedelta(hours=FULL_RESOLUTION_HOURS), 1
        )
        return {**answer, "hours": FULL_RESOLUTION_HOURS, "start": start}
    if hours > SPECTRUM_MINUTE_HOURS:
        return {
            **await _spectrum_hours(session, station, now - timedelta(hours=hours)),
            "hours": hours,
        }
    minutes = max(1, -(-hours * 60 // SPECTRUM_MAX_ROWS))
    answer = await _spectrum_minutes(session, station, now - timedelta(hours=hours), now, minutes)
    return {**answer, "hours": hours}


async def _spectrum_minutes(
    session: AsyncSession, station: str, since: datetime, until: datetime, minutes: int
) -> dict[str, object]:
    """The waterfall from the minutes in [since, until), in rows of `minutes`."""
    window = (
        RfSpectrum.station_id == station,
        RfSpectrum.t >= since,
        RfSpectrum.t < until,
    )
    layout = (
        await session.execute(
            select(
                RfSpectrum.f_start_hz,
                RfSpectrum.bin_hz,
                func.cardinality(RfSpectrum.p95),
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
    f_start, bin_hz, bins, gain_db, sweeps, newest = layout
    rows = (
        await session.execute(
            bin_rows(
                func.time_bucket(timedelta(minutes=minutes), RfSpectrum.t),
                *window,
                RfSpectrum.f_start_hz == f_start,
                RfSpectrum.bin_hz == bin_hz,
                func.cardinality(RfSpectrum.p95) == bins,
            )
        )
    ).all()
    return {
        "station": station,
        "bucket_minutes": minutes,
        "f_start_hz": f_start,
        "bin_hz": bin_hz,
        "bins": bins,
        "gain_db": gain_db,
        "sweeps_per_minute": sweeps,
        "newest": newest,
        "rows": _spectrum_rows(
            ((t, p50, p95, busy, peak, pmin) for t, p50, p95, busy, _, peak, pmin in rows),
            with_peak_min=minutes > 1,
        ),
    }


async def _spectrum_hours(
    session: AsyncSession, station: str, since: datetime
) -> dict[str, object]:
    """The waterfall from the hourly rollup: one row per hour, oldest first."""
    layout = (
        await session.execute(
            select(
                RfSpectrumHour.f_start_hz,
                RfSpectrumHour.bin_hz,
                RfSpectrumHour.bins,
                RfSpectrumHour.gain_db,
                RfSpectrumHour.t,
            )
            .where(RfSpectrumHour.station_id == station, RfSpectrumHour.t >= since)
            .order_by(RfSpectrumHour.t.desc())
            .limit(1)
        )
    ).first()
    if layout is None:
        return {"station": station, "bucket_minutes": 60, "rows": []}
    f_start, bin_hz, bins, gain_db, newest = layout
    rows = (
        await session.execute(
            select(
                RfSpectrumHour.t,
                RfSpectrumHour.p50,
                RfSpectrumHour.p95,
                RfSpectrumHour.busy,
                RfSpectrumHour.peak,
                RfSpectrumHour.peak_min,
            )
            .where(
                RfSpectrumHour.station_id == station,
                RfSpectrumHour.t >= since,
                RfSpectrumHour.f_start_hz == f_start,
                RfSpectrumHour.bin_hz == bin_hz,
                RfSpectrumHour.bins == bins,
            )
            .order_by(RfSpectrumHour.t)
        )
    ).all()
    sweeps = await session.scalar(
        select(RfSpectrum.sweeps)
        .where(RfSpectrum.station_id == station, RfSpectrum.t >= since)
        .order_by(RfSpectrum.t.desc())
        .limit(1)
    )
    return {
        "station": station,
        "bucket_minutes": 60,
        "f_start_hz": f_start,
        "bin_hz": bin_hz,
        "bins": bins,
        "gain_db": gain_db,
        "sweeps_per_minute": sweeps,
        # The start of the newest finished hour: the window ends there.
        "newest": newest,
        "rows": _spectrum_rows(rows, with_peak_min=True),
    }


@router.get("/channels")
async def channels() -> dict[str, object]:
    """Return where each Meshtastic preset's default channel sits in the band.

    Computed the way the firmware computes it (`sonoran.radio.channels`),
    for the US region, so the waterfall's marks are never typed by hand.
    """
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
            }
            for item in all_channels()
        ],
    }
