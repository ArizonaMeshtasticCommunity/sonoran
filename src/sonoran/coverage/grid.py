"""One grid for the whole region, and how a raster lands on it.

This module is the only place that decides how a raster maps to the
ground. It is the same arrangement as `sonoran/positions.py` and
`sonoran/api/traces.py`: one module holds the rule, so nothing can hold
a different one.

Every raster the engine makes sits on the same lattice. The engine
works at a whole number of points for each degree, and its region
always starts at a whole degree. So a cell edge is always at

    k / 1200 degrees

for a whole number k. That is true of every run, whatever its centre.

This means a raster does not have to be resampled onto the region grid.
It has to be put in the right place. An offset in whole cells is all
that is needed, and no value ever changes. Resampling would blur every
ridge line the model worked to find.

Levels are held the way the engine reports them: one unsigned byte for
each cell, where

    dBm = byte - 200

A byte of zero means no run reached the cell. That is -200 dBm, which no
radio ever produces, so the sentinel costs nothing.

A signed byte was the obvious choice and it is wrong. It reaches only
-128, and the sensitivity of Long fast is -139 dBm. Every level clipped
to -127, every level then sat above every threshold, and the usable
filter quietly passed everything. Keep the offset.
"""

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

# Points of terrain and of raster for each degree.
#
# The engine and the terrain service both work at this resolution. See
# `sonoran/terrain/srtm.py` and `sonoran/coverage/params.py`.
CELLS_PER_DEGREE = 1200

# What a byte of zero means: no run reached this cell.
NO_COVERAGE = 0

# What to take off a byte to get dBm.
#
# This is the offset the engine itself uses, so a raster crosses into
# this module with no arithmetic at all.
DBM_OFFSET = 200

# The weakest and strongest level a cell may hold, as a byte.
#
# One is the weakest a cell can be and still count as reached. 255 is
# +55 dBm, which is far above anything real and only a clip guard.
MIN_LEVEL = 1
MAX_LEVEL = 255

Levels = npt.NDArray[np.uint8]


def to_dbm(level: int) -> float:
    """Return the level of one cell in dBm."""
    return float(level) - DBM_OFFSET


def to_level(dbm: float) -> int:
    """Return a level in dBm as a byte, held inside the range.

    Use this for a threshold before comparing it against a grid. A
    threshold below the range clamps to the weakest reached cell, so a
    very sensitive preset counts every cell a run touched.
    """
    return int(min(max(round(dbm + DBM_OFFSET), MIN_LEVEL), MAX_LEVEL))


@dataclass(frozen=True)
class Grid:
    """A lattice of cells over a piece of ground.

    `north` and `west` are the outer edges of the first cell, not its
    centre. Row 0 is the north edge and column 0 is the west edge, which
    is the order the engine writes.

    The grid is in plain latitude and longitude. It is not projected.
    The map projects it when it draws.
    """

    north: float
    west: float
    width: int
    height: int
    cells_per_degree: int = CELLS_PER_DEGREE

    @property
    def south(self) -> float:
        """Return the south edge."""
        return self.north - self.height / self.cells_per_degree

    @property
    def east(self) -> float:
        """Return the east edge."""
        return self.west + self.width / self.cells_per_degree

    @property
    def cells(self) -> int:
        """Return how many cells the grid holds."""
        return self.width * self.height

    def bounds(self) -> tuple[float, float, float, float]:
        """Return the edges as south, west, north, east.

        That is the order Leaflet takes for a bounds pair.
        """
        return (self.south, self.west, self.north, self.east)

    def empty(self) -> Levels:
        """Return a grid of cells nothing has reached yet."""
        return np.zeros((self.height, self.width), dtype=np.uint8)

    def row_of(self, latitude: float) -> int:
        """Return the row a latitude falls in. It may be outside."""
        return int(np.floor((self.north - latitude) * self.cells_per_degree))

    def column_of(self, longitude: float) -> int:
        """Return the column a longitude falls in. It may be outside."""
        return int(np.floor((longitude - self.west) * self.cells_per_degree))

    def holds(self, latitude: float, longitude: float) -> bool:
        """Return true when a place is inside this grid."""
        return self.south <= latitude <= self.north and self.west <= longitude <= self.east


def region_grid(
    lat_min: int, lat_max: int, lon_min: int, lon_max: int, cells_per_degree: int = CELLS_PER_DEGREE
) -> Grid:
    """Return the grid that covers a box of whole degrees.

    The bounds are the ones the terrain settings hold, so the grid
    covers exactly the ground the terrain service serves and no more.
    The maximum values are inclusive degrees, as they are in the
    settings: a box of 30 to 37 north covers up to 38 north.
    """
    height = (lat_max + 1 - lat_min) * cells_per_degree
    width = (lon_max + 1 - lon_min) * cells_per_degree
    return Grid(
        north=float(lat_max + 1),
        west=float(lon_min),
        width=width,
        height=height,
        cells_per_degree=cells_per_degree,
    )


