"""The public coverage embed.

A page on somebody else's website that shows where the mesh reaches.

Everything here is off until `EMBED_ENABLED` is true, which is the same
default `STORE_TEXT_MESSAGES` takes: the private value is the safe one.

The embed is its own document. The dashboard carries `serial=(self)` so
the config checker can read a node over USB, and framing the dashboard
would take Web Serial and the whole navigation onto a third party page.

`sonoran/embed/sanitise.py` is the only place that decides what a
public viewer sees. Nothing here reaches around it.

That claim used to hold for the JSON and not for the pixels. The embed
drew its tiles from `/api/coverage/tiles`, which is the dashboard's
route: it takes the site set from the path and serves whatever a run
wrote, whatever the run was. Turning the embed on meant opening that
path at the proxy, and one path segment then fetched the client map of
the same run, whose footprints are centred on people's houses. A
diagnostic run written under a directory named `infrastructure` was
reachable the same way, behind nothing but a guessable stamp.

So the public tiles are served from here, on this router, under the
same `_require_enabled` dependency as everything else. The site set is
not in the URL at all, the stamp is the published run, and a
diagnostic run is refused before a handler body runs. See `AGENTS.md`
9.25 and 9.27, and `docs/API.md` 3B for the paths a proxy may open.
"""

import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi import Path as PathParam
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import HTMLResponse, Response

from sonoran.api.dependencies import get_session
from sonoran.api.html import as_script_json

# One bound on the zoom a tile request may name, shared with the
# dashboard route. Two copies would drift, and the lower one would
# then be the only one anybody tested.
from sonoran.api.routes.coverage import MAX_ZOOM
from sonoran.config import Settings
from sonoran.coverage import store
from sonoran.coverage.store import LAYERS
from sonoran.db.models import Node
from sonoran.embed.sanitise import public_nodes
from sonoran.positions import is_usable
from sonoran.roles import SITE_SET_INFRASTRUCTURE


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

# And the same for the manifest.
#
# It is a file on disk, read and parsed inside the event loop, and it
# carries up to `MANIFEST_NODE_LIMIT` site records for each preset. The
# node list below was given a hold for exactly this reason; this
# endpoint, which every embed load hits first, was not.
SUMMARY_CACHE_SECONDS = 30.0

_node_cache: tuple[float, list[dict[str, object]]] | None = None
_summary_cache: tuple[float, dict[str, object]] | None = None

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
    return HTMLResponse(html.replace("__SONORAN_EMBED_CONFIG__", as_script_json(config)))


@router.get("/api/embed/coverage")
async def embed_summary(settings: Settings = Depends(_require_enabled)) -> dict[str, object]:
    """Return what a public page needs to draw the coverage.

    A cut down manifest. The list of sites a run used, the terrain
    tiles it was missing, and how long it took are all operational
    detail that a public page has no use for.
    """
    global _summary_cache
    now = time.monotonic()
    if _summary_cache is not None and now - _summary_cache[0] < SUMMARY_CACHE_SECONDS:
        return _summary_cache[1]

    manifest = store.read_manifest(settings)
    if manifest is None:
        return {"available": False, "presets": []}

    # A diagnostic run does not reach a public page at all.
    #
    # Labelling it is not enough here, and the reason is not honesty.
    # A run with `COVERAGE_SITE_ROLES=ALL` predicts from every client
    # node, and a client node is usually somebody's house. Each one
    # then draws a footprint centred on it. The markers are already
    # held back by `embed/sanitise.py`, but a footprint has a centre,
    # and a stranger reading the tiles can find it.
    #
    # The dashboard shows the run with a notice on it, because that is
    # the audience the diagnostic is for. The public page says there is
    # no map, which is true: what exists is not one.
    if manifest.get("is_diagnostic"):
        withheld: dict[str, object] = {
            "available": False,
            "presets": [],
            "reason": "diagnostic",
        }
        _summary_cache = (now, withheld)
        return withheld

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
    answer: dict[str, object] = {
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
        # Always false here: a diagnostic run returned above. It is
        # sent anyway so the page has one thing to read rather than
        # inferring the state from a missing key.
        "is_diagnostic": False,
        "presets": presets,
    }
    _summary_cache = (now, answer)
    return answer


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


# --- the public tiles --------------------------------------------------
#
# The pixels of the public map. `embed/sanitise.py` decides what a
# public viewer sees, and these are the part of that answer a browser
# fetches by the thousand, so every rule about them is here and none of
# it is in the browser.
#
# Three things are held away from the URL, and each one was reachable
# through `/api/coverage/tiles` before this route existed:
#
# 1. The site set. It is not a parameter. A public viewer cannot name
#    `extended`, because there is nowhere to write it. The run publishes
#    that map beside this one and a client node is usually somebody's
#    house. See `AGENTS.md` 9.27.
# 2. The run. The stamp in the URL is a cache key, not a lookup: it must
#    be the run that is published now, and the bytes come from that run.
#    An older or guessed stamp answers 404.
# 3. A diagnostic run. `_require_published_map` refuses one for the
#    whole router, so no handler body runs and no tile is read. This is
#    `AGENTS.md` 9.16.3 one level down: a route that must refuse cannot
#    check inside the handler.


