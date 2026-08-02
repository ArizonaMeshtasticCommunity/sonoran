"""Terrain elevation data for the coverage planner.

This package reads SRTM elevation tiles and makes the elevation pages
that the SPLAT! coverage engine reads.

This package must never touch the database. It has the same rule as the
`decode` and `crypto` packages.
"""

from sonoran.terrain.srtm import (
    HGT_SIZE,
    PAGE_BYTES,
    PAGE_SIZE,
    SRTM_NODATA,
    page_from_hgt,
    page_signed_floor_lon,
    tile_name,
)

__all__ = [
    "HGT_SIZE",
    "PAGE_BYTES",
    "PAGE_SIZE",
    "SRTM_NODATA",
    "page_from_hgt",
    "page_signed_floor_lon",
    "tile_name",
]
