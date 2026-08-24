"""The coverage job.

The job predicts from every node the mesh reports and writes the result
as map tiles.

It runs once for each modem preset. A node on Long fast cannot hear a
node on Medium fast, so merging their coverage would draw a mesh that
does not exist. See `AGENTS.md` 9.7. The preset also sets the receiver
sensitivity, so it is part of the run and not a filter on the display.

Each node gives one engine run and two layers. See
`sonoran/coverage/sites.py` for why one run is enough for both
directions.

The engine is a tight loop of floating point and holds the processor
for a second or so at a time, so the whole build runs in a worker
thread. Running it on the event loop would stop the jobs process. The
sites themselves are divided over worker processes.
"""

import asyncio
import multiprocessing
import os
import time
from collections import Counter, OrderedDict
from collections.abc import Sequence
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import partial
from pathlib import Path

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sonoran.config import Settings, get_settings
from sonoran.coverage import store
from sonoran.coverage.clutter import loss_by_class
from sonoran.coverage.engine import MASK_COVERED, EngineError, SplatInstance, SplatModule
from sonoran.coverage.grid import (
    MAX_LEVEL,
    MIN_LEVEL,
    NO_COVERAGE,
    Grid,
    Levels,
    blit_max,
    combine_min,
    covered_area_km2,
    data_bounds,
    levels_from_raster,
    region_grid,
    union_bounds,
)
from sonoran.coverage.params import DEFAULT_FREQUENCY_MHZ
from sonoran.coverage.render import (
    colour_levels,
    sample_tile,
    tiles_for_grid,
    write_png,
)
from sonoran.coverage.sites import (
    HANDHELD_TX_POWER_DBM,
    Site,
    downlink_offset_db,
    engine_params,
    make_site,
    uplink_offset_db,
)
from sonoran.db.models import Node
from sonoran.db.session import make_engine, make_session_factory
from sonoran.landcover.store import PAGE_SIZE, class_page, have_pages
from sonoran.landcover.store import tile_name as landcover_tile_name
from sonoran.logging import configure_logging, get_logger
from sonoran.positions import is_precise_enough, is_usable, precision_deviation_m
from sonoran.radio.overrides import EMPTY as EMPTY_OVERRIDES
from sonoran.radio.overrides import Overrides, load_overrides
from sonoran.radio.presets import ModemPreset, preset_by_key, preset_for_channel
from sonoran.radio.resolve import resolve_profile
from sonoran.roles import (
    EVERY_ROLE,
    SITE_SET_EXTENDED,
    SITE_SET_INFRASTRUCTURE,
    SITE_SET_LABELS,
    is_diagnostic_role_set,
    is_site_role,
    parse_site_roles,
    role_name,
    site_set_roles,
)
from sonoran.terrain.store import coordinates_in_region, load_page, read_cached_page

logger = get_logger(__name__)

# How many nodes to report by name in the manifest.
#
# The page lists the sites a run used. A mesh of several hundred does
# not need every one of them in a document the browser downloads.
MANIFEST_NODE_LIMIT = 250

# What a node left out for a fuzzed position is counted under.
#
# It sits beside the role names in the same report. A role can never
# take this value, so the two cannot collide.
COARSE_POSITION = "coarse-position"

# How many coarse sites the manifest names.
#
# The list exists so an operator can fix them, and nobody fixes two
# hundred by hand. The count beside it is always the whole number, so a
# shortened list cannot read as the whole story.
COARSE_REPORT_LIMIT = 50


def worker_count(settings: Settings) -> int:
    """Return how many worker processes to predict with.

    Zero in the setting means as many as the machine has, less one, so
    the jobs process keeps a core for everything else it does.
    """
    if settings.coverage_workers > 0:
        return settings.coverage_workers
    return max(1, (os.cpu_count() or 2) - 1)


async def select_nodes(
    session: AsyncSession, settings: Settings, overrides: Overrides = EMPTY_OVERRIDES
) -> Sequence[Node]:
    """Return the nodes a run may predict from.

    A node needs a position to be a transmitter. A node the mesh has not
    heard from for a long time is left out, because a node that is gone
    must not hold coverage open on the map.

    The position an operator gave is used for this test as well. A node
    whose reported position is missing or nonsense is exactly the node
    an operator writes a position for, and testing the reported one
    first would drop it before the file was ever read.
    """
    since = datetime.now(UTC) - timedelta(hours=settings.coverage_active_hours)
    rows = await session.scalars(
        select(Node).where(Node.last_heard.is_not(None), Node.last_heard >= since)
    )

    def is_in_region(node: Node) -> bool:
        given = overrides.position_of(f"!{node.node_num:08x}")
        latitude, longitude = given if given else (node.last_lat, node.last_lon)
        if latitude is None or longitude is None or not is_usable(latitude, longitude):
            return False
        return coordinates_in_region(settings, latitude, longitude)

    return [node for node in rows.all() if is_in_region(node)]


