"""Read-only coverage map endpoints.

These are the dashboard's. They serve every site set a run published,
including a diagnostic one, because the dashboard is the audience a
diagnostic is for. They are not the public surface and must never be
exposed to one: see `api/routes/embed.py` for the tiles a public
viewer may fetch, and `docs/API.md` 3B for the exact list of paths a
reverse proxy may open.

The coverage job writes tiles and a manifest to disk. This module serves
them. It computes nothing: a request that needed a prediction would take
seconds and could not be cached.

Tiles never change. A run writes a new directory and the index moves to
it, so a tile URL of one run always answers with the same bytes. That is
why they are served as immutable, and why the map opens fast the second
time somebody looks at it.
"""

from fastapi import APIRouter, Depends, HTTPException, Path, Request
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import Response

from sonoran.api.dependencies import get_session
from sonoran.coverage import store
from sonoran.coverage.render import TILE_SIZE
from sonoran.coverage.store import LAYER_LABELS, LAYERS
from sonoran.roles import SITE_SET_KEYS

router = APIRouter(prefix="/api/coverage", tags=["coverage"])

# The largest zoom a request may ask for.
#
# A request past the zooms a run wrote would always miss. The bound
# stops a crawler walking to zoom 22 and making a million misses.
MAX_ZOOM = 16


@router.get("")
async def coverage_summary(request: Request) -> dict[str, object]:
    """Return what the current coverage run holds.

    A deployment that has never run the job returns `available: false`.
    That is a working state, not a fault, and the page says the map has
    not been made yet.
    """
    settings = request.app.state.settings
    manifest = store.read_manifest(settings)
    if manifest is None:
        return {
            "available": False,
            "layers": [{"key": key, "label": LAYER_LABELS[key]} for key in LAYERS],
            "presets": [],
        }

    return {
        "available": True,
        "layers": [{"key": key, "label": LAYER_LABELS[key]} for key in LAYERS],
        "active_hours": settings.coverage_active_hours,
        "tile_size": TILE_SIZE,
        **manifest,
    }


@router.get("/calibration")
async def coverage_calibration(session: AsyncSession = Depends(get_session)) -> dict[str, object]:
    """Return what the mesh measured against what the model predicted.

    This is where a node that is not what its nameplate says becomes
    visible. `offset_db` is the bounded correction the map uses. A node
    with thin evidence is listed with its counts and a null offset.

    `applied` says whether the fit as a whole is trusted. A fit whose
    measurements still disagree widely describes nothing, and the map
    keeps its nameplate figures instead of moving on noise.
    """
    document = await store.read_calibration(session)
    if document is None:
        return {"available": False, "nodes": []}
    applied = store.offsets_of(document)
    nodes = document.get("nodes")
    reported_nodes: list[dict[object, object]] = []
    for item in nodes if isinstance(nodes, list) else []:
        if not isinstance(item, dict):
            continue
        node_id = item.get("node_id")
        offset = applied.get(node_id) if isinstance(node_id, str) else None
        reported_nodes.append(
            {
                **item,
                "offset_db": offset,
                "applied": isinstance(node_id, str) and node_id in applied,
            }
        )
    return {
        "available": True,
        "generated_at": document.get("generated_at"),
        "summary": document.get("summary"),
        "model_bias_db": document.get("model_bias_db"),
        "residual_spread_db": document.get("residual_spread_db"),
        "applied_count": len(applied),
        "nodes": reported_nodes,
    }


def _check_tile(layer: str, site_set: str, zoom: int, x: int, y: int) -> None:
    """Refuse a tile request that names no tile a run can hold."""
    if layer not in LAYERS:
        raise HTTPException(status_code=422, detail=f"not a coverage layer: {layer}")
    if site_set not in SITE_SET_KEYS:
        raise HTTPException(status_code=422, detail=f"not a coverage site set: {site_set}")

    # A tile index must fit the zoom it names, or the run is asked for
    # ground that does not exist.
    limit = 1 << zoom
    if x >= limit or y >= limit:
        raise HTTPException(status_code=422, detail="the tile is outside the zoom level")


def _tile_response(png: bytes | None, etag: str) -> Response:
    """Return a tile, or a 404 for ground no node reaches."""
    if png is None:
        raise HTTPException(status_code=404, detail="no coverage here")
    return Response(
        content=png,
        media_type="image/png",
        headers={
            # The run stamp is part of the URL. These bytes can never
            # change, so a browser can keep them permanently.
            "Cache-Control": "public, max-age=31536000, immutable",
            "ETag": f'"{etag}"',
        },
    )


@router.get("/tiles/{stamp}/{preset}/{site_set}/{layer}/{zoom}/{x}/{y}.png")
async def coverage_tile(
    request: Request,
    stamp: str = Path(pattern=r"^\d{8}T\d{6}Z$"),
    preset: str = Path(pattern=r"^[A-Za-z]{1,32}$"),
    site_set: str = Path(pattern=r"^[a-z_]{1,32}$"),
    layer: str = Path(pattern=r"^[a-z]{1,16}$"),
    zoom: int = Path(ge=0, le=MAX_ZOOM),
    x: int = Path(ge=0),
    y: int = Path(ge=0),
) -> Response:
    """Return one coverage tile.

    A tile that was never written is ground no node reaches. That is a
    404, which is what a map library already knows how to draw.
    """
    _check_tile(layer, site_set, zoom, x, y)
    settings = request.app.state.settings
    png = store.read_run_tile(settings, stamp, preset, site_set, layer, zoom, x, y)
    return _tile_response(png, f"{stamp}-{preset}-{site_set}-{layer}-{zoom}-{x}-{y}")


@router.get("/tiles/{stamp}/{preset}/{site_set}/{layer}/margin/{zoom}/{x}/{y}.png")
async def coverage_margin_tile(
    request: Request,
    stamp: str = Path(pattern=r"^\d{8}T\d{6}Z$"),
    preset: str = Path(pattern=r"^[A-Za-z]{1,32}$"),
    site_set: str = Path(pattern=r"^[a-z_]{1,32}$"),
    layer: str = Path(pattern=r"^[a-z]{1,16}$"),
    zoom: int = Path(ge=0, le=MAX_ZOOM),
    x: int = Path(ge=0),
    y: int = Path(ge=0),
) -> Response:
    """Return the margin tile of one coverage tile (#334).

    One grey byte for each pixel: zero for no usable coverage, and
    otherwise one more than the dB above the sensitivity. The dashboard
    colours it to draw a signal floor. See `coverage/render.py`.

    The dashboard's only. The public embed has no route to these, and
    `docs/API.md` 3B.5 does not list this path.

    A run made before the margin tiles existed has none, and answers
    404 for every one. Its manifest has no `margin_tiles`, so the page
    does not ask.
    """
    _check_tile(layer, site_set, zoom, x, y)
    settings = request.app.state.settings
    png = store.read_run_margin_tile(settings, stamp, preset, site_set, layer, zoom, x, y)
    return _tile_response(png, f"{stamp}-{preset}-{site_set}-{layer}-margin-{zoom}-{x}-{y}")
