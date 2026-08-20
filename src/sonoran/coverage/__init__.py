"""Coverage prediction.

The prediction engine is the ITM / Longley-Rice model from SPLAT!,
compiled to WebAssembly and vendored in `web/static/vendor/splat/`. The
planner page runs it in the browser. This package runs the same file in
Python, so a published map and an interactive plan agree.

`units` holds the one conversion from metres to feet. `params` holds
the values the engine takes. `engine` runs it.

The engine is under the GNU General Public License, version 3. See
`AGENTS.md` 7.1.
"""

from sonoran.coverage.engine import (
    EngineError,
    EngineRun,
    Link,
    PageRef,
    Raster,
    Region,
    SplatInstance,
    SplatModule,
    predict,
)
from sonoran.coverage.params import EngineParams, erp_watts, received_dbm
from sonoran.coverage.units import METRES_PER_FOOT, feet_to_metres, metres_to_feet

__all__ = [
    "METRES_PER_FOOT",
    "EngineError",
    "EngineParams",
    "EngineRun",
    "Link",
    "PageRef",
    "Raster",
    "Region",
    "SplatInstance",
    "SplatModule",
    "erp_watts",
    "feet_to_metres",
    "metres_to_feet",
    "predict",
    "received_dbm",
]