def group_by_preset(
    settings: Settings,
    nodes: Sequence[Node],
    overrides: Overrides,
    offsets: dict[str, float] | None = None,
    allowed: frozenset[str] | None = None,
) -> tuple[dict[str, list[Site]], dict[str, Counter[str]], list[dict[str, object]]]:
    """Return the sites of each preset, strongest first, what was left
    out of each, and the nodes left out for a coarse position.

    A node whose channel is not a preset name rides on top of a preset
    and does not name one. Weather and PKI are the examples this mesh
    has. Such a node is left out rather than guessed at, because putting
    it on the wrong preset draws a link that cannot exist.

    A node whose role is not in `COVERAGE_SITE_ROLES` is left out as
    well. The default is the infrastructure set, because only a node
    that stays where it is can hold coverage open. See
    `sonoran/roles.py` for why a missing role is a client and not an
    unknown, and for the `ALL` diagnostic that turns the test off.

    So is a node whose position is known to be coarse. The public
    Meshtastic broker fuzzes a position by up to 23 km, and the terrain
    under a prediction is 90 m across.

    The counts come back beside the groups, and not as a log line,
    because the manifest has to report them. A run that quietly drops
    nine nodes in ten must say so on the page.
    """
    # `allowed` of None here means "read the setting", which is the
    # single-map case. It is not the same as `parse_site_roles`
    # returning None, which means every role. The sentinel is resolved
    # before anything reads it, so the two never meet.
    if allowed is None:
        allowed = parse_site_roles(settings.coverage_site_roles)
    groups: dict[str, list[Site]] = {}
    left_out: dict[str, Counter[str]] = {}
    coarse: list[dict[str, object]] = []
    for node in nodes:
        preset = preset_for_channel(node.last_channel)
        if preset is None:
            continue
        rejected = left_out.setdefault(preset.key, Counter())
        if not is_site_role(node.role, allowed):
            rejected[role_name(node.role)] += 1
            continue
        identifier = f"!{node.node_num:08x}"
        # An operator who says where their own router is beats the
        # broker, which fuzzes what it relays.
        given = overrides.position_of(identifier)
        if given is None and not is_precise_enough(
            node.last_position_precision_bits, settings.coverage_min_precision_bits
        ):
            # The node said where it is, and said the answer is coarse.
            # A footprint drawn around it would describe ground that
            # may have no radio on it. See `sonoran/positions.py`.
            rejected[COARSE_POSITION] += 1
            # And keep it, so the page can name it. Telling an operator
            # to write a position for "34 of those" and not saying
            # which is not an instruction anybody can follow. The
            # rounded position is what there is, and it is enough to
            # recognise a site by.
            if (
                len(coarse) < COARSE_REPORT_LIMIT
                and node.last_lat is not None
                and node.last_lon is not None
            ):
                coarse.append(
                    {
                        "node_id": identifier,
                        "display_name": node.long_name or node.short_name or identifier,
                        "role": role_name(node.role),
                        "precision_bits": node.last_position_precision_bits,
                        "deviation_m": precision_deviation_m(node.last_position_precision_bits),
                        "rounded_lat": round(node.last_lat, 4),
                        "rounded_lon": round(node.last_lon, 4),
                    }
                )
            continue
        profile = resolve_profile(
            identifier,
            node.hw_model,
            overrides,
            (offsets or {}).get(identifier),
            role=node.role,
        )
        latitude, longitude = given if given else (node.last_lat, node.last_lon)
        if latitude is None or longitude is None:
            continue
        site = make_site(
            settings,
            identifier,
            node.node_num,
            node.long_name or node.short_name or identifier,
            latitude,
            longitude,
            profile,
            preset,
        )
        groups.setdefault(preset.key, []).append(site)

    for sites in groups.values():
        sites.sort(key=lambda site: site.sort_key, reverse=True)
    # Coarsest first. That is the order to fix them in: the node whose
    # position is 23 km out is the one moving the map most.
    coarse.sort(key=lambda item: -float(item["deviation_m"] or 0.0))  # type: ignore[arg-type]
    return groups, left_out, coarse


def _tile_name(latitude: int, longitude: int) -> str:
    """Return the SRTM tile name of one whole degree."""
    north_south = "N" if latitude >= 0 else "S"
    east_west = "E" if longitude >= 0 else "W"
    return f"{north_south}{abs(latitude):02d}{east_west}{abs(longitude):03d}"