def levels_from_raster(
    signal: bytes, mask: bytes, covered_bits: int, width: int, height: int
) -> Levels:
    """Return the levels of one engine raster, as dBm.

    The engine reports a field strength as a byte with a 200 dB offset.
    A cell the sweep never reached carries no value at all, whatever the
    signal byte happens to hold, so the mask is read first.
    """
    signals = np.frombuffer(signal, dtype=np.uint8).reshape(height, width)
    masks = np.frombuffer(mask, dtype=np.uint8).reshape(height, width)
    reached = (masks & covered_bits) != 0
    # A reached cell must never carry the sentinel, so the weakest a
    # cell can report is one byte above it.
    levels = np.maximum(signals, MIN_LEVEL)
    return np.where(reached, levels, NO_COVERAGE).astype(np.uint8)


def blit_max(target: Levels, grid: Grid, patch: Levels, patch_grid: Grid) -> int:
    """Put a raster on the region grid, keeping the stronger cell.

    Returns how many cells of the region this raster set or improved.

    The two grids share a lattice, so the offset is a whole number of
    cells and no value is changed. A run that reaches past the edge of
    the region is cut at the edge.

    "The stronger cell wins" is the right rule for a coverage map: a
    place is served by the best node that reaches it, not by the last
    one computed.
    """
    if patch_grid.cells_per_degree != grid.cells_per_degree:
        raise ValueError("the two grids must share a resolution")

    row = round((grid.north - patch_grid.north) * grid.cells_per_degree)
    column = round((patch_grid.west - grid.west) * grid.cells_per_degree)

    # The part of the patch that lands inside the region.
    top = max(row, 0)
    left = max(column, 0)
    bottom = min(row + patch_grid.height, grid.height)
    right = min(column + patch_grid.width, grid.width)
    if top >= bottom or left >= right:
        return 0

    window = target[top:bottom, left:right]
    piece = patch[top - row : bottom - row, left - column : right - column]

    # A cell nothing reached carries zero, which is the smallest byte,
    # so a plain maximum never lets a hole win.
    better = piece > window
    window[better] = piece[better]
    return int(np.count_nonzero(better))


def combine_min(first: Levels, second: Levels) -> Levels:
    """Return the weaker of two grids, cell by cell.

    This is how the two directions of a link are put together. A place
    is usable only when the node hears the handheld and the handheld
    hears the node. The weaker direction is the one that decides.

    A cell that only one direction reached is not usable at all.
    """
    both = (first != NO_COVERAGE) & (second != NO_COVERAGE)
    return np.where(both, np.minimum(first, second), NO_COVERAGE).astype(np.uint8)


def data_bounds(levels: Levels, grid: Grid, threshold_dbm: float) -> list[float] | None:
    """Return the box the usable coverage sits in, or None.

    The region grid covers every degree the terrain service serves,
    which is far more ground than any mesh reaches. A map that opens on
    the whole region shows the coverage as a speck in the middle. This
    is what the page opens on instead.

    The order is south, west, north, east, which is what Leaflet takes.
    """
    usable = usable_cells(levels, threshold_dbm)
    rows = np.flatnonzero(usable.any(axis=1))
    columns = np.flatnonzero(usable.any(axis=0))
    if not rows.size or not columns.size:
        return None
    step = 1.0 / grid.cells_per_degree
    north = grid.north - rows[0] * step
    south = grid.north - (rows[-1] + 1) * step
    west = grid.west + columns[0] * step
    east = grid.west + (columns[-1] + 1) * step
    return [float(south), float(west), float(north), float(east)]


def union_bounds(boxes: list[list[float]]) -> list[float] | None:
    """Return the box that holds every box given."""
    real = [box for box in boxes if box]
    if not real:
        return None
    return [
        min(box[0] for box in real),
        min(box[1] for box in real),
        max(box[2] for box in real),
        max(box[3] for box in real),
    ]


def usable_cells(levels: Levels, threshold_dbm: float) -> npt.NDArray[np.bool_]:
    """Return which cells reach a level.

    This is the one place a threshold in dBm meets a grid of bytes.
    Everything that draws or counts coverage goes through it.
    """
    return (levels != NO_COVERAGE) & (levels >= to_level(threshold_dbm))


def covered_cells(levels: Levels, threshold_dbm: float) -> int:
    """Return how many cells are at or above a level."""
    return int(np.count_nonzero(usable_cells(levels, threshold_dbm)))


def covered_area_km2(levels: Levels, grid: Grid, threshold_dbm: float) -> float:
    """Return the ground at or above a level, in square kilometres.

    A cell of latitude is the same size everywhere. A cell of longitude
    narrows towards the poles, so each row is weighted by the cosine of
    its own latitude. Counting cells without that overstates the north
    of a region and understates the south.
    """
    metres_per_degree = 111_320.0
    side_m = metres_per_degree / grid.cells_per_degree
    rows = np.arange(grid.height)
    latitudes = grid.north - (rows + 0.5) / grid.cells_per_degree
    weights = np.cos(np.radians(latitudes))
    usable = usable_cells(levels, threshold_dbm)
    per_row = usable.sum(axis=1) * weights
    return float(per_row.sum() * side_m * side_m / 1_000_000.0)
