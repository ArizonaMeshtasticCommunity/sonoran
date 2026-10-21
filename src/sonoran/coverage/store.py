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
    {cache}/runs/{stamp}/{preset}/{site_set}/{layer}/{z}/{x}/{y}.png
    {cache}/runs/{stamp}/{preset}/{site_set}/{layer}/margin/{z}/{x}/{y}.png
    {cache}/index.json

The second tile is the margin tile of the first (#334). It holds the dB
above the sensitivity, one grey byte for each pixel, so the dashboard
can draw a signal floor. See `coverage/render.py`. It sits under a
directory named `margin`, which is not a number. A route that takes the
zoom as a whole number, such as the public tile route, therefore cannot
name a margin tile.

The site set is part of the path because one run can publish more than
one map. It is also the name a reader trusts, so a run that predicted
from anything but infrastructure roles writes `diagnostic` there rather
than `infrastructure`. See `sonoran/roles.py` and `AGENTS.md` 9.25.

A run is built under `pending-{stamp}` and renamed when it is whole. A
reader therefore never sees half a run, and a job that dies leaves
nothing a reader can find.
"""

import json
import math
import re
import shutil
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from sonoran.config import Settings
from sonoran.coverage.calibrate import (
    MAX_TRUSTED_BIAS_DB,
    MAX_TRUSTED_SPREAD_DB,
    MIN_COUNTERPARTIES,
    MIN_OBSERVATIONS,
    MIN_REPORTED,
    Calibration,
)
from sonoran.coverage.render import COVER_ALPHA, MARGIN_ENCODING, RAMP, RAMP_SPAN_DB
from sonoran.db.models import CoverageCalibration, CoverageCalibrationNode
from sonoran.logging import get_logger
from sonoran.radio.resolve import clamp_calibration

logger = get_logger(__name__)

# How many finished runs to keep.
#
# Two is enough to serve the old one while the new one is written, and
# to look at what changed. Tiles are large, so more would cost disk for
# nothing.
KEEP_RUNS = 2

# What a run stamp looks like.
#
# The value is read from a file and becomes part of a path. Nothing
# else writes that file, so this is not a hole today. It is checked
# anyway, because a path built from a value read off disk is the shape
# of a hole, and the check costs nothing.
STAMP_PATTERN = re.compile(r"^\d{8}T\d{6}Z$")

INDEX_NAME = "index.json"
MANIFEST_NAME = "manifest.json"
CALIBRATION_NAME = "calibration.json"

# The level each run predicted at each node it considered.
#
# A finished run keeps no level grid. `_build_site_set` holds the region
# grids in RAM, renders colour ramped PNG tiles, and deletes them, and a
# tile whose coverage is entirely below the threshold is never written
# at all. So the exact dBm at a point cannot be recovered from disk
# after a run, and reading it back from an alpha channel at zoom 11
# gives a boolean where a margin is wanted.
#
# The job therefore samples the grids while they are still in memory and
# writes this beside the manifest. It is tens of kilobytes: a few
# thousand nodes, two or three presets, two site sets, three layers.
NODE_LEVELS_NAME = "coverage-at-nodes.json"

# The layers a run writes.
#
# `usable` is the honest one and the one a page shows first. It is the
# weaker of the two directions, so it answers "can I use the mesh from
# here", which is what somebody looking at a coverage map wants to know.
LAYERS = ("usable", "downlink", "uplink")

# The directory of the margin tiles, inside the directory of a layer.
MARGIN_DIR = "margin"

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
    # How many sites the run predicted from.
    node_count: int
    # Every positioned node on this preset, before the role test.
    candidate_count: int
    # The sites the run used, after the cap.
    site_count: int
    # Sites dropped by `coverage_max_nodes`, and nothing else.
    skipped_count: int
    # How many nodes each role lost. A node with no role is counted
    # under `NULL`. See `sonoran/roles.py`: that is a client, not an
    # unknown, and the page must be able to say how many there were.
    excluded_by_role: dict[str, int]
    usable_area_km2: float
    downlink_area_km2: float
    tile_count: int
    # The box the usable coverage sits in. None when nothing is
    # covered. The page opens on this rather than on the whole region.
    data_bounds: list[float] | None = None
    nodes: list[dict[str, object]] = field(default_factory=list)


@dataclass
class SiteSetSummary:
    """One map of the mesh, from one set of site roles.

    A run publishes the infrastructure map always, and the wider map
    that includes the nodes which repeat when
    `COVERAGE_INCLUDE_CLIENTS` is on. They answer different questions
    and each carries its own presets, areas and tiles.

    `is_diagnostic` is true for any set that is not a subset of the
    infrastructure roles. The public embed serves the infrastructure
    set and nothing else, whatever this says. See `AGENTS.md` 9.25.
    """

    key: str
    label: str
    site_roles: list[str]
    is_diagnostic: bool
    presets: list[PresetSummary] = field(default_factory=list)
    data_bounds: list[float] | None = None
    # The position rule this map was predicted with: `precise`, or
    # `approximate` for the extra map `COVERAGE_INCLUDE_APPROXIMATE`
    # adds. `approximate` is true for the second, so a reader has one
    # flag to test. A run made before #315 has neither field.
    site_precision: str = "precise"
    approximate: bool = False


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
    calibrated_nodes: int
    missing_terrain_tiles: list[str]
    seconds: float
    # The dB above the sensitivity that the colour ramp spans.
    #
    # Python writes the tiles, so Python owns this. The pages read it
    # from here rather than each holding a copy, because two copies
    # drift and a legend that disagrees with its map is worse than no
    # legend. See `coverage/render.py`.
    ramp_span_db: float = RAMP_SPAN_DB
    # The degrees of the region with no land cover page. Clutter is
    # charged nowhere in these, so `has_landcover` is false while any
    # remain.
    missing_landcover_tiles: list[str] = field(default_factory=list)
    # The roles this run predicted from, and whether that set is the
    # infrastructure one.
    #
    # A diagnostic run predicts from handhelds and from nodes that
    # never said what they are, and it is useful for exactly that. It
    # is not a coverage map, and a reader who opens the page a week
    # later has no way to know which they are looking at unless the run
    # carries it. Both the dashboard and the public embed read this and
    # label the map. See `sonoran/roles.py`.
    site_roles: list[str] = field(default_factory=list)
    is_diagnostic: bool = False
    # The nodes left out because the broker rounded their position off.
    #
    # A count alone is not actionable. The page tells an operator to
    # write a position in `config/nodes.yaml` for each of these, and
    # "34 of those" is not an instruction anybody can follow. Each
    # entry carries the rounded position, which is enough to recognise
    # a site by, and the deviation, which says how wrong it is.
    #
    # Bounded by `COARSE_REPORT_LIMIT`. The count in
    # `PresetSummary.excluded_by_role` is always the whole number.
    coarse_sites: list[dict[str, object]] = field(default_factory=list)
    data_bounds: list[float] | None = None
    presets: list[PresetSummary] = field(default_factory=list)
    # Every map this run published, the infrastructure one first.
    #
    # `presets` above stays the infrastructure map on its own. The
    # embed and anything else that must never widen reads that field
    # and cannot reach a client map through it, which is the property
    # `AGENTS.md` 9.25 asks for: the narrow answer is the one a reader
    # gets without asking for anything else.
    site_sets: list[SiteSetSummary] = field(default_factory=list)
    # How this run's margin tiles are encoded, and the ramp and alpha
    # to colour them with. See `margin_spec`.
    #
    # None for a run made before the margin tiles existed. A reader
    # reads that as "this run cannot draw a signal floor", and still
    # draws its colour tiles. The public embed never reads this field.
    margin_tiles: dict[str, object] | None = None


def margin_spec() -> dict[str, object]:
    """Return what a page needs to colour a margin tile.

    The ramp and the alpha are the ones `colour_levels` uses, sent from
    here so the page holds no copy of its own. Python writes the tiles,
    so Python owns the colours. `ramp_span_db` is already in the
    manifest beside this.
    """
    return {
        "encoding": MARGIN_ENCODING,
        "ramp": [list(colour) for colour in RAMP],
        "alpha": COVER_ALPHA,
    }


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


def tile_path(
    root: Path, preset: str, site_set: str, layer: str, zoom: int, x: int, y: int
) -> Path:
    """Return where one tile of a run sits.

    The site set is part of the path because one run can publish more
    than one map of the same preset: the infrastructure map, and the
    wider one that includes the nodes which repeat. They are different
    answers and must never share a tile.
    """
    return root / preset / site_set / layer / str(zoom) / str(x) / f"{y}.png"


def margin_tile_path(
    root: Path, preset: str, site_set: str, layer: str, zoom: int, x: int, y: int
) -> Path:
    """Return where the margin tile of one tile sits.

    The `margin` directory is inside the layer, where every other entry
    is a zoom level. A path built from a whole number zoom can never
    reach it.
    """
    return root / preset / site_set / layer / MARGIN_DIR / str(zoom) / str(x) / f"{y}.png"


def write_tile(
    root: Path,
    preset: str,
    site_set: str,
    layer: str,
    zoom: int,
    x: int,
    y: int,
    png: bytes,
) -> None:
    """Write one tile."""
    path = tile_path(root, preset, site_set, layer, zoom, x, y)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png)


def write_margin_tile(
    root: Path,
    preset: str,
    site_set: str,
    layer: str,
    zoom: int,
    x: int,
    y: int,
    png: bytes,
) -> None:
    """Write the margin tile of one tile."""
    path = margin_tile_path(root, preset, site_set, layer, zoom, x, y)
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


def clear_pending(settings: Settings, keep: str | None = None) -> int:
    """Delete every half built run but one. Return how many went.

    A run is built under `pending-{stamp}` and renamed only when it is
    whole, so a run that dies leaves its directory behind. Nothing
    published it, so `prune` never sees it: `prune` reads `runs`, and
    this sits beside it.

    That is a slow disk leak. A run of the Arizona mesh writes 16 MB,
    and a job that fails every six hours adds that four times a day
    until the volume fills. It has happened here once already, when a
    run was ended by the memory killer.

    A run calls this before it starts, rather than after it finishes,
    because a run that fails never reaches its own end. At most one
    dead run is on the disk at a time.
    """
    root = Path(settings.coverage_cache_dir)
    if not root.is_dir():
        return 0
    removed = 0
    for path in root.glob("pending-*"):
        if not path.is_dir() or (keep is not None and path.name == f"pending-{keep}"):
            continue
        shutil.rmtree(path, ignore_errors=True)
        removed += 1
        logger.info("removed a coverage run that never finished: %s", path.name)
    return removed


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
    if not isinstance(stamp, str) or not STAMP_PATTERN.fullmatch(stamp):
        return None
    return stamp


def current_root(settings: Settings) -> Path | None:
    """Return the directory of the current run, or None."""
    stamp = current_stamp(settings)
    if stamp is None:
        return None
    return run_root(settings, stamp)


def run_root(settings: Settings, stamp: str) -> Path | None:
    """Return one named run directory, or None.

    The stamp comes from a URL for tile reads. Check it before it
    becomes part of a path.
    """
    if not STAMP_PATTERN.fullmatch(stamp):
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


def write_node_levels(root: Path, document: dict[str, object]) -> None:
    """Write the sampled level of each node into a run being built.

    The file goes into the pending directory, so the run's own rename
    publishes it. There is no separate write and no second rename, which
    means a reader can never see this file without the manifest that
    explains it, or a level from one run beside a stamp from another.
    """
    root.mkdir(parents=True, exist_ok=True)
    (root / NODE_LEVELS_NAME).write_text(json.dumps(document, indent=1), encoding="utf-8")


def read_node_levels(settings: Settings) -> dict[str, object] | None:
    """Return the sampled node levels of the current run, or None.

    None when no run has been published, or when the run was made before
    this file existed. That is a working state: the signal that reads it
    answers `unknown` and says why, rather than guessing that a node
    with no entry has no coverage.

    **A node absent from the document is unknown, not zero.** A node
    outside the region grid is simply not in it. A stored zero is
    different and is a real answer: `grid.NO_COVERAGE`, meaning the run
    reached that cell and found nothing there.
    """
    root = current_root(settings)
    if root is None:
        return None
    try:
        document = json.loads((root / NODE_LEVELS_NAME).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as error:
        logger.warning("cannot read the coverage node levels: %s", error)
        return None
    return document if isinstance(document, dict) else None


def read_tile(
    settings: Settings, preset: str, site_set: str, layer: str, zoom: int, x: int, y: int
) -> bytes | None:
    """Return one tile of the current run, or None.

    A tile that was never written is ground no node reaches. The API
    answers those with a 404 and the map draws nothing there.
    """
    stamp = current_stamp(settings)
    if stamp is None:
        return None
    return read_run_tile(settings, stamp, preset, site_set, layer, zoom, x, y)


def read_run_tile(
    settings: Settings,
    stamp: str,
    preset: str,
    site_set: str,
    layer: str,
    zoom: int,
    x: int,
    y: int,
) -> bytes | None:
    """Return one tile from one named run, or None.

    A stamped URL must always identify the same bytes. It must not move
    to the current run when a new run is published.
    """
    root = run_root(settings, stamp)
    if root is None:
        return None
    return _read_bytes(tile_path(root, preset, site_set, layer, zoom, x, y))


def read_run_margin_tile(
    settings: Settings,
    stamp: str,
    preset: str,
    site_set: str,
    layer: str,
    zoom: int,
    x: int,
    y: int,
) -> bytes | None:
    """Return the margin tile of one tile of one named run, or None.

    None also for a run made before the margin tiles existed. The page
    knows that from the manifest and does not ask.
    """
    root = run_root(settings, stamp)
    if root is None:
        return None
    return _read_bytes(margin_tile_path(root, preset, site_set, layer, zoom, x, y))


def _read_bytes(path: Path) -> bytes | None:
    """Return the bytes of a file, or None when it cannot be read."""
    try:
        return path.read_bytes()
    except (OSError, ValueError):
        return None


# --- the calibration ---------------------------------------------------
#
# The calibration lives in two tables (#351): `coverage_calibration`
# holds the fit as a whole, one row or none, and
# `coverage_calibration_node` holds one row per node. The calibration job
# replaces both in one transaction, so a reader sees the old fit or the
# new one and never half of each. The coverage job and the API read it.
#
# It used to be `calibration.json` beside the runs. The jobs process
# imports that file once when the tables are empty, see
# `sonoran/jobs/legacy_import.py`, which is the only reader of the path.


def calibration_path(settings: Settings) -> Path:
    """Return where the calibration file was kept, before #351."""
    return Path(settings.coverage_cache_dir) / CALIBRATION_NAME


def read_calibration_file(settings: Settings) -> dict[str, object] | None:
    """Return the calibration file of a box from before #351, or None."""
    try:
        document = json.loads(calibration_path(settings).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return document if isinstance(document, dict) else None


async def write_calibration(
    session: AsyncSession, calibration: Calibration, summary: dict[str, float]
) -> None:
    """Replace the calibration with a new fit, and commit."""
    await write_calibration_document(
        session,
        {
            "generated_at": datetime.now(UTC).isoformat(),
            "summary": summary,
            **asdict(calibration),
        },
    )
    logger.info("wrote the calibration for %s nodes", len(calibration.nodes))


async def write_calibration_document(session: AsyncSession, document: dict[str, object]) -> bool:
    """Replace the calibration with a document of the old file's shape.

    Return False, and change nothing, when the document is not a fit.
    """
    try:
        generated = datetime.fromisoformat(str(document["generated_at"]))
        bias = float(document["model_bias_db"])  # type: ignore[arg-type]
        spread = float(document.get("residual_spread_db") or 0.0)  # type: ignore[arg-type]
        rounds = int(document.get("rounds") or 0)  # type: ignore[call-overload]
    except (KeyError, TypeError, ValueError):
        logger.warning("refusing to store a calibration that is not a fit")
        return False
    rows: list[dict[str, object]] = []
    listed = document.get("nodes")
    for item in listed if isinstance(listed, list) else []:
        if not isinstance(item, dict):
            continue
        node_id = item.get("node_id")
        if not isinstance(node_id, str) or not re.fullmatch(r"![0-9a-fA-F]{8}", node_id):
            continue
        try:
            rows.append(
                {
                    "node_num": int(node_id[1:], 16),
                    "offset_db": float(item["offset_db"]),
                    "observations": int(item.get("observations") or 0),
                    "counterparties": int(item.get("counterparties") or 0),
                    "censored": int(item.get("censored") or 0),
                    "reported": int(item.get("reported") or 0),
                    "residual_spread_db": float(item.get("residual_spread_db") or 0.0),
                    "locked": item.get("locked") is True,
                }
            )
        except (KeyError, TypeError, ValueError):
            continue
    summary = document.get("summary")
    await session.execute(delete(CoverageCalibrationNode))
    await session.execute(delete(CoverageCalibration))
    await session.execute(
        insert(CoverageCalibration).values(
            id=1,
            generated_at=generated,
            model_bias_db=bias,
            residual_spread_db=spread,
            rounds=rounds,
            summary=summary if isinstance(summary, dict) else {},
        )
    )
    if rows:
        await session.execute(insert(CoverageCalibrationNode), rows)
    await session.commit()
    return True


async def clear_calibration(session: AsyncSession) -> None:
    """Remove a stale calibration when the current window has none."""
    await session.execute(delete(CoverageCalibrationNode))
    await session.execute(delete(CoverageCalibration))
    await session.commit()


async def read_calibration(session: AsyncSession) -> dict[str, object] | None:
    """Return the calibration, or None when there is none.

    The shape is the old file's, so a reader written for the file reads
    it unchanged. A deployment that has never run the job has none, and
    the prediction then uses the nameplate figures.
    """
    fit = await session.scalar(select(CoverageCalibration).where(CoverageCalibration.id == 1))
    if fit is None:
        return None
    nodes = (
        await session.scalars(
            select(CoverageCalibrationNode).order_by(CoverageCalibrationNode.node_num)
        )
    ).all()
    return {
        "generated_at": fit.generated_at.isoformat(),
        "summary": fit.summary,
        "model_bias_db": fit.model_bias_db,
        "nodes": [
            {
                "node_id": f"!{node.node_num:08x}",
                "offset_db": node.offset_db,
                "observations": node.observations,
                "counterparties": node.counterparties,
                "censored": node.censored,
                "reported": node.reported,
                "residual_spread_db": node.residual_spread_db,
                "locked": node.locked,
            }
            for node in nodes
        ],
        "rounds": fit.rounds,
        "residual_spread_db": fit.residual_spread_db,
    }


async def calibration_offsets(session: AsyncSession) -> dict[str, float]:
    """Return the offsets that have enough evidence, by node ID.

    This is what a prediction reads. See `offsets_of`.
    """
    document = await read_calibration(session)
    return {} if document is None else offsets_of(document)


def offsets_of(document: dict[str, object]) -> dict[str, float]:
    """Return the offsets of a calibration that have enough evidence, by node ID.

    A node with thin evidence is absent rather than present with a
    zero, so a caller can tell "measured and found to be right" from
    "never measured".
    """
    raw_bias = document.get("model_bias_db")
    bias = float(raw_bias) if isinstance(raw_bias, int | float) else math.nan
    # A fit whose measurements disagree this widely is not describing
    # the mesh. Correcting on it would move the map on noise.
    raw_spread = document.get("residual_spread_db")
    spread = float(raw_spread) if isinstance(raw_spread, int | float) else math.nan
    if (
        not math.isfinite(bias)
        or abs(bias) > MAX_TRUSTED_BIAS_DB
        or not math.isfinite(spread)
        or spread > MAX_TRUSTED_SPREAD_DB
    ):
        logger.warning(
            "the calibration bias is %.1f dB and scatter is %.1f dB, "
            "so the nameplate figures are used",
            bias,
            spread,
        )
        return {}
    offsets: dict[str, float] = {}
    nodes = document.get("nodes")
    if not isinstance(nodes, list):
        return {}
    for item in nodes:
        if not isinstance(item, dict):
            continue
        try:
            observations = int(item.get("observations") or 0)
            counterparties = int(item.get("counterparties") or 0)
            reported = int(item.get("reported") or 0)
            node_spread = float(item.get("residual_spread_db") or 0.0)
        except (TypeError, ValueError):
            continue
        # A pinned node is fitted at zero and never applied. The file
        # says so, and the reader checks it as well as the resolver, so
        # a stale file from before a lock was added cannot move the map.
        if item.get("locked") is True:
            continue
        usable = (
            observations >= MIN_OBSERVATIONS
            and counterparties >= MIN_COUNTERPARTIES
            and reported >= MIN_REPORTED
            and math.isfinite(node_spread)
            and node_spread <= MAX_TRUSTED_SPREAD_DB
        )
        node_id = item.get("node_id")
        if usable and isinstance(node_id, str):
            try:
                offset = float(item["offset_db"])
            except (KeyError, TypeError, ValueError):
                continue
            if math.isfinite(offset):
                offsets[node_id] = clamp_calibration(offset)
    return offsets