def tiles_around(site: Site, radius_km: float) -> set[str]:
    """Return every terrain tile a site could reach into.

    A degree of latitude is about 111 km. One extra degree on each side
    covers the rounding and the way a degree of longitude narrows as it
    goes north.
    """
    reach = radius_km / 111.0 + 1.0
    lat_from = int(np.floor(site.latitude - reach))
    lat_to = int(np.floor(site.latitude + reach))
    lon_from = int(np.floor(site.longitude - reach))
    lon_to = int(np.floor(site.longitude + reach))
    return {
        _tile_name(latitude, longitude)
        for latitude in range(lat_from, lat_to + 1)
        for longitude in range(lon_from, lon_to + 1)
    }


async def ensure_terrain(settings: Settings, names: Sequence[str]) -> set[str]:
    """Put every terrain page on the disk cache. Return the names held.

    The bytes are not kept. A page is 2.7 MB and a run over Arizona
    wants about forty of them, so holding the set costs more than a
    hundred megabytes, and every worker process would take a copy of it.
    The workers read the pages they need from the disk cache instead.
    See `docs/COVERAGE.md` 9.2.

    A tile the service does not hold is absent from the answer. The
    engine reads a page it never got as sea level, so the run draws
    coverage over flat ground there. The manifest names those tiles, so
    a page can say so.
    """
    held: set[str] = set()
    for name in dict.fromkeys(names):
        try:
            page = await load_page(settings, name)
        except Exception as error:  # a bad tile must not stop the run
            logger.warning("terrain page %s could not be read: %s", name, error)
            continue
        if page is not None:
            held.add(name)
    return held


# How many terrain pages one process holds in memory.
#
# One engine run at a 60 km radius reads about nine pages, and the sites
# of a preset are predicted one after another over ground that mostly
# repeats, so a small hold serves nearly every read. This bounds the
# terrain a worker costs at about 43 MB whatever the size of the region.
PAGE_CACHE_SIZE = 16

_page_cache: OrderedDict[str, bytes | None] = OrderedDict()


def read_page(settings: Settings, name: str) -> bytes | None:
    """Return one terrain page from the disk cache.

    A page that is absent or damaged gives None, which the caller
    reports as a missing tile.
    """
    if name in _page_cache:
        _page_cache.move_to_end(name)
        return _page_cache[name]
    try:
        page = read_cached_page(settings, name)
    except Exception as error:  # a bad tile must not stop the run
        logger.warning("terrain page %s could not be read: %s", name, error)
        page = None
    _page_cache[name] = page
    while len(_page_cache) > PAGE_CACHE_SIZE:
        _page_cache.popitem(last=False)
    return page


def _site_levels(
    instance: SplatInstance,
    settings: Settings,
    site: Site,
) -> tuple[Levels, Grid, list[str]] | None:
    """Return the field one site puts on the ground.

    The levels are the engine field, before either direction's offset.
    Returns None when the engine refuses the run.
    """
    params = engine_params(settings, site)
    missing: list[str] = []
    try:
        with instance.run(params) as run:
            refs = run.pages()
            for index, ref in enumerate(refs):
                page = read_page(settings, ref.tile_name)
                if page is None:
                    missing.append(ref.tile_name)
                    continue
                run.load_page(index, page)
            run.run_all_radials()
            run.rasterize()
            raster = run.raster()
    except EngineError as error:
        logger.warning("the engine refused %s: %s", site.node_id, error)
        return None

    region = raster.region
    levels = levels_from_raster(
        raster.signal, raster.mask, MASK_COVERED, region.width, region.height
    )
    grid = Grid(north=region.north, west=region.west, width=region.width, height=region.height)
    return levels, grid, missing


def _shift(levels: Levels, offset_db: float) -> Levels:
    """Return the levels moved by a number of dB, keeping the gaps.

    A cell nothing reached stays unreached. Moving it would turn a hole
    in the coverage into a very weak signal.
    """
    if round(offset_db) == 0:
        return levels
    moved = np.clip(levels.astype(np.int16) + round(offset_db), MIN_LEVEL, MAX_LEVEL)
    return np.where(levels == NO_COVERAGE, NO_COVERAGE, moved).astype(np.uint8)


# One engine instance for each worker process.
#
# Compiling the module costs more than a prediction does, so a worker
# does it once when it starts. The instance is held too, and this is
# the part that matters: an instance owns a linear memory that grows to
# the largest run it has made, and a new one for each site grows a new
# heap of several hundred megabytes that is never given back. That is
# what the memory killer ended a three hundred node run on. See
# `AGENTS.md` 9.16.4.
_WORKER_MODULE: SplatModule | None = None
_WORKER_INSTANCE: SplatInstance | None = None

# What one site sends back from a worker.
#
# Everything crossing a process boundary is pickled, so the levels go
# back as bytes and the grid as four numbers rather than as objects.
SiteResult = tuple[bytes, int, int, float, float, list[str]]


