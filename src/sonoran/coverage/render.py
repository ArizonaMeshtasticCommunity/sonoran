"""Turning coverage levels into map tiles.

The job writes tiles rather than one large image. A browser fetches only
the tiles it can see, at only the zoom it is at, and it fetches each one
once because they never change. That is what makes the map open fast on
a phone.

The tiles are in the usual web map scheme, so Leaflet reads them with no
help: `{z}/{x}/{y}.png`, 256 pixels square, Web Mercator.

The colours are the ones the dashboard already uses. The palette lives
in `web/static/app.css` and this module holds the same values, because
Python cannot read a stylesheet. `tests/unit/test_coverage_map.py`
pins the two together.

PNG is written here rather than with an imaging library. A tile is a
plain RGBA raster and the format wants a zlib stream and four chunks, so
a dependency for it would earn nothing.

Each colour tile has a margin tile beside it (#334). The colour tile
holds colours only, and a colour cannot be read back as a level without
loss. The margin tile is one grey byte for each pixel:

    byte 0      no usable coverage here
    byte n      n - 1 dB above the sensitivity of the preset

The levels are whole dB. The threshold meets them as a whole byte
through `to_level`, the same byte the colour tile uses, also for a
preset whose sensitivity is on a half dB (#362). So the margin is a
whole number and the byte holds it exactly. The dashboard colours a margin
tile in the browser to draw a signal floor. The public embed never reads
one. See `docs/COVERAGE.md` 6.1.2.
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
# Sixty dB is measured, not chosen. Over the live Arizona mesh, 16
# sites and 1.5 million covered cells, the margin of the published
# `usable` layer falls out like this:
#
#     p5   3      p25  20      p50  35      p75  46      p95  55
#
# The figure that matters is how much of the map sits at the top of the
# ramp, where every cell is the same colour and the map stops saying
# anything:
#
#     span 30 dB -> 60% of the map saturated
#     span 40 dB -> 41%
#     span 50 dB -> 13%
#     span 60 dB ->  2%
#
# Thirty dB was taken from the levels of a single site. The published
# map is the strongest of every site over the same ground, so its
# margins are far higher, and two thirds of it came out one flat blue.
# Sixty puts the median at the middle of the ramp, where the colours
# are furthest apart, and it is what `planner.js` has always used, so
# the two pages finally agree.
RAMP_SPAN_DB = 60.0

# The name of the margin tile encoding. A run writes it into its
# manifest, and the page draws a floor only for an encoding it knows.
MARGIN_ENCODING = "margin_db_plus_one"


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


def margin_levels(levels: Levels, threshold_dbm: float) -> npt.NDArray[np.uint8]:
    """Return the margin byte of each cell, for a margin tile.

    Zero where `colour_levels` leaves the cell clear. Elsewhere one more
    than the dB above the threshold. A level is at most 255 and the
    threshold byte is at least 1, so the largest margin is 254 dB and
    its byte is 255. Nothing is clipped.
    """
    usable = usable_cells(levels, threshold_dbm)
    above = levels.astype(np.int16) - to_level(threshold_dbm) + 1
    return np.where(usable, above, 0).astype(np.uint8)


def margin_db(byte: int) -> int | None:
    """Return the margin a margin tile byte holds, or None for none."""
    return None if byte == 0 else byte - 1


def write_png(image: npt.NDArray[np.uint8]) -> bytes:
    """Return an RGBA image as a PNG file.

    A tile is a plain raster, so the format needs only a header, the
    pixels, and an end marker. Each row carries a filter byte of zero,
    which means the row is stored as it is.
    """
    return _png(image.reshape(image.shape[0], image.shape[1] * 4), image.shape[1], 6)


def write_grey_png(image: npt.NDArray[np.uint8]) -> bytes:
    """Return a two-dimensional image of bytes as a grey PNG file.

    A margin tile is written this way. A grey PNG has no colour profile
    and no alpha, so a browser that decodes it gives back each byte as
    it was written.
    """
    return _png(image, image.shape[1], 0)


def _png(rows_of_bytes: npt.NDArray[np.uint8], width: int, colour_type: int) -> bytes:
    """Return a PNG of eight bit samples, one row of bytes for each row."""
    height = rows_of_bytes.shape[0]
    rows = np.concatenate([np.zeros((height, 1), dtype=np.uint8), rows_of_bytes], axis=1)
    body = zlib.compress(rows.tobytes(), level=6)

    def chunk(kind: bytes, payload: bytes) -> bytes:
        head = struct.pack(">I", len(payload)) + kind
        return head + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", width, height, 8, colour_type, 0, 0, 0)
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
