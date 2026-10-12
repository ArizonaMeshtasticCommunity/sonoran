"""The Köppen-Geiger grid this deployment ships, and reading it.

The grid is a crop of the Beck et al. (2023) map, 1991 to 2020, at
1/120 degree. That is about 0.93 km north to south and 0.77 km east to
west at Phoenix. `tools/make_climate_crop.py` makes it. Each cell is
one byte, holding the class number of the source legend (1 to 30), or
0 where the source has no class.

The cell order is row 0 at the **north** edge and column 0 at the
**west** edge. That is the order of the source file, of a land cover
page and of a coverage grid. It is **not** the order of a terrain page,
which is south-up and east-first (AGENTS.md 9.13.1).

The file is part of the package, so it needs no download, no cache
directory and no setting. A place outside the crop has no class, and
the caller falls back to `desert` and says so. It never guesses.

This module must never touch the database.
"""

import gzip
import logging
import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
import numpy.typing as npt

logger = logging.getLogger(__name__)

# Cells for each degree, in both directions. The source is 0.00833333
# degrees, which is 1/120.
CELLS_PER_DEGREE = 120

# The value of a cell the source gives no class to.
NO_CLASS = 0


@dataclass(frozen=True)
class Extent:
    """A box of whole degrees. South and west are inside, north and east are not."""

    south: int
    north: int
    west: int
    east: int

    def contains(self, latitude: float, longitude: float) -> bool:
        """Return true when a point is inside the box."""
        return self.south <= latitude < self.north and self.west <= longitude < self.east

    @property
    def rows(self) -> int:
        """Return the number of cell rows."""
        return (self.north - self.south) * CELLS_PER_DEGREE

    @property
    def columns(self) -> int:
        """Return the number of cell columns."""
        return (self.east - self.west) * CELLS_PER_DEGREE


# The crop that ships. It is the default terrain region in `config.py`,
# tile for tile: 30 to 38 north and 116 to 108 west. Arizona is 31.33 to
# 37.00 north and 114.82 to 109.04 west, so the whole state is inside
# with a margin, and so is every site the planner can draw terrain for.
CROP = Extent(south=30, north=38, west=-116, east=-108)

# The compressed grid.
DATA_FILE = Path(__file__).with_name("koppen_1991_2020.u8.gz")

# The bytes of one page, one degree square.
PAGE_BYTES = CELLS_PER_DEGREE * CELLS_PER_DEGREE


@lru_cache(maxsize=1)
def _grid() -> npt.NDArray[np.uint8] | None:
    """Return the whole crop, or None when the file cannot be read.

    0.9 MB in memory. It is read once for the life of the process.
    """
    try:
        raw = gzip.decompress(DATA_FILE.read_bytes())
    except (OSError, EOFError, gzip.BadGzipFile) as error:
        logger.warning("cannot read the climate grid at %s: %s", DATA_FILE, error)
        return None
    expected = CROP.rows * CROP.columns
    if len(raw) != expected:
        logger.warning("the climate grid is %s bytes, not %s, so it is ignored", len(raw), expected)
        return None
    return np.frombuffer(raw, dtype=np.uint8).reshape(CROP.rows, CROP.columns)


def koppen_at(latitude: float, longitude: float) -> int | None:
    """Return the Köppen-Geiger class number at a place, or None.

    None outside the crop, and where the source gives no class. A cell
    is the square whose north-west corner the index names, which is how
    the source file lays out its cells.
    """
    if not (math.isfinite(latitude) and math.isfinite(longitude)):
        return None
    if not CROP.contains(latitude, longitude):
        return None
    grid = _grid()
    if grid is None:
        return None
    row = min(int((CROP.north - latitude) * CELLS_PER_DEGREE), CROP.rows - 1)
    column = min(int((longitude - CROP.west) * CELLS_PER_DEGREE), CROP.columns - 1)
    value = int(grid[row, column])
    return None if value == NO_CLASS else value


def page(latitude: int, longitude: int) -> bytes | None:
    """Return one degree of the grid, by its south-west corner, or None.

    `PAGE_BYTES` bytes. Row 0 is the north edge of the degree and column
    0 is its west edge. None when the degree is not wholly inside the
    crop, or when the grid cannot be read.
    """
    if not (CROP.south <= latitude < CROP.north and CROP.west <= longitude < CROP.east):
        return None
    grid = _grid()
    if grid is None:
        return None
    top = (CROP.north - latitude - 1) * CELLS_PER_DEGREE
    left = (longitude - CROP.west) * CELLS_PER_DEGREE
    block = grid[top : top + CELLS_PER_DEGREE, left : left + CELLS_PER_DEGREE]
    return np.ascontiguousarray(block).tobytes()
