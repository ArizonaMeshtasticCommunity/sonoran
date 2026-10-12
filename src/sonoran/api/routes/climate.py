"""Read-only radio climate endpoints for the coverage planner (#239).

The planner must never send a site to this server (`docs/PLANNER.md`
2). So there is no "climate at this point" endpoint. The browser asks
for the one degree square around its site, the same square it already
asks terrain for, and reads the cell itself.

The data ships inside the package and never changes, so a page is
cacheable for ever. Like the terrain page, it is served for the
configured region only.
"""

from fastapi import APIRouter, HTTPException, Request, Response

from sonoran.climate import (
    CELLS_PER_DEGREE,
    CROP,
    FALLBACK_CLIMATE,
    KOPPEN,
    PAGE_BYTES,
    SOURCE,
    page,
)
from sonoran.config import Settings
from sonoran.terrain.store import in_region, is_tile_name, tile_bounds

router = APIRouter(prefix="/api/climate", tags=["climate"])


@router.get("/page/{tile}")
async def climate_page(tile: str, request: Request) -> Response:
    """Return the Köppen-Geiger classes of one degree square.

    The body is `PAGE_BYTES` bytes, one class number for each cell. Row
    0 is the north edge and column 0 the west edge. A 404 means no class
    is known there, and the planner then uses the fallback and says so.
    """
    if not is_tile_name(tile):
        raise HTTPException(status_code=422, detail=f"not a tile name: {tile}")

    settings: Settings = request.app.state.settings
    if not in_region(settings, tile):
        # The terrain rule: this service answers for its own region and
        # nowhere else (AGENTS.md 7).
        raise HTTPException(status_code=404, detail=f"no climate for {tile}")

    latitude, longitude = tile_bounds(tile)
    body = page(latitude, longitude)
    if body is None:
        raise HTTPException(status_code=404, detail=f"no climate for {tile}")

    return Response(
        content=body,
        media_type="application/octet-stream",
        headers={
            "Cache-Control": "public, max-age=31536000, immutable",
            "ETag": f'"climate-{tile}-{PAGE_BYTES}"',
        },
    )


@router.get("/classes")
async def climate_classes() -> dict[str, object]:
    """Return the Köppen to ITM table, and what the data is.

    The planner reads the table from here rather than keeping a copy,
    so the page and the coverage job cannot map a class two ways.
    """
    return {
        "source": SOURCE,
        "cells_per_degree": CELLS_PER_DEGREE,
        "page_bytes": PAGE_BYTES,
        "fallback": FALLBACK_CLIMATE,
        "extent": {
            "lat_min": CROP.south,
            "lat_max": CROP.north,
            "lon_min": CROP.west,
            "lon_max": CROP.east,
        },
        "classes": [
            {
                "code": item.code,
                "symbol": item.symbol,
                "name": item.name,
                "climate": item.climate,
                "reason": item.reason,
            }
            for item in KOPPEN
        ],
    }