def _pool_context() -> multiprocessing.context.BaseContext:
    """Return the way to start a worker process.

    Spawn, and never fork. `_build` runs in a worker thread, because
    the engine would otherwise hold the event loop of the whole jobs
    process. Fork copies only the thread that calls it, so a lock any
    other thread held at that moment is held for ever in the child. The
    logging lock is the one that does it here, and this job logs from
    the main thread while it works.

    A forked worker then blocks before it runs a single instruction of
    `_worker_start`. There is no error and no timeout: the run simply
    never finishes, and the scheduler waits on a task that never
    returns. Spawn starts a new interpreter and inherits no locks.

    `test_a_run_over_worker_processes_answers_the_same` found this. See
    `AGENTS.md` 9.16.5.
    """
    return multiprocessing.get_context("spawn")


def _worker_start(nice: int = 0) -> None:
    """Set up one worker process.

    Only the engine is made here, and the niceness. The terrain a worker
    needs is read from the disk cache as the work asks for it, because
    sending the pages through the pool would copy the whole region into
    every process. Nothing else may be passed through this initialiser:
    an argument crosses to every worker at start up.

    The niceness is why an argument is taken at all. The engine is a
    solid floating point loop, so a run pins every worker for minutes,
    and on a machine that also serves the dashboard and takes MQTT that
    is felt by everybody using it. A niced worker still gets every idle
    cycle and hands the CPU straight back to anything interactive.
    """
    global _WORKER_MODULE, _WORKER_INSTANCE
    _be_nice(nice)
    _WORKER_MODULE = SplatModule()
    _WORKER_INSTANCE = _WORKER_MODULE.instance()


def _be_nice(nice: int) -> None:
    """Lower the priority of this process, where the platform has it.

    Never raised. A process cannot restore its own priority without
    privilege, so a negative value is refused rather than acted on and
    then regretted. A platform with no `os.nice` is left alone.
    """
    if nice <= 0 or not hasattr(os, "nice"):
        return
    try:
        os.nice(nice)
    except OSError as error:  # pragma: no cover - depends on the host
        logger.debug("could not lower the worker priority: %s", error)


def _to_plain(computed: tuple[Levels, Grid, list[str]] | None) -> SiteResult | None:
    """Return a prediction in the shape that crosses a process."""
    if computed is None:
        return None
    levels, grid, missing = computed
    return (levels.tobytes(), grid.width, grid.height, grid.north, grid.west, missing)


def _worker_site(settings: Settings, site: Site) -> SiteResult | None:
    """Predict one site in a worker process."""
    assert _WORKER_INSTANCE is not None
    return _to_plain(_site_levels(_WORKER_INSTANCE, settings, site))


def predict_preset(
    settings: Settings,
    grid: Grid,
    sites: Sequence[Site],
    workers: int,
) -> tuple[Levels, Levels, Levels, list[dict[str, object]], set[str]]:
    """Predict one preset from every site on it.

    Returns the downlink grid, the uplink grid, the usable grid, a note
    about each site, and the terrain tiles that were missing.

    The engine runs in worker processes. One site takes a few seconds of
    solid floating point, and a mesh of several hundred would take the
    better part of an hour on one core. The work divides cleanly,
    because each site is its own prediction and none of them reads
    another.

    A worker that dies takes the whole pool with it, and the usual cause
    is memory on a small machine. That must cost time, not the run, so
    the preset is then predicted again in this process alone. The
    accumulators are made inside `_predict`, so the retry starts from
    empty ground and never counts a site twice.
    """
    if workers >= 1:
        try:
            return _predict(settings, grid, sites, workers)
        except BrokenProcessPool:
            logger.warning(
                "a worker process died, so this preset is predicted in this "
                "process instead. The usual cause is memory."
            )
    # Zero means here, in the jobs process, and is the crash fallback
    # rather than a setting. One worker is still a worker: it is the
    # answer for a small box, and it is niced, which a run inside the
    # jobs process could not be without slowing every other job down.
    return _predict(settings, grid, sites, 0)


