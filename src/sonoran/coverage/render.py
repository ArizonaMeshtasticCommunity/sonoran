"""Turning coverage levels into map tiles.

The job writes tiles rather than one large image. A browser fetches only
the tiles it can see, at only the zoom it is at, and it fetches each one
once because they never change. That is what makes the map open fast on
a phone.

The tiles are in the usual web map scheme, so Leaflet reads them with no
help: `{z}/{x}/{y}.png`, 256 pixels square, Web Mercator.

The colours are the ones the dashboard already uses. The palette lives
in `web/static/app.css` and this module holds the same values, because
Python cannot read a stylesheet. `tests/unit/test_coverage_render.py`
pins the two together.

PNG is written here rather than with an imaging library. A tile is a
plain RGBA raster and the format wants a zlib stream and four chunks, so
a dependency for it would earn nothing.
"""

import math
import struct
import zlib
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from sonoran.coverage.grid import NO_COVERAGE, Grid, Levels, to_level, usable_cells

# Pixels on each side of a tile.
TILE_SIZE = 256

# The colour ramp, weakest first.
#
# These colours do not occur in the dark terrain map as one natural
# ramp. The weak end starts hot. The strong end finishes cool. A reader
# can therefore see both the edge and the direction of improvement.
# The map can be turned off when the ground detail is more important.
RAMP: tuple[tuple[int, int, int], ...] = (
    (0xFF, 0x2D, 0x55),
    (0xFF, 0x7A, 0x00),
    (0xFF, 0xE6, 0x00),
    (0x00, 0xD9, 0x8B),
    (0x00, 0xA8, 0xFF),
)

# How opaque a covered cell is drawn, from 0 to 255.
#
# The strength layer must remain distinct from the terrain map. The
# reader can turn it off to read roads and place names without it.
COVER_ALPHA = 235

# The range the ramp spans above the threshold, in dB.
#
# This is a link margin scale, not an absolute one. Zero is the
# sensitivity of the preset, so a cell at the weak end of the ramp is
# one the mesh only just reaches.
#
# Thirty dB is chosen from what the model actually produces. Over real
# Arizona terrain the levels of one site fall out like this, as dB above
# the floor:
#
#     p25  14      p75  15      p95  43      p99  52
#
# Most of a footprint sits near 14 dB of margin, and a linear scale of
# 30 dB puts that mid ramp, where the colours are furthest apart. A
# wider scale pushes the whole footprint into one flat colour and hides
# the difference between ground that just works and ground that works
# well. Past 30 dB of margin the link is as good as it gets, and the
# colour stops changing, which is honest.
RAMP_SPAN_DB = 30.0


@dataclass(frozen=True)
class TileRef:
    """One tile in the web map scheme."""

    zoom: int
    x: int
    y: int

    @property
    def path(self) -> str:
        """Return the path part of this tile, without a suffix."""
        return f"{self.zoom}/{self.x}/{self.y}"


def _ramp_colour(fraction: npt.NDArray[np.float32]) -> npt.NDArray[np.uint8]:
    """Return the ramp colour for each value, from 0 to 1."""
    stops = np.array(RAMP, dtype=np.float32)
    last = len(RAMP) - 1
    position = np.clip(fraction, 0.0, 1.0) * last
    lower = np.floor(position).astype(np.int32)
    upper = np.minimum(lower + 1, last)
    weight = (position - lower)[..., None]
    mixed = stops[lower] * (1.0 - weight) + stops[upper] * weight
    return mixed.astype(np.uint8)


def colour_levels(levels: Levels, threshold_dbm: float) -> npt.NDArray[np.uint8]:
    """Return an RGBA image for a block of levels.

    A cell below the threshold is left clear, not drawn dark. The map
    must show where the mesh reaches, and painting the rest would hide
    the ground instead of describing it.
    """
    height, width = levels.shape
    image = np.zeros((height, width, 4), dtype=np.uint8)

    usable = usable_cells(levels, threshold_dbm)
    if not usable.any():
        return image

    # A dB above the threshold is a byte above it, because the levels
    # and the threshold share the same offset.
    floor = to_level(threshold_dbm)
    margin = (levels.astype(np.float32) - floor) / RAMP_SPAN_DB
    image[..., :3] = _ramp_colour(margin)
    image[..., 3] = np.where(usable, COVER_ALPHA, 0)
    return image