# What the gate decided, for one run of one cache directory.
#
# The gate reads the manifest, which is parsed in the event loop and
# carries up to `MANIFEST_NODE_LIMIT` site records for each preset. A
# map view fetches tiles by the dozen and each one asks this question,
# so the answer is kept.
#
# It is keyed on the stamp rather than held for a while, because the
# stamp changes exactly when the answer can change, and the index file
# it is read from is thirty bytes. A hold on a clock would be either
# long enough to serve a run that has been withdrawn or short enough to
# be no hold at all.
_publishable: tuple[str, str, bool] | None = None


def _published_stamp(settings: Settings) -> str | None:
    """Return the run a public viewer may draw, or None.

    None for a deployment that has never run the job, and None for a
    run that predicted from anything but infrastructure roles. The
    second is the one that matters: such a run draws a footprint around
    every client node it was given, and a footprint has a centre.

    The manifest flag is what is read, never a setting.
    `COVERAGE_SITE_ROLES` is not consulted here for the same reason
    `embed/sanitise.py` takes no settings argument: one environment
    variable must not be able to widen a public map. See `AGENTS.md`
    9.25.
    """
    global _publishable
    stamp = store.current_stamp(settings)
    if stamp is None:
        return None
    root = str(settings.coverage_cache_dir)
    if _publishable is not None and _publishable[0] == root and _publishable[1] == stamp:
        return stamp if _publishable[2] else None
    manifest = store.read_manifest(settings)
    public = manifest is not None and not manifest.get("is_diagnostic")
    _publishable = (root, stamp, public)
    return stamp if public else None


def _require_published_map(settings: Settings = Depends(_require_enabled)) -> str:
    """Return the published run, or refuse.

    A dependency of the tile router rather than a check in the handler,
    for the reason `_require_enabled` is one: the refusal has to happen
    before anything resolves a parameter or reads a file. See
    `AGENTS.md` 9.16.3.
    """
    stamp = _published_stamp(settings)
    if stamp is None:
        raise HTTPException(status_code=404, detail="no coverage map is published here")
    return stamp


tile_router = APIRouter(tags=["embed"], dependencies=[Depends(_require_published_map)])


@tile_router.get("/api/embed/tiles/{stamp}/{preset}/{layer}/{zoom}/{x}/{y}.png")
async def embed_tile(
    stamp: str = PathParam(pattern=r"^\d{8}T\d{6}Z$"),
    preset: str = PathParam(pattern=r"^[A-Za-z]{1,32}$"),
    layer: str = PathParam(pattern=r"^[a-z]{1,16}$"),
    zoom: int = PathParam(ge=0, le=MAX_ZOOM),
    x: int = PathParam(ge=0),
    y: int = PathParam(ge=0),
    settings: Settings = Depends(_require_enabled),
    published: str = Depends(_require_published_map),
) -> Response:
    """Return one tile of the public coverage map.

    The infrastructure map of the published run, and nothing else.

    A tile that was never written is ground no node reaches. That is a
    404, which is what a map library already knows how to draw.
    """
    if layer not in LAYERS:
        raise HTTPException(status_code=422, detail=f"not a coverage layer: {layer}")

    # A tile index must fit the zoom it names, or the run is asked for
    # ground that does not exist.
    limit = 1 << zoom
    if x >= limit or y >= limit:
        raise HTTPException(status_code=422, detail="the tile is outside the zoom level")

    # The stamp is in the URL so a browser can cache a tile for ever,
    # and it is checked rather than used. A run that is no longer the
    # published one is not a run this page may draw.
    if stamp != published:
        raise HTTPException(status_code=404, detail="that is not the published coverage run")

    png = store.read_run_tile(
        settings, published, preset, SITE_SET_INFRASTRUCTURE, layer, zoom, x, y
    )
    if png is None:
        raise HTTPException(status_code=404, detail="no coverage here")

    return Response(
        content=png,
        media_type="image/png",
        headers={
            # The run stamp is part of the URL, and a stamp names one
            # run for ever. These bytes can never change.
            "Cache-Control": "public, max-age=31536000, immutable",
            "ETag": f'"{stamp}-{preset}-{SITE_SET_INFRASTRUCTURE}-{layer}-{zoom}-{x}-{y}"',
        },
    )


# On the embed router, so `_require_enabled` applies to the tiles as
# well. A public tile route that the embed switch does not reach is the
# defect this module's docstring is about.
router.include_router(tile_router)
