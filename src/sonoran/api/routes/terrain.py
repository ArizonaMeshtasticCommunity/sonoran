"""Read-only terrain endpoints for the coverage planner.

The planner runs in the browser. It asks the engine which elevation
pages it needs, then reads each of them from here.

A page never changes, so the response is cacheable forever. The browser
should ask for a tile once and never again.
"""

import logging

from fastapi import APIRouter, HTTPException, Request, Response

from sonoran.config import Settings
from sonoran.terrain.srtm import PAGE_BYTES
from sonoran.terrain.store import in_region, is_tile_name, load_page

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/terrain", tags=["terrain"])


@router.get("/page/{tile}")
async def terrain_page(tile: str, request: Request) -> Response:
    """Return the elevation page of one SRTM tile.

    The body is `PAGE_BYTES` of little-endian int16, in the cell order
    the engine reads. A 404 means no terrain is held for that tile. The
    planner treats that as sea level, which is what the engine does with
    a page it was never given.
    """
    if not is_tile_name(tile):
        raise HTTPException(status_code=422, detail=f"not a tile name: {tile}")

    settings: Settings = request.app.state.settings
    if not in_region(settings, tile):
        # Outside the region this service covers. Refusing here stops the
        # endpoint being a general purpose proxy for the tile source.
        raise HTTPException(status_code=404, detail=f"no terrain for {tile}")

    page = await load_page(settings, tile)
    if page is None:
        raise HTTPException(status_code=404, detail=f"no terrain for {tile}")

    return Response(
        content=page,
        media_type="application/octet-stream",
        headers={
            "Cache-Control": "public, max-age=31536000, immutable",
            "ETag": f'"{tile}-{PAGE_BYTES}"',
        },
    )


@router.get("/region")
async def terrain_region(request: Request) -> dict[str, object]:
    """Return the region this service holds terrain for.

    The planner reads this to warn before a run reaches past the edge of
    the data, where coverage would be drawn over flat ground.
    """
    settings: Settings = request.app.state.settings
    return {
        "lat_min": settings.terrain_lat_min,
        "lat_max": settings.terrain_lat_max + 1,
        "lon_min": settings.terrain_lon_min,
        "lon_max": settings.terrain_lon_max + 1,
        "page_bytes": PAGE_BYTES,
    }
