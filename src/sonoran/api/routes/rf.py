"""Read-only RF map endpoints. See `docs/design/rf-map.md` section 6.

Everything here is what the community's own receivers heard. Nothing is
fetched, and a thing that is not in these answers was not heard by us.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from sonoran.api.dependencies import get_session
from sonoran.db.models import RfHeard, RfLatest, RfStation, RfTrack
from sonoran.rf.schema import STATION_ID

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


@router.get("/stations")
async def stations(session: AsyncSession = Depends(get_session)) -> list[dict[str, object]]:
    """Return every station, its rounded position, and when it last reported."""
    now = datetime.now(UTC)
    rows = (await session.scalars(select(RfStation).order_by(RfStation.station_id))).all()
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
    if kind not in {"adsb", "uat", "aprs", "sonde", "ism"} or thing_id in _hidden(request):
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