def _predict(
    settings: Settings,
    grid: Grid,
    sites: Sequence[Site],
    workers: int,
) -> tuple[Levels, Levels, Levels, list[dict[str, object]], set[str]]:
    """Predict one preset with a given number of processes.

    The results are put on the region grid here, in the order the sites
    were given, so the answer never depends on which worker finished
    first.

    Three layers come back, and `usable` is built here rather than from
    the other two. See the note on it below.
    """
    downlink = grid.empty()
    uplink = grid.empty()
    usable = grid.empty()
    notes: list[dict[str, object]] = []
    missing: set[str] = set()
    down_offset = downlink_offset_db(settings)

    def take(index: int, site: Site, computed: SiteResult | None) -> None:
        if computed is None:
            notes.append({"node_id": site.node_id, "used": False, "reason": "engine refused"})
            return
        raw, width, height, north, west, site_missing = computed
        levels = np.frombuffer(raw, dtype=np.uint8).reshape(height, width)
        site_grid = Grid(north=north, west=west, width=width, height=height)
        missing.update(site_missing)

        # The clutter around the node costs the same at both ends,
        # because it is a loss on this end of every path.
        here = site.clutter_loss_db
        down_here = _shift(levels, down_offset - here)
        up_here = _shift(levels, uplink_offset_db(settings, site) - here)
        added_down = blit_max(downlink, grid, down_here, site_grid)
        added_up = blit_max(uplink, grid, up_here, site_grid)
        # `usable` is the weaker direction **of one node**, and only
        # then the best node. Taking the best of each direction first
        # and the weaker of the two afterwards lets one node answer for
        # the downlink and another for the uplink, and paints a place
        # as usable both ways where no single node closes both. A tall
        # router a handheld cannot answer, beside a solar node the
        # handheld can reach but which cannot be heard, is exactly that
        # place, and the mesh does not work there.
        blit_max(usable, grid, combine_min(down_here, up_here), site_grid)
        notes.append(
            {
                "node_id": site.node_id,
                "display_name": site.display_name,
                "used": True,
                "eirp_dbm": round(site.profile.effective_eirp_dbm, 1),
                "antenna_height_m": site.profile.antenna_height_m,
                "clutter_height_m": site.clutter_height_m,
                "clutter_loss_db": round(site.clutter_loss_db, 1),
                "calibrated": site.profile.is_measured,
                "cells_set": added_down,
                "cells_set_uplink": added_up,
            }
        )
        if (index + 1) % 25 == 0:
            logger.info("  %s of %s sites", index + 1, len(sites))

    if workers < 1:
        with SplatModule().instance() as instance:
            for index, site in enumerate(sites):
                take(index, site, _to_plain(_site_levels(instance, settings, site)))
        return downlink, uplink, usable, notes, missing

    with ProcessPoolExecutor(
        max_workers=workers,
        initializer=_worker_start,
        initargs=(settings.coverage_worker_nice,),
        mp_context=_pool_context(),
    ) as pool:
        computed = pool.map(partial(_worker_site, settings), sites, chunksize=1)
        for index, (site, result) in enumerate(zip(sites, computed, strict=True)):
            take(index, site, result)

    return downlink, uplink, usable, notes, missing


def render_layer(
    root: Path,
    preset: str,
    site_set: str,
    layer: str,
    levels: Levels,
    grid: Grid,
    settings: Settings,
    threshold: float,
) -> int:
    """Write every tile of one layer. Return how many were written.

    A tile with nothing on it is not written. Empty ground is most of
    the region, so writing it would multiply the run for no gain, and
    the API answers a missing tile with a 404 that Leaflet already
    handles.
    """
    written = 0
    for zoom in range(settings.coverage_min_zoom, settings.coverage_max_zoom + 1):
        for tile in tiles_for_grid(grid, zoom):
            patch = sample_tile(levels, grid, tile)
            image = colour_levels(patch, threshold)
            if not image[..., 3].any():
                continue
            store.write_tile(
                root, preset, site_set, layer, tile.zoom, tile.x, tile.y, write_png(image)
            )
            written += 1
    return written


def receiver_loss(settings: Settings, grid: Grid) -> tuple[Levels | None, list[str]]:
    """Return the clutter loss at the receiving end, cell by cell.

    The map is drawn for a handheld at `COVERAGE_RX_HEIGHT_M`, which is
    below every clutter class except bare ground and water. Until now
    that end was charged nothing anywhere, and it is the end the whole
    map is about.

    The land cover pages sit on the same lattice as the region grid,
    1200 cells to the degree, so a page is placed at a whole cell offset
    and no value is resampled. See `coverage/grid.py` 6.

    None when the deployment holds no land cover page. The manifest
    already says so, and a guess at clutter that is not there would move
    every prediction for no reason.
    """
    if not have_pages(settings):
        return None, []

    table = loss_by_class(settings.coverage_rx_height_m, DEFAULT_FREQUENCY_MHZ)
    missing: list[str] = []
    loss = np.zeros((grid.height, grid.width), dtype=np.uint8)
    north = int(np.floor(grid.north))
    west = int(np.floor(grid.west))
    per_degree = grid.cells_per_degree

    for latitude in range(int(np.floor(grid.south)), north + 1):
        for longitude in range(west, int(np.floor(grid.east)) + 1):
            # Where this degree lands on the region, before the page
            # is read. The loop runs one degree past each edge so that
            # a region which does not start on a whole degree is
            # covered, and those extra degrees touch nothing. A page
            # that is not wanted is not a page that is missing.
            row = round((grid.north - (latitude + 1)) * per_degree)
            column = round((longitude - grid.west) * per_degree)
            top, left = max(row, 0), max(column, 0)
            bottom = min(row + PAGE_SIZE, grid.height)
            right = min(column + PAGE_SIZE, grid.width)
            if bottom <= top or right <= left:
                continue

            name = landcover_tile_name(latitude, longitude)
            page = class_page(settings, name)
            if page is None:
                # No page means no clutter charged over that whole
                # degree, and the edge of it is a straight step of
                # eighteen dB in a town. The manifest names it, as it
                # already does for terrain.
                missing.append(name)
                continue
            patch = page[top - row : bottom - row, left - column : right - column]
            loss[top:bottom, left:right] = table[patch]
    if missing:
        logger.warning(
            "%s degrees of the region have no land cover page, so no clutter is charged over them",
            len(missing),
        )
    return loss, sorted(set(missing))


