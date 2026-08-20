"""Read-only coverage map endpoints.

The coverage job writes tiles and a manifest to disk. This module serves
them. It computes nothing: a request that needed a prediction would take
seconds and could not be cached.

Tiles never change. A run writes a new directory and the index moves to
it, so a tile URL of one run always answers with the same bytes. That is
why they are served as immutable, and why the map opens fast the second
time somebody looks at it.
"""

from fastapi import APIRouter, HTTPException, Path, Request
from starlette.responses import Response

from sonoran.coverage import store
from sonoran.coverage.render import TILE_SIZE
from sonoran.coverage.store import LAYER_LABELS, LAYERS

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
        "tile_size": TILE_SIZE,
        **manifest,
    }


@router.get("/tiles/{preset}/{layer}/{zoom}/{x}/{y}.png")
async def coverage_tile(
    request: Request,
    preset: str = Path(pattern=r"^[A-Za-z]{1,32}$"),
    layer: str = Path(pattern=r"^[a-z]{1,16}$"),
    zoom: int = Path(ge=0, le=MAX_ZOOM),
    x: int = Path(ge=0),
    y: int = Path(ge=0),
) -> Response:
    """Return one coverage tile.

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

    settings = request.app.state.settings
    stamp = store.current_stamp(settings)
    if stamp is None:
        raise HTTPException(status_code=404, detail="no coverage run has been made")

    png = store.read_tile(settings, preset, layer, zoom, x, y)
    if png is None:
        raise HTTPException(status_code=404, detail="no coverage here")

    return Response(
        content=png,
        media_type="image/png",
        headers={
            # A tile of one run never changes. The run stamp is part of
            # the ETag, so a new run makes every tile fresh again.
            "Cache-Control": "public, max-age=86400",
            "ETag": f'"{stamp}-{preset}-{layer}-{zoom}-{x}-{y}"',
        },
    )
