#!/usr/bin/env python
"""Fill the terrain cache for the configured region.

Run this once after deployment. It downloads each SRTM tile in the
region, turns it into an engine page, and writes the page to the cache.

The Arizona region is 8 by 8 tiles. Expect about 640 MB of downloads and
about 184 MB on disk. The run takes a few minutes and can be stopped and
started again: a tile that is already cached is skipped.

Set `TERRAIN_ALLOW_DOWNLOAD=false` afterwards. The API then serves the
cache and makes no outbound request.

    uv run python tools/prefetch_terrain.py
    uv run python tools/prefetch_terrain.py --lat 34 --lon -112
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from sonoran.config import Settings, get_settings
from sonoran.terrain.srtm import tile_name
from sonoran.terrain.store import (
    download_page,
    page_path,
    read_cached_page,
    write_page,
)

logger = logging.getLogger("prefetch")


def region_tiles(settings: Settings) -> list[str]:
    """Return every tile name in the configured region."""
    names = []
    for lat in range(settings.terrain_lat_min, settings.terrain_lat_max + 1):
        for lon in range(settings.terrain_lon_min, settings.terrain_lon_max + 1):
            # tile_name takes the west-positive form the engine reports.
            min_west = -lon - 1 if lon < 0 else 359 - lon
            names.append(tile_name(lat, min_west))
    return names


def tile_for_point(lat: float, lon: float) -> str:
    """Return the tile that holds one position."""
    floor_lat = int(lat // 1)
    floor_lon = int(lon // 1)
    min_west = -floor_lon - 1 if floor_lon < 0 else 359 - floor_lon
    return tile_name(floor_lat, min_west)


async def fetch_one(settings: Settings, name: str) -> str:
    """Make sure one tile is cached. Return what happened."""
    if read_cached_page(settings, name) is not None:
        return "cached"
    page = await download_page(settings, name)
    if page is None:
        return "absent"
    await asyncio.to_thread(write_page, settings, name, page)
    return "written"


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lat", type=float, help="fetch the tile holding this latitude")
    parser.add_argument("--lon", type=float, help="fetch the tile holding this longitude")
    parser.add_argument("--dry-run", action="store_true", help="list the work and stop")
    arguments = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    settings = get_settings()

    if (arguments.lat is None) != (arguments.lon is None):
        parser.error("give both --lat and --lon, or neither")
    if arguments.lat is not None:
        names = [tile_for_point(arguments.lat, arguments.lon)]
    else:
        names = region_tiles(settings)

    logger.info("cache directory: %s", settings.terrain_cache_dir)
    logger.info("tiles to check: %d", len(names))
    if arguments.dry_run:
        for name in names:
            state = "cached" if read_cached_page(settings, name) is not None else "missing"
            logger.info("  %s  %s  %s", name, state, page_path(settings, name))
        return 0

    if not settings.terrain_allow_download:
        logger.error("TERRAIN_ALLOW_DOWNLOAD is false, so nothing can be fetched")
        return 1

    counts = {"cached": 0, "written": 0, "absent": 0, "failed": 0}
    for index, name in enumerate(names, start=1):
        try:
            result = await fetch_one(settings, name)
        except Exception:
            logger.exception("%s failed", name)
            counts["failed"] += 1
            continue
        counts[result] += 1
        logger.info("[%d/%d] %s %s", index, len(names), name, result)

    logger.info(
        "done: %d written, %d already cached, %d not published, %d failed",
        counts["written"],
        counts["cached"],
        counts["absent"],
        counts["failed"],
    )
    return 1 if counts["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