def _charge_receiver(levels: Levels, loss: Levels | None) -> Levels:
    """Take the receiving end's clutter off a layer.

    A cell nothing reached stays unreached, as in `_shift`. Turning a
    hole into a very weak signal would draw coverage that is not there.
    """
    if loss is None:
        return levels
    moved = np.clip(levels.astype(np.int16) - loss.astype(np.int16), MIN_LEVEL, MAX_LEVEL)
    return np.where(levels == NO_COVERAGE, NO_COVERAGE, moved).astype(np.uint8)


def _empty_summary(key: str, rejected: "Counter[str]") -> store.PresetSummary:
    """Return the summary of a preset that kept no site at all.

    Every node on it was a client, or every position was too coarse.
    The page must still say so: a preset that is missing from the
    manifest reads as a preset the mesh does not use.
    """
    preset = preset_by_key(key)
    assert preset is not None, key
    return store.PresetSummary(
        preset=preset.name,
        label=preset.label,
        sensitivity_dbm=preset.sensitivity_dbm,
        node_count=0,
        candidate_count=sum(rejected.values()),
        site_count=0,
        skipped_count=0,
        excluded_by_role=dict(sorted(rejected.items())),
        usable_area_km2=0.0,
        downlink_area_km2=0.0,
        tile_count=0,
        data_bounds=None,
        nodes=[],
    )


@dataclass(frozen=True)
class SiteSetPlan:
    """One map to build: which roles, and the sites they gave."""

    key: str
    label: str
    allowed: frozenset[str] | None
    groups: dict[str, list[Site]]
    left_out: dict[str, Counter[str]]
    coarse: list[dict[str, object]]


def _build_site_set(
    settings: Settings,
    plan: SiteSetPlan,
    grid: Grid,
    rx_loss: Levels | None,
    root: Path,
    workers: int,
    missing_all: set[str],
) -> list[store.PresetSummary]:
    """Run every preset of one site set and write its tiles."""
    site_set = plan.key
    groups = plan.groups
    left_out = plan.left_out
    summaries: list[store.PresetSummary] = []
    # Every preset that had a candidate, not only every preset that
    # kept one. A preset whose nodes were all clients used to vanish
    # from the manifest entirely, which is the opposite of what the
    # counts are for: the reader sees no mention of it and concludes
    # the mesh does not use it.
    for key in sorted(set(groups) | set(left_out)):
        sites = groups.get(key, [])
        rejected = left_out.get(key, Counter())
        if not sites:
            summaries.append(_empty_summary(key, rejected))
            continue
        preset: ModemPreset = sites[0].preset
        chosen = sites[: settings.coverage_max_nodes]
        # Name the site set. A run that publishes two maps logs this
        # line twice, and without the set the two are indistinguishable
        # while being the whole point of the feature.
        logger.info(
            "%s, preset %s: %s sites, %s nodes left out by role",
            site_set,
            preset.name,
            len(chosen),
            sum(rejected.values()),
        )

        downlink, uplink, usable, notes, missing = predict_preset(settings, grid, chosen, workers)
        missing_all.update(missing)
        # The receiving end is the same wherever it stands, so taking
        # it off after the sites are combined is the same as taking it
        # off each one, and costs one pass instead of many.
        downlink = _charge_receiver(downlink, rx_loss)
        uplink = _charge_receiver(uplink, rx_loss)
        usable = _charge_receiver(usable, rx_loss)
        threshold = preset.sensitivity_dbm

        tiles = 0
        for layer, levels in (
            ("usable", usable),
            ("downlink", downlink),
            ("uplink", uplink),
        ):
            tiles += render_layer(
                root, preset.name, site_set, layer, levels, grid, settings, threshold
            )

        summaries.append(
            store.PresetSummary(
                preset=preset.name,
                label=preset.label,
                sensitivity_dbm=threshold,
                node_count=len(sites),
                candidate_count=len(sites) + sum(rejected.values()),
                site_count=len(chosen),
                skipped_count=len(sites) - len(chosen),
                excluded_by_role=dict(sorted(rejected.items())),
                usable_area_km2=round(covered_area_km2(usable, grid, threshold), 1),
                downlink_area_km2=round(covered_area_km2(downlink, grid, threshold), 1),
                tile_count=tiles,
                data_bounds=data_bounds(usable, grid, threshold),
                nodes=notes[:MANIFEST_NODE_LIMIT],
            )
        )
        # A region grid of Arizona is 88 MB. Letting three of them stay
        # named while the next preset makes two more is most of a
        # gigabyte for nothing.
        del downlink, uplink, usable

    return summaries


