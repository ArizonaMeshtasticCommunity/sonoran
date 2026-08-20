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

The work is held to one process and run in a worker thread, because the
engine is a tight loop of floating point and holds the processor for a
second or so at a time. Running it on the event loop would stop the
whole jobs process.
"""

import asyncio
import os
import time
from collections.abc import Sequence
from concurrent.futures import ProcessPoolExecutor
from datetime import UTC, datetime, timedelta
from functools import partial
from pathlib import Path

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sonoran.config import Settings, get_settings
from sonoran.coverage import store
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
from sonoran.landcover.store import have_pages
from sonoran.logging import get_logger
from sonoran.positions import is_usable
from sonoran.radio.overrides import Overrides, load_overrides
from sonoran.radio.presets import ModemPreset, preset_for_channel
from sonoran.radio.resolve import resolve_profile
from sonoran.terrain.store import load_page

logger = get_logger(__name__)

# How many nodes to report by name in the manifest.
#
# The page lists the sites a run used. A mesh of several hundred does
# not need every one of them in a document the browser downloads.
MANIFEST_NODE_LIMIT = 250


def worker_count(settings: Settings) -> int:
    """Return how many worker processes to predict with.

    Zero in the setting means as many as the machine has, less one, so
    the jobs process keeps a core for everything else it does.
    """
    if settings.coverage_workers > 0:
        return settings.coverage_workers
    return max(1, (os.cpu_count() or 2) - 1)


async def select_nodes(session: AsyncSession, settings: Settings) -> Sequence[Node]:
    """Return the nodes a run may predict from.

    A node needs a position to be a transmitter. A node the mesh has not
    heard from for a long time is left out, because a node that is gone
    must not hold coverage open on the map.
    """
    since = datetime.now(UTC) - timedelta(hours=settings.coverage_active_hours)
    rows = await session.scalars(
        select(Node).where(Node.last_heard.is_not(None), Node.last_heard >= since)
    )
    return [node for node in rows.all() if is_usable(node.last_lat, node.last_lon)]


def group_by_preset(
    settings: Settings,
    nodes: Sequence[Node],
    overrides: Overrides,
    offsets: dict[str, float] | None = None,
) -> dict[str, list[Site]]:
    """Return the sites of each preset, strongest first.

    A node whose channel is not a preset name rides on top of a preset
    and does not name one. Weather and PKI are the examples this mesh
    has. Such a node is left out rather than guessed at, because putting
    it on the wrong preset draws a link that cannot exist.
    """
    groups: dict[str, list[Site]] = {}
    for node in nodes:
        preset = preset_for_channel(node.last_channel)
        if preset is None:
            continue
        identifier = f"!{node.node_num:08x}"
        profile = resolve_profile(
            identifier, node.hw_model, overrides, (offsets or {}).get(identifier)
        )
        latitude = node.last_lat
        longitude = node.last_lon
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
    return groups


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


async def read_terrain(settings: Settings, names: Sequence[str]) -> dict[str, bytes | None]:
    """Return the terrain pages for a set of tile names.

    A tile the service does not hold gives None. The engine reads a page
    it never got as sea level, so the run draws coverage over flat
    ground there. The manifest names those tiles, so a page can say so.
    """
    pages: dict[str, bytes | None] = {}
    for name in names:
        if name in pages:
            continue
        try:
            pages[name] = await load_page(settings, name)
        except Exception as error:  # a bad tile must not stop the run
            logger.warning("terrain page %s could not be read: %s", name, error)
            pages[name] = None
    return pages


def _site_levels(
    instance: SplatInstance,
    settings: Settings,
    site: Site,
    pages: dict[str, bytes | None],
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
                page = pages.get(ref.tile_name)
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
# does it once when it starts and holds it for every site it takes.
_WORKER_MODULE: SplatModule | None = None
_WORKER_PAGES: dict[str, bytes | None] = {}

# What one site sends back from a worker.
#
# Everything crossing a process boundary is pickled, so the levels go
# back as bytes and the grid as four numbers rather than as objects.
SiteResult = tuple[bytes, int, int, float, float, list[str]]


def _worker_start(pages: dict[str, bytes | None]) -> None:
    """Set up one worker process."""
    global _WORKER_MODULE
    _WORKER_MODULE = SplatModule()
    _WORKER_PAGES.clear()
    _WORKER_PAGES.update(pages)


def _to_plain(computed: tuple[Levels, Grid, list[str]] | None) -> SiteResult | None:
    """Return a prediction in the shape that crosses a process."""
    if computed is None:
        return None
    levels, grid, missing = computed
    return (levels.tobytes(), grid.width, grid.height, grid.north, grid.west, missing)


def _worker_site(settings: Settings, site: Site) -> SiteResult | None:
    """Predict one site in a worker process."""
    assert _WORKER_MODULE is not None
    return _to_plain(_site_levels(_WORKER_MODULE.instance(), settings, site, _WORKER_PAGES))


def predict_preset(
    settings: Settings,
    grid: Grid,
    sites: Sequence[Site],
    pages: dict[str, bytes | None],
    workers: int,
) -> tuple[Levels, Levels, list[dict[str, object]], set[str]]:
    """Predict one preset from every site on it.

    Returns the downlink grid, the uplink grid, a note about each site,
    and the terrain tiles that were missing.

    The engine runs in worker processes. One site takes a few seconds of
    solid floating point, and a mesh of several hundred would take the
    better part of an hour on one core. The work divides cleanly,
    because each site is its own prediction and none of them reads
    another.

    The results are put on the region grid here, in the order the sites
    were given, so the answer never depends on which worker finished
    first.
    """
    downlink = grid.empty()
    uplink = grid.empty()
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

        added_down = blit_max(downlink, grid, _shift(levels, down_offset), site_grid)
        added_up = blit_max(
            uplink, grid, _shift(levels, uplink_offset_db(settings, site)), site_grid
        )
        notes.append(
            {
                "node_id": site.node_id,
                "display_name": site.display_name,
                "used": True,
                "eirp_dbm": round(site.profile.effective_eirp_dbm, 1),
                "antenna_height_m": site.profile.antenna_height_m,
                "clutter_height_m": site.clutter_height_m,
                "calibrated": site.profile.is_measured,
                "cells_set": added_down,
                "cells_set_uplink": added_up,
            }
        )
        if (index + 1) % 25 == 0:
            logger.info("  %s of %s sites", index + 1, len(sites))

    if workers <= 1:
        module = SplatModule()
        for index, site in enumerate(sites):
            take(index, site, _to_plain(_site_levels(module.instance(), settings, site, pages)))
        return downlink, uplink, notes, missing

    with ProcessPoolExecutor(
        max_workers=workers, initializer=_worker_start, initargs=(pages,)
    ) as pool:
        computed = pool.map(partial(_worker_site, settings), sites, chunksize=1)
        for index, (site, result) in enumerate(zip(sites, computed, strict=True)):
            take(index, site, result)

    return downlink, uplink, notes, missing


def render_layer(
    root: Path,
    preset: str,
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
            store.write_tile(root, preset, layer, tile.zoom, tile.x, tile.y, write_png(image))
            written += 1
    return written


def _build(
    settings: Settings,
    groups: dict[str, list[Site]],
    pages: dict[str, bytes | None],
    stamp: str,
    workers: int,
) -> store.Manifest:
    """Run every preset and write its tiles. This holds the processor."""
    started = time.monotonic()
    grid = region_grid(
        settings.terrain_lat_min,
        settings.terrain_lat_max,
        settings.terrain_lon_min,
        settings.terrain_lon_max,
    )
    root = store.pending_dir(settings, stamp)
    root.mkdir(parents=True, exist_ok=True)

    summaries: list[store.PresetSummary] = []
    missing_all: set[str] = set()

    for _key, sites in sorted(groups.items()):
        preset: ModemPreset = sites[0].preset
        chosen = sites[: settings.coverage_max_nodes]
        logger.info("preset %s: %s sites", preset.name, len(chosen))

        downlink, uplink, notes, missing = predict_preset(settings, grid, chosen, pages, workers)
        missing_all.update(missing)
        usable = combine_min(downlink, uplink)
        threshold = preset.sensitivity_dbm

        tiles = 0
        for layer, levels in (
            ("usable", usable),
            ("downlink", downlink),
            ("uplink", uplink),
        ):
            tiles += render_layer(root, preset.name, layer, levels, grid, settings, threshold)

        summaries.append(
            store.PresetSummary(
                preset=preset.name,
                label=preset.label,
                sensitivity_dbm=threshold,
                node_count=len(sites),
                positioned_count=len(chosen),
                skipped_count=len(sites) - len(chosen),
                usable_area_km2=round(covered_area_km2(usable, grid, threshold), 1),
                downlink_area_km2=round(covered_area_km2(downlink, grid, threshold), 1),
                tile_count=tiles,
                data_bounds=data_bounds(usable, grid, threshold),
                nodes=notes[:MANIFEST_NODE_LIMIT],
            )
        )

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
        has_terrain=any(page is not None for page in pages.values()),
        has_landcover=have_pages(settings),
        calibrated_nodes=sum(
            1 for sites in groups.values() for site in sites if site.profile.is_measured
        ),
        missing_terrain_tiles=sorted(missing_all),
        seconds=round(time.monotonic() - started, 1),
        data_bounds=union_bounds([item.data_bounds or [] for item in summaries]),
        presets=summaries,
    )


async def run_once(session: AsyncSession, settings: Settings) -> store.Manifest | None:
    """Make one coverage run and publish it.

    Returns None when there is nothing to predict from, which is a
    working state for a new deployment.
    """
    overrides = load_overrides(settings.radio_overrides_path)
    nodes = await select_nodes(session, settings)
    # What the mesh measured, where there is enough of it. A node
    # with thin evidence is absent rather than zero, so it keeps its
    # nameplate figures.
    offsets = store.calibration_offsets(settings)
    if offsets:
        logger.info("%s nodes carry a measured correction", len(offsets))
    groups = group_by_preset(settings, nodes, overrides, offsets)
    if not groups:
        logger.info("no positioned nodes on a modem preset, so no coverage run")
        return None

    # Terrain is read before the engine starts, because reading it is
    # network work and the engine is processor work. Mixing them would
    # leave the processor idle while a tile downloads.
    wanted: set[str] = set()
    for sites in groups.values():
        for site in sites[: settings.coverage_max_nodes]:
            wanted.update(tiles_around(site, settings.coverage_radius_km))

    pages = await read_terrain(settings, sorted(wanted))
    held = sum(1 for page in pages.values() if page is not None)
    logger.info("read %s of %s terrain tiles", held, len(pages))

    stamp = store.new_stamp()
    workers = worker_count(settings)
    logger.info("predicting with %s worker processes", workers)
    manifest = await asyncio.to_thread(_build, settings, groups, pages, stamp, workers)
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
