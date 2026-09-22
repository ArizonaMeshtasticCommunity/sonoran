"""Read-only RF map endpoints. See `docs/design/rf-map.md` section 6.

Everything here is what the community's own receivers heard. Nothing is
fetched, and a thing that is not in these answers was not heard by us.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import func, select, true
from sqlalchemy.dialects.postgresql import aggregate_order_by
from sqlalchemy.ext.asyncio import AsyncSession

from sonoran.api.dependencies import get_session
from sonoran.db.models import RfHeard, RfLatest, RfSpectrum, RfStation, RfTrack
from sonoran.radio.channels import US_END_HZ, US_START_HZ, all_channels
from sonoran.rf.schema import KINDS, STATION_ID, STORED_KINDS

router = APIRouter(prefix="/api/rf", tags=["rf"])

KIND = "^(adsb|uat|aprs|sonde|ism)$"
# A station that has not sent a heartbeat for this long is shown as
# silent. The agent sends one a minute (design 3.3).
ONLINE = timedelta(minutes=5)
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


@router.get("/stations")
async def stations(session: AsyncSession = Depends(get_session)) -> list[dict[str, object]]:
    """Return every station, its rounded position, and when it last reported."""
    now = datetime.now(UTC)
    rows = (await session.scalars(select(RfStation).order_by(RfStation.station_id))).all()
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
    return [
        {
            "station": row.station_id,
            "lat": row.lat,
            "lon": row.lon,
            # The agent rounded the position by this much before sending it.
            "precision_m": row.precision_m,
            "kinds": row.kinds or [],
            "agent_version": row.agent_version,
            "last_seen": row.last_seen,
            "online": now - row.last_seen <= ONLINE,
            # Since the heartbeat before: a thinned picture says so.
            "counts": {"heard": row.heard, "sent": row.sent, "dropped": row.dropped},
            "spectrum_last": swept.get(row.station_id),
        }
        for row in rows
    ]


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
    cell_lat = func.round(RfHeard.lat / CELL_DEG) * CELL_DEG
    cell_lon = func.round(RfHeard.lon / CELL_DEG) * CELL_DEG
    rows = (
        await session.execute(
            select(
                cell_lat.label("lat"),
                cell_lon.label("lon"),
                func.max(RfHeard.best_rssi_db).label("best_rssi_db"),
                func.sum(RfHeard.heard).label("heard"),
            )
            .where(
                RfHeard.station_id == station,
                RfHeard.kind == kind,
                RfHeard.bucket >= since,
                RfHeard.lat.is_not(None),
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


@router.get("/spectrum/{station}")
async def spectrum(
    station: str,
    hours: int = Query(default=6, ge=1, le=24),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    """Return one station's minutes of the 900 MHz band, for the waterfall.

    Design 7.4. One station at a time: levels are relative to that
    station's own dongle and never compare two stations (design 3.5).

    Two levels come back per bin, because they answer two questions:

    - `p50`, the median over the minute's sweeps: the noise floor. A
      LoRa packet is a burst, and a channel is keyed for a minority of
      the time, so a burst does not move the median. This is the view
      that shows noise rather than our own traffic.
    - `p95`: the bursts on top of it, ours and anybody else's.

    A window longer than `SPECTRUM_MAX_ROWS` minutes is cut into equal
    buckets in the database, so a day is a few hundred rows and not
    1,440. In a bucket each bin keeps the median of its medians, the
    highest 95th percentile, so a burst is never averaged away, and the
    mean busy share.

    Only minutes with the station's newest bin layout are used. A change
    of sweep range starts a new picture rather than mixing two.
    """
    if not STATION_ID.fullmatch(station):
        raise HTTPException(status_code=422, detail="not a station id")
    since = datetime.now(UTC) - timedelta(hours=hours)
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
            .where(RfSpectrum.station_id == station, RfSpectrum.t >= since)
            .order_by(RfSpectrum.t.desc())
            .limit(1)
        )
    ).first()
    minutes = max(1, -(-hours * 60 // SPECTRUM_MAX_ROWS))
    if layout is None:
        return {"station": station, "hours": hours, "bucket_minutes": minutes, "rows": []}
    f_start, bin_hz, bins, gain_db, sweeps, newest = layout

    bins_of = (
        func.unnest(RfSpectrum.p50, RfSpectrum.p95, RfSpectrum.busy)
        .table_valued("p50", "p95", "busy", with_ordinality="i")
        .render_derived()
    )
    bucket = func.time_bucket(timedelta(minutes=minutes), RfSpectrum.t).label("bucket")
    per_bin = (
        select(
            bucket,
            bins_of.c.i,
            func.percentile_disc(0.5).within_group(bins_of.c.p50).label("p50"),
            func.max(bins_of.c.p95).label("p95"),
            func.round(func.avg(bins_of.c.busy)).label("busy"),
        )
        .select_from(RfSpectrum)
        .join(bins_of, true())
        .where(
            RfSpectrum.station_id == station,
            RfSpectrum.t >= since,
            RfSpectrum.f_start_hz == f_start,
            RfSpectrum.bin_hz == bin_hz,
            func.cardinality(RfSpectrum.p95) == bins,
        )
        .group_by(bucket, bins_of.c.i)
        .subquery()
    )
    rows = (
        await session.execute(
            select(
                per_bin.c.bucket,
                func.array_agg(aggregate_order_by(per_bin.c.p50, per_bin.c.i)),
                func.array_agg(aggregate_order_by(per_bin.c.p95, per_bin.c.i)),
                func.array_agg(aggregate_order_by(per_bin.c.busy, per_bin.c.i)),
            )
            .group_by(per_bin.c.bucket)
            .order_by(per_bin.c.bucket)
        )
    ).all()
    return {
        "station": station,
        "hours": hours,
        "bucket_minutes": minutes,
        "f_start_hz": f_start,
        "bin_hz": bin_hz,
        "bins": bins,
        "gain_db": gain_db,
        "sweeps_per_minute": sweeps,
        "newest": newest,
        "rows": [
            {
                "t": when,
                "p50": list(p50),
                "p95": list(p95),
                "busy": [None if b is None else int(b) for b in busy],
            }
            for when, p50, p95, busy in rows
        ],
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