def _build(
    settings: Settings,
    plans: list[SiteSetPlan],
    held_terrain: set[str],
    stamp: str,
    workers: int,
) -> store.Manifest:
    """Run every site set and every preset, and write the tiles.

    This holds the processor. One grid and one receiver-loss field are
    made for the whole run and shared by every site set: a region grid
    of Arizona is 88 MB and the receiving end does not change with the
    site set any more than it changes with the preset.
    """
    started = time.monotonic()
    # The first plan is the infrastructure one. Its groups and its
    # roles are what the manifest reports at the top level, so that a
    # reader who takes `presets` without asking for a site set gets the
    # narrow answer. See `AGENTS.md` 9.25.
    allowed = plans[0].allowed
    groups = plans[0].groups
    coarse = plans[0].coarse
    grid = region_grid(
        settings.terrain_lat_min,
        settings.terrain_lat_max,
        settings.terrain_lon_min,
        settings.terrain_lon_max,
    )
    # Clear anything a previous run left behind. See
    # `store.clear_pending`: a run that dies is never published, so
    # nothing else would ever remove it.
    store.clear_pending(settings, keep=stamp)
    root = store.pending_dir(settings, stamp)
    root.mkdir(parents=True, exist_ok=True)

    missing_all: set[str] = set()
    # The receiving end does not change with the preset or with the
    # site set, so it is built once for the whole run.
    rx_loss, missing_landcover = receiver_loss(settings, grid)

    set_summaries: list[store.SiteSetSummary] = []
    for plan in plans:
        summaries = _build_site_set(settings, plan, grid, rx_loss, root, workers, missing_all)
        set_summaries.append(
            store.SiteSetSummary(
                key=plan.key,
                label=plan.label,
                site_roles=sorted(plan.allowed) if plan.allowed is not None else [EVERY_ROLE],
                is_diagnostic=is_diagnostic_role_set(plan.allowed),
                presets=summaries,
                data_bounds=union_bounds([item.data_bounds or [] for item in summaries]),
            )
        )

    # The infrastructure set is the top-level answer.
    summaries = set_summaries[0].presets

    return store.Manifest(
        stamp=stamp,
        generated_at=datetime.now(UTC).isoformat(),
        engine="SPLAT! ITM, WebAssembly",
        bounds=list(grid.bounds()),
        min_zoom=settings.coverage_min_zoom,
        max_zoom=settings.coverage_max_zoom,
        radius_km=settings.coverage_radius_km,
        rx_height_m=settings.coverage_rx_height_m,
        rx_gain_dbi=settings.coverage_rx_gain_dbi,
        handheld_tx_power_dbm=HANDHELD_TX_POWER_DBM,
        has_terrain=bool(held_terrain),
        # True only when every degree of the region has a page. One
        # page used to be enough to claim it, and the edge of a missing
        # degree is a straight step of eighteen dB in a town.
        has_landcover=have_pages(settings) and not missing_landcover,
        missing_landcover_tiles=missing_landcover,
        # What the run predicted from, carried with the run. A reader
        # who opens the page later cannot otherwise tell a coverage map
        # from a diagnostic one.
        site_roles=sorted(allowed) if allowed is not None else [EVERY_ROLE],
        is_diagnostic=is_diagnostic_role_set(allowed),
        coarse_sites=coarse,
        calibrated_nodes=sum(
            1 for sites in groups.values() for site in sites if site.profile.is_measured
        ),
        missing_terrain_tiles=sorted(missing_all),
        seconds=round(time.monotonic() - started, 1),
        data_bounds=union_bounds([item.data_bounds or [] for item in summaries]),
        presets=summaries,
        site_sets=set_summaries,
    )


