"""The land cover pages on disk.

A page is one degree of latitude by one degree of longitude, at the same
1200 by 1200 lattice the terrain uses. Each cell is one byte, holding
the ESA WorldCover class of that ground.

`tools/prefetch_landcover.py` makes the pages once. It reads the source
product, which is a set of large cloud optimised GeoTIFF files, and
needs `rasterio` to do it. Nothing here does. This module reads plain
bytes, so the API and the jobs need no geospatial libraries at all.
That is the same arrangement the terrain cache uses.

A deployment with no pages predicts with no clutter. That is a working
state and not a fault, and it is what the planner page has always done.
"""

import re
from functools import lru_cache
from pathlib import Path

import numpy as np

from sonoran.config import Settings
from sonoran.landcover.classes import UNKNOWN_CLASS, clutter_height_m
from sonoran.logging import get_logger

logger = get_logger(__name__)

# Cells on each side of a page. The terrain uses the same figure.
PAGE_SIZE = 1200

PAGE_BYTES = PAGE_SIZE * PAGE_SIZE

# A page file name. The value becomes part of a path, so it is checked.
TILE_PATTERN = re.compile(r"^[NS]\d{2}[EW]\d{3}$")


def is_tile_name(name: str) -> bool:
    """Return true when a name is a tile name and safe in a path."""
    return bool(TILE_PATTERN.fullmatch(name))


def tile_name(latitude: int, longitude: int) -> str:
    """Return the tile name for the south-west corner of a degree."""
    north_south = "N" if latitude >= 0 else "S"
    east_west = "E" if longitude >= 0 else "W"
    return f"{north_south}{abs(latitude):02d}{east_west}{abs(longitude):03d}"


def page_path(settings: Settings, name: str) -> Path:
    """Return where a page is kept."""
    return Path(settings.landcover_cache_dir) / f"{name}.class.u8"


@lru_cache(maxsize=64)
def _read(path: str) -> bytes | None:
    """Return the bytes of a page file, or None.

    Pages never change, so they are worth holding. Sixty-four pages is
    88 MB, which covers a region far larger than one deployment needs.
    """
    file = Path(path)
    try:
        data = file.read_bytes()
    except FileNotFoundError:
        return None
    except OSError as error:
        logger.warning("cannot read the land cover page at %s: %s", file, error)
        return None
    if len(data) != PAGE_BYTES:
        logger.warning("the land cover page at %s is %s bytes, ignored", file, len(data))
        return None
    return data


def read_page(settings: Settings, name: str) -> bytes | None:
    """Return one land cover page, or None when there is none."""
    if not is_tile_name(name):
        return None
    return _read(str(page_path(settings, name)))


def class_at(settings: Settings, latitude: float, longitude: float) -> int:
    """Return the land cover class at a place.

    A place with no page gives `UNKNOWN_CLASS`.
    """
    floor_lat = int(np.floor(latitude))
    floor_lon = int(np.floor(longitude))
    page = read_page(settings, tile_name(floor_lat, floor_lon))
    if page is None:
        return UNKNOWN_CLASS

    # Row 0 is the north edge of the degree, as it is in a terrain page.
    row = int((floor_lat + 1 - latitude) * PAGE_SIZE)
    column = int((longitude - floor_lon) * PAGE_SIZE)
    row = min(max(row, 0), PAGE_SIZE - 1)
    column = min(max(column, 0), PAGE_SIZE - 1)
    return page[row * PAGE_SIZE + column]


def clutter_at(settings: Settings, latitude: float, longitude: float) -> float:
    """Return the nominal clutter height at a place, in metres.

    A place with no land cover data gives zero, which predicts as open
    ground. The caller must say so rather than let a reader believe the
    clutter was accounted for.
    """
    return clutter_height_m(class_at(settings, latitude, longitude))


def have_pages(settings: Settings) -> bool:
    """Return true when this deployment holds any land cover page.

    A page that draws a prediction reads this to decide whether it may
    claim that buildings and trees were accounted for.
    """
    directory = Path(settings.landcover_cache_dir)
    try:
        return any(directory.glob("*.class.u8"))
    except OSError:
        return False
