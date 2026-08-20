"""Where a coverage run is kept.

A run writes tiles and a manifest to disk, beside the terrain cache. It
does not write to the database.

The reason is that the tiles are the run. Holding the manifest in one
place and the pixels in another lets the two disagree, and a map that
says it was made at nine and shows the mesh as it was at six is worse
than no map. Here a run is one directory, and it becomes visible in one
step.

The layout is:

    {cache}/runs/{stamp}/manifest.json
    {cache}/runs/{stamp}/{preset}/{layer}/{z}/{x}/{y}.png
    {cache}/index.json

A run is built under `pending-{stamp}` and renamed when it is whole. A
reader therefore never sees half a run, and a job that dies leaves
nothing a reader can find.
"""

import json
import shutil
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from sonoran.config import Settings
from sonoran.logging import get_logger

logger = get_logger(__name__)

# How many finished runs to keep.
#
# Two is enough to serve the old one while the new one is written, and
# to look at what changed. Tiles are large, so more would cost disk for
# nothing.
KEEP_RUNS = 2

INDEX_NAME = "index.json"
MANIFEST_NAME = "manifest.json"

# The layers a run writes.
#
# `usable` is the honest one and the one a page shows first. It is the
# weaker of the two directions, so it answers "can I use the mesh from
# here", which is what somebody looking at a coverage map wants to know.
LAYERS = ("usable", "downlink", "uplink")

LAYER_LABELS: dict[str, str] = {
    "usable": "Usable both ways",
    "downlink": "Node heard here",
    "uplink": "Here heard by a node",
}


@dataclass
class PresetSummary:
    """What one run found for one modem preset."""

    preset: str
    label: str
    sensitivity_dbm: float
    node_count: int
    positioned_count: int
    skipped_count: int
    usable_area_km2: float
    downlink_area_km2: float
    tile_count: int
    # The box the usable coverage sits in. None when nothing is
    # covered. The page opens on this rather than on the whole region.
    data_bounds: list[float] | None = None
    nodes: list[dict[str, object]] = field(default_factory=list)


@dataclass
class Manifest:
    """What one run did."""

    stamp: str
    generated_at: str
    engine: str
    bounds: list[float]
    min_zoom: int
    max_zoom: int
    radius_km: float
    rx_height_m: float
    rx_gain_dbi: float
    handheld_tx_power_dbm: float
    has_terrain: bool
    has_landcover: bool
    missing_terrain_tiles: list[str]
    seconds: float
    data_bounds: list[float] | None = None
    presets: list[PresetSummary] = field(default_factory=list)


def runs_dir(settings: Settings) -> Path:
    """Return where finished runs are kept."""
    return Path(settings.coverage_cache_dir) / "runs"


def index_path(settings: Settings) -> Path:
    """Return where the pointer to the current run is kept."""
    return Path(settings.coverage_cache_dir) / INDEX_NAME


def new_stamp() -> str:
    """Return a stamp that sorts by time and is safe in a path."""
    return time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())


def pending_dir(settings: Settings, stamp: str) -> Path:
    """Return where a run is built before it is published."""
    return Path(settings.coverage_cache_dir) / f"pending-{stamp}"


def tile_path(root: Path, preset: str, layer: str, zoom: int, x: int, y: int) -> Path:
    """Return where one tile of a run sits."""
    return root / preset / layer / str(zoom) / str(x) / f"{y}.png"


def write_tile(root: Path, preset: str, layer: str, zoom: int, x: int, y: int, png: bytes) -> None:
    """Write one tile."""
    path = tile_path(root, preset, layer, zoom, x, y)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png)


def publish(settings: Settings, stamp: str, manifest: Manifest) -> Path:
    """Make a pending run the current one.

    The manifest is written, the directory is renamed, and only then is
    the index moved. A reader that arrives in the middle sees either the
    run before or the run after, and never a mixture.
    """
    pending = pending_dir(settings, stamp)
    (pending / MANIFEST_NAME).write_text(json.dumps(asdict(manifest), indent=1), encoding="utf-8")

    final = runs_dir(settings) / stamp
    final.parent.mkdir(parents=True, exist_ok=True)
    if final.exists():
        shutil.rmtree(final, ignore_errors=True)
    pending.rename(final)

    index = index_path(settings)
    index.parent.mkdir(parents=True, exist_ok=True)
    temporary = index.with_suffix(f".{stamp}.tmp")
    temporary.write_text(json.dumps({"current": stamp}, indent=1), encoding="utf-8")
    temporary.replace(index)

    prune(settings)
    logger.info("published coverage run %s", stamp)
    return final


def prune(settings: Settings, keep: int = KEEP_RUNS) -> None:
    """Delete every run but the newest few."""
    root = runs_dir(settings)
    if not root.is_dir():
        return
    stamps = sorted((path for path in root.iterdir() if path.is_dir()), reverse=True)
    for path in stamps[keep:]:
        shutil.rmtree(path, ignore_errors=True)
        logger.info("removed old coverage run %s", path.name)


def current_stamp(settings: Settings) -> str | None:
    """Return the stamp of the current run, or None."""
    try:
        document = json.loads(index_path(settings).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    stamp = document.get("current")
    return stamp if isinstance(stamp, str) else None


def current_root(settings: Settings) -> Path | None:
    """Return the directory of the current run, or None."""
    stamp = current_stamp(settings)
    if stamp is None:
        return None
    root = runs_dir(settings) / stamp
    return root if root.is_dir() else None


def read_manifest(settings: Settings) -> dict[str, object] | None:
    """Return the manifest of the current run, or None.

    A deployment that has never run the job has none. That is a working
    state: the page says the map has not been made yet.
    """
    root = current_root(settings)
    if root is None:
        return None
    try:
        document = json.loads((root / MANIFEST_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        logger.warning("cannot read the coverage manifest: %s", error)
        return None
    return document if isinstance(document, dict) else None


def read_tile(
    settings: Settings, preset: str, layer: str, zoom: int, x: int, y: int
) -> bytes | None:
    """Return one tile of the current run, or None.

    A tile that was never written is ground no node reaches. The API
    answers those with a 404 and the map draws nothing there.
    """
    root = current_root(settings)
    if root is None:
        return None
    path = tile_path(root, preset, layer, zoom, x, y)
    try:
        return path.read_bytes()
    except (OSError, ValueError):
        return None