def _plans(
    settings: Settings,
    nodes: Sequence[Node],
    overrides: Overrides,
    offsets: dict[str, float] | None,
) -> list[SiteSetPlan]:
    """Return the maps this run will build, the narrow one first.

    The infrastructure map is always built. The wider one is built as
    well when `COVERAGE_INCLUDE_CLIENTS` is on, and it predicts from
    the nodes that repeat traffic without being infrastructure. See
    `sonoran/roles.py` for what is in that set and what the firmware
    says about each one.

    The order matters. `_build` reports the first plan at the top level
    of the manifest, so a reader who takes `presets` without asking for
    a site set gets the infrastructure answer.

    A deployment that has set `COVERAGE_SITE_ROLES` to something of its
    own keeps it: that setting is what the first plan uses, so a
    diagnostic run of every role still behaves exactly as before.
    """
    wanted: list[tuple[str, frozenset[str] | None]] = [
        (SITE_SET_INFRASTRUCTURE, parse_site_roles(settings.coverage_site_roles))
    ]
    if settings.coverage_include_clients:
        wanted.append((SITE_SET_EXTENDED, site_set_roles(SITE_SET_EXTENDED)))

    plans: list[SiteSetPlan] = []
    for key, allowed in wanted:
        groups, left_out, coarse = group_by_preset(
            settings, nodes, overrides, offsets, allowed=allowed
        )
        plans.append(
            SiteSetPlan(
                key=key,
                label=SITE_SET_LABELS.get(key, key),
                allowed=allowed,
                groups=groups,
                left_out=left_out,
                coarse=coarse,
            )
        )
    return plans


async def run_once(session: AsyncSession, settings: Settings) -> store.Manifest | None:
    """Make one coverage run and publish it.

    Returns None when there is nothing to predict from, which is a
    working state for a new deployment.
    """
    overrides = load_overrides(settings.radio_overrides_path)
    nodes = await select_nodes(session, settings, overrides)
    # What the mesh measured, where there is enough of it. A node
    # with thin evidence is absent rather than zero, so it keeps its
    # nameplate figures.
    offsets = store.calibration_offsets(settings)
    if offsets:
        logger.info("%s nodes carry a measured correction", len(offsets))
    plans = _plans(settings, nodes, overrides, offsets)
    left_out = plans[0].left_out
    if not any(plan.groups for plan in plans):
        dropped = sum(sum(counts.values()) for counts in left_out.values())
        # Name the setting, not the mesh. "No infrastructure node" is
        # true and unhelpful when the cause is a role set that matches
        # nothing: it sends the reader out to look at the radios.
        logger.info(
            "no node matched %s on a modem preset, so no coverage run. "
            "%s positioned nodes were left out",
            settings.coverage_site_roles,
            dropped,
        )
        return None

    # Terrain is fetched before the engine starts, because fetching it
    # is network work and the engine is processor work. Mixing them
    # would leave the processor idle while a tile downloads. Only the
    # names are kept: the workers read the pages themselves.
    wanted: set[str] = set()
    for plan in plans:
        for sites in plan.groups.values():
            for site in sites[: settings.coverage_max_nodes]:
                wanted.update(tiles_around(site, settings.coverage_radius_km))

    held = await ensure_terrain(settings, sorted(wanted))
    logger.info("%s of %s terrain tiles are held", len(held), len(wanted))

    stamp = store.new_stamp()
    workers = worker_count(settings)
    logger.info("predicting with %s worker processes", workers)
    manifest = await asyncio.to_thread(_build, settings, plans, held, stamp, workers)
    store.publish(settings, stamp, manifest)
    return manifest


async def main() -> None:
    """Make one coverage run."""
    settings = get_settings()
    if not settings.coverage_enabled:
        logger.info("the coverage job is turned off")
        return
    engine = make_engine(settings.database_url_jobs)
    factory = make_session_factory(engine)
    try:
        async with factory() as session:
            manifest = await run_once(session, settings)
            if manifest is not None:
                logger.info(
                    "coverage run %s took %ss over %s presets",
                    manifest.stamp,
                    manifest.seconds,
                    len(manifest.presets),
                )
    finally:
        await engine.dispose()


def run() -> None:
    """Make one coverage run and stop. The console entry point.

    The scheduler makes a run every `COVERAGE_INTERVAL_HOURS`. This is
    the other half of that: one run, now, so that an operator bringing
    a box up does not have to wait for the timer, and so that a first
    run can be watched. It writes into the same cache and publishes the
    same way, so the schedule picks up from where this left off.

        sonoran-coverage-once

    The logging is set up here, as `jobs/scheduler.py` does it. Nothing
    else in the process does, so without this the command runs for five
    minutes and prints not one line — no site count, no progress, no
    completion. For a command whose whole purpose is to be watched,
    that is the same as being broken.
    """
    configure_logging(get_settings().log_level)
    asyncio.run(main())
