"""Cache and supply of terrain pages.

A page is expensive to make and never changes, so it is made once and
kept on disk. The planner asks for the same few tiles again and again.

The download is optional. Set `terrain_allow_download` to false after
`tools/prefetch_terrain.py` has filled the cache. The API process then
makes no outbound request at all.

This module never touches the database.
"""

import asyncio
import gzip
import logging
import os
import re
from pathlib import Path

import httpx

from sonoran.config import Settings
from sonoran.terrain.srtm import PAGE_BYTES, page_from_hgt, tile_urls

logger = logging.getLogger(__name__)

# A skadi tile name, for example N34W112. Nothing else is ever accepted,
# because this value becomes part of a file path and of a URL.
TILE_PATTERN = re.compile(r"^[NS]\d{2}[EW]\d{3}$")

# One lock per tile. Several workers ask for the same tile at once, and
# without this each of them would download it.
_locks: dict[str, asyncio.Lock] = {}


class TerrainError(Exception):
    """A terrain page could not be supplied."""


def is_tile_name(name: str) -> bool:
    """Return true when the name is a well formed tile name."""
    return TILE_PATTERN.match(name) is not None


def tile_bounds(name: str) -> tuple[int, int]:
    """Return the signed south-west corner of a tile as (lat, lon).

    The caller must check the name first.
    """
    lat = int(name[1:3])
    lon = int(name[4:7])
    return (lat if name[0] == "N" else -lat, lon if name[3] == "E" else -lon)


def in_region(settings: Settings, name: str) -> bool:
    """Return true when a tile is inside the configured region.

    The service covers one region only. Without this check the endpoint
    would fetch and cache any tile on earth for anybody who asks.
    """
    lat, lon = tile_bounds(name)
    return (
        settings.terrain_lat_min <= lat <= settings.terrain_lat_max
        and settings.terrain_lon_min <= lon <= settings.terrain_lon_max
    )


def coordinates_in_region(settings: Settings, latitude: float, longitude: float) -> bool:
    """Return true when a point has terrain in the configured region."""
    return (
        settings.terrain_lat_min <= latitude < settings.terrain_lat_max + 1
        and settings.terrain_lon_min <= longitude < settings.terrain_lon_max + 1
    )


def page_path(settings: Settings, name: str) -> Path:
    """Return the cache path of a tile page."""
    return Path(settings.terrain_cache_dir) / f"{name}.page.i16"


def read_cached_page(settings: Settings, name: str) -> bytes | None:
    """Return a cached page, or None when it is absent or damaged."""
    path = page_path(settings, name)
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if len(data) != PAGE_BYTES:
        logger.warning("terrain page %s has %d bytes, expected %d", name, len(data), PAGE_BYTES)
        return None
    return data


def write_page(settings: Settings, name: str, data: bytes) -> bool:
    """Write a page to the cache. Return whether it was written.

    The write goes to a temporary file and is then renamed, so a reader
    never sees a part written page.

    A cache that cannot be written is a problem to fix, not a reason to
    fail the request: the page is already made and the caller can serve
    it. The usual cause is a volume that belongs to root while the
    process runs as somebody else.
    """
    path = page_path(settings, name)
    temporary = path.with_suffix(f".{os.getpid()}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_bytes(data)
        temporary.replace(path)
    except OSError as error:
        logger.error("terrain page %s could not be cached at %s: %s", name, path, error)
        temporary.unlink(missing_ok=True)
        return False
    return True


def decode_tile(compressed: bytes) -> bytes:
    """Decompress a downloaded tile and turn it into a page."""
    return page_from_hgt(gzip.decompress(compressed))


async def download_page(settings: Settings, name: str) -> bytes | None:
    """Download a tile and make its page.

    Returns None when the source holds no such tile. That is normal. A
    tile of open sea is not published, and the engine reads a missing
    page as sea level.
    """
    timeout = httpx.Timeout(settings.terrain_timeout_seconds)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        for url in tile_urls(settings.terrain_source_url, name):
            try:
                response = await client.get(url)
            except httpx.HTTPError as error:
                logger.warning("terrain download failed for %s: %s", url, error)
                continue
            if response.status_code == 404:
                continue
            if response.status_code != 200:
                logger.warning("terrain download for %s returned %d", url, response.status_code)
                continue
            logger.info("terrain tile %s downloaded, %d bytes", name, len(response.content))
            # Both steps are slow and hold the processor, so they run in
            # a worker thread. In the event loop they would stop every
            # other request for several seconds.
            return await asyncio.to_thread(decode_tile, response.content)
    return None


async def load_page(settings: Settings, name: str) -> bytes | None:
    """Return the page for a tile, and make it when necessary.

    Returns None when the tile is not held and cannot be obtained.
    """
    if not is_tile_name(name):
        raise TerrainError(f"not a tile name: {name!r}")

    cached = await asyncio.to_thread(read_cached_page, settings, name)
    if cached is not None:
        return cached
    if not settings.terrain_allow_download:
        return None

    lock = _locks.setdefault(name, asyncio.Lock())
    async with lock:
        # Another request may have written the page while this one waited.
        cached = await asyncio.to_thread(read_cached_page, settings, name)
        if cached is not None:
            return cached
        page = await download_page(settings, name)
        if page is None:
            return None
        await asyncio.to_thread(write_page, settings, name, page)
        return page
