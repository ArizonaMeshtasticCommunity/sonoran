"""What stands on the ground, and how much signal it takes.

The terrain model says where the ground is. This package says what is
on it, so a prediction can charge the clutter loss that ITM leaves out.

The data is the ESA WorldCover 10 m product, reduced to the same page
grid the terrain uses. `tools/prefetch_landcover.py` makes the pages.
A deployment with no pages predicts with no clutter, which is what the
planner has always done.

This package must never touch the database. It has the same rule as
`decode`, `crypto`, and `terrain`.
"""

from sonoran.landcover.classes import (
    CLASSES,
    UNKNOWN,
    UNKNOWN_CLASS,
    LandCover,
    clutter_height_m,
    land_cover,
)
from sonoran.landcover.store import PAGE_BYTES, clutter_at, page_path, read_page

__all__ = [
    "CLASSES",
    "PAGE_BYTES",
    "UNKNOWN",
    "UNKNOWN_CLASS",
    "LandCover",
    "clutter_at",
    "clutter_height_m",
    "land_cover",
    "page_path",
    "read_page",
]