def write_png(image: npt.NDArray[np.uint8]) -> bytes:
    """Return an RGBA image as a PNG file.

    A tile is a plain raster, so the format needs only a header, the
    pixels, and an end marker. Each row carries a filter byte of zero,
    which means the row is stored as it is.
    """
    height, width = image.shape[0], image.shape[1]
    rows = np.concatenate(
        [np.zeros((height, 1), dtype=np.uint8), image.reshape(height, width * 4)], axis=1
    )
    body = zlib.compress(rows.tobytes(), level=6)

    def chunk(kind: bytes, payload: bytes) -> bytes:
        head = struct.pack(">I", len(payload)) + kind
        return head + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", body) + chunk(b"IEND", b"")
    )


def tile_latitudes(tile: TileRef) -> npt.NDArray[np.float64]:
    """Return the latitude of the centre of each row of a tile.

    A web map tile is even in Web Mercator, not in latitude. A row near
    the top of a tile covers more ground than a row near the bottom.
    Reading the grid evenly would put the coverage in the wrong place,
    by more than a kilometre at the top of Arizona.
    """
    scale = 2**tile.zoom
    rows = np.arange(TILE_SIZE) + 0.5
    y = (tile.y + rows / TILE_SIZE) / scale
    mercator = math.pi * (1.0 - 2.0 * y)
    return np.degrees(np.arctan(np.sinh(mercator)))


def tile_longitudes(tile: TileRef) -> npt.NDArray[np.float64]:
    """Return the longitude of the centre of each column of a tile."""
    scale = 2**tile.zoom
    columns = np.arange(TILE_SIZE) + 0.5
    return (tile.x + columns / TILE_SIZE) / scale * 360.0 - 180.0


def sample_tile(levels: Levels, grid: Grid, tile: TileRef) -> Levels:
    """Return the levels under one tile.

    The nearest cell is taken. Smoothing between cells would invent a
    signal between two ridges that the model says is not there.
    """
    latitudes = tile_latitudes(tile)
    longitudes = tile_longitudes(tile)

    rows = np.floor((grid.north - latitudes) * grid.cells_per_degree).astype(np.int64)
    columns = np.floor((longitudes - grid.west) * grid.cells_per_degree).astype(np.int64)

    inside_rows = (rows >= 0) & (rows < grid.height)
    inside_columns = (columns >= 0) & (columns < grid.width)

    safe_rows = np.clip(rows, 0, grid.height - 1)
    safe_columns = np.clip(columns, 0, grid.width - 1)

    patch = levels[safe_rows[:, None], safe_columns[None, :]]
    inside = inside_rows[:, None] & inside_columns[None, :]
    return np.where(inside, patch, NO_COVERAGE).astype(np.uint8)


def tiles_for_grid(grid: Grid, zoom: int) -> list[TileRef]:
    """Return every tile of a zoom level that touches a grid."""
    scale = 2**zoom

    def x_of(longitude: float) -> int:
        return math.floor((longitude + 180.0) / 360.0 * scale)

    def y_of(latitude: float) -> int:
        clamped = max(min(latitude, 85.05112878), -85.05112878)
        radians = math.radians(clamped)
        value = (1.0 - math.asinh(math.tan(radians)) / math.pi) / 2.0
        return math.floor(value * scale)

    x_start = max(x_of(grid.west), 0)
    x_end = min(x_of(grid.east), scale - 1)
    y_start = max(y_of(grid.north), 0)
    y_end = min(y_of(grid.south), scale - 1)

    return [
        TileRef(zoom, x, y) for x in range(x_start, x_end + 1) for y in range(y_start, y_end + 1)
    ]
