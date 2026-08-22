"""The public coverage embed.

A page on somebody else's website that shows where the mesh reaches.

Everything here is off until `EMBED_ENABLED` is true, which is the same
default `STORE_TEXT_MESSAGES` takes: the private value is the safe one.

The embed is its own document. The dashboard carries `serial=(self)` so
the config checker can read a node over USB, and framing the dashboard
would take Web Serial and the whole navigation onto a third party page.

`sonoran/embed/sanitise.py` is the only place that decides what a
public viewer sees. Nothing here reaches around it.
"""

import json
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import HTMLResponse

from sonoran.api.dependencies import get_session
from sonoran.config import Settings
from sonoran.coverage import store
from sonoran.db.models import Node
from sonoran.embed.sanitise import public_nodes
from sonoran.positions import is_usable


def _require_enabled(request: Request) -> Settings:
    """Return the settings, or refuse while the embed is off.

    This is a dependency of the whole router, not a check inside each
    handler. A handler body runs after every parameter is resolved, so
    a check there would already have opened a database session for a
    request that must never have reached the database at all.
    """
    settings: Settings = request.app.state.settings
    if not settings.embed_enabled:
        raise HTTPException(status_code=404, detail="the coverage embed is not enabled")
    return settings


router = APIRouter(tags=["embed"], dependencies=[Depends(_require_enabled)])

# How long a public answer is held before the database is asked again.
#
# The embed sits on a page anybody may load, and the node list is the
# only part of it that touches the database. The tiles are files and a
# browser caches them; this must not be the one endpoint a busy page
# hammers. The sites of a mesh change over hours, not seconds.
NODE_CACHE_SECONDS = 300.0

_node_cache: tuple[float, list[dict[str, object]]] | None = None

STATIC_DIR = Path(__file__).parent.parent.parent / "web" / "static"


@router.get("/embed/coverage", include_in_schema=False)
async def embed_page(settings: Settings = Depends(_require_enabled)) -> HTMLResponse:
    """Serve the embed document."""
    html = (STATIC_DIR / "embed-coverage.html").read_text(encoding="utf-8")
    config = {
        "apiBase": settings.web_api_base_url,
        "tileUrl": settings.map_tile_url,
        "tileAttribution": settings.map_tile_attribution,
        "mapCenter": [settings.map_default_lat, settings.map_default_lon],
        "mapZoom": settings.map_default_zoom,
    }
    return HTMLResponse(html.replace("__SONORAN_EMBED_CONFIG__", json.dumps(config)))


@router.get("/api/embed/coverage")
async def embed_summary(settings: Settings = Depends(_require_enabled)) -> dict[str, object]:
    """Return what a public page needs to draw the coverage.

    A cut down manifest. The list of sites a run used, the terrain
    tiles it was missing, and how long it took are all operational
    detail that a public page has no use for.
    """
    manifest = store.read_manifest(settings)
    if manifest is None:
        return {"available": False, "presets": []}

    raw_presets = manifest.get("presets")
    presets = [
        {
            "preset": item.get("preset"),
            "label": item.get("label"),
            "sensitivity_dbm": item.get("sensitivity_dbm"),
            "node_count": item.get("node_count"),
            "usable_area_km2": item.get("usable_area_km2"),
            "data_bounds": item.get("data_bounds"),
        }
        for item in (raw_presets if isinstance(raw_presets, list) else [])
        if isinstance(item, dict)
    ]
    return {
        "available": True,
        "stamp": manifest.get("stamp"),
        "generated_at": manifest.get("generated_at"),
        "bounds": manifest.get("bounds"),
        "data_bounds": manifest.get("data_bounds"),
        "min_zoom": manifest.get("min_zoom"),
        "max_zoom": manifest.get("max_zoom"),
        "rx_height_m": manifest.get("rx_height_m"),
        "ramp_span_db": manifest.get("ramp_span_db"),
        "has_landcover": manifest.get("has_landcover"),
        "presets": presets,
    }


@router.get("/api/embed/nodes")
async def embed_nodes(
    settings: Settings = Depends(_require_enabled),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, object]]:
    """Return the infrastructure sites a public page may show.

    Routers, repeaters, and MQTT gateways only. Positions are snapped
    to a grid before they leave this process, not in the browser.

    The answer is held for a few minutes. This is the only part of the
    embed that reads the database, and the sites of a mesh change over
    hours.
    """
    global _node_cache
    now = time.monotonic()
    if _node_cache is not None and now - _node_cache[0] < NODE_CACHE_SECONDS:
        return _node_cache[1]

    rows = await session.scalars(select(Node))
    nodes = public_nodes(
        (
            (
                node.short_name,
                node.long_name,
                node.last_lat if is_usable(node.last_lat, node.last_lon) else None,
                node.last_lon if is_usable(node.last_lat, node.last_lon) else None,
                node.role,
                bool(node.is_mqtt_gateway),
            )
            for node in rows.all()
        ),
        settings.embed_position_step,
    )
    answer: list[dict[str, object]] = [
        {
            "short_name": node.short_name,
            "lat": node.latitude,
            "lon": node.longitude,
            "role": node.role,
            "is_gateway": node.is_gateway,
        }
        for node in nodes
    ]
    _node_cache = (now, answer)
    return answer
