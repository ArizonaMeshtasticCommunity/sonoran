"""The siting half of the coverage gaps feature.

`jobs/gaps.py` answers "which nodes are struggling". This job answers
"where would one new node help the most of them", for one modem preset
at a time.

## Why this one joins the coverage cycle

`jobs/scheduler.py::service` runs tasks with `asyncio.gather`, so a task
registered on its own clock runs **beside** the others. This job uses
the SPLAT engine, and the engine has no IO to yield on: a worker holds
its core solid until it finishes. On the three core box this project
runs on, which also serves a public dashboard and takes MQTT, a task
free to start during a coverage build would take the last core.

So it runs inside `_coverage_cycle`, after `coverage.run_once`, and
never as a peer `Task`. The per node job of phase 1 is the opposite
case and correctly keeps its own clock: it is only SQL.

## What one run costs, and why it is the shape it is

Brute force is dead. A 5 km candidate grid over the Arizona region is
about 27,000 candidates, and the measured cost of the engine is 18.4
core-seconds for a 60 km site, which is roughly six core-days.

The cost falls with the square of the radius, so a 25 km candidate is
about 3.2 core-seconds. The budget is then:

    up to GAPS_MAX_CLUSTERS areas
    x GAPS_SPLAT_PER_CLUSTER predictions each
    capped at GAPS_MAX_PREDICTIONS, which is 24
    = about 77 core-seconds, under two minutes on one niced worker

Everything before the engine is arithmetic: the clustering is a
distance matrix over a few hundred points, and the terrain screen is
numpy over cached pages. The engine step is the only expensive part and
it is capped by a setting, not by hope.

**No region grid is ever built for a candidate.** One is 88 MB, and the
question a candidate answers is a few dozen point lookups. Each
candidate's own raster is about 600 by 600 cells, which is 360 KB, and
it is sampled at the demand points and then dropped.
"""

import asyncio
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

import numpy as np
from sqlalchemy.ext.asyncio import AsyncSession

from sonoran.config import Settings, get_settings
from sonoran.coverage import store as coverage_store
from sonoran.coverage.clutter import terminal_loss_db
from sonoran.coverage.grid import NO_COVERAGE, Grid, Levels, combine_min, shift, to_dbm
from sonoran.coverage.params import DEFAULT_FREQUENCY_MHZ
from sonoran.coverage.sites import Site, downlink_offset_db, make_site, uplink_offset_db
from sonoran.db.session import make_engine, make_session_factory
from sonoran.gaps import siting, store
from sonoran.gaps.siting import (
    BAD,
    KIND_EXISTING,
    METHOD_SCREEN,
    METHOD_SPLAT,
    OK,
    UNKNOWN,
    Candidate,
    Cluster,
    DemandPoint,
)
from sonoran.jobs import coverage as coverage_job
from sonoran.landcover.classes import is_diffracting
from sonoran.landcover.store import class_at, clutter_at
from sonoran.logging import configure_logging, get_logger
from sonoran.radio.presets import ModemPreset, modelled, preset_for_channel, sensitivity_of
from sonoran.radio.resolve import RadioProfile, Source
from sonoran.roles import SITE_SET_INFRASTRUCTURE
from sonoran.terrain.store import read_cached_page

logger = get_logger(__name__)

# The identifier a candidate site carries into the engine.
#
# It is not a node and it must never look like one. A reader who finds
# this string in a log is looking at a place, not at a radio somebody
# owns.
CANDIDATE_NODE_ID = "!candidate"


@dataclass(frozen=True)
class Baseline:
    """What the published coverage run already predicts at a node.

    `threshold_level` is `to_level(preset.sensitivity_dbm)`, so a reader
    needs no preset table. A node **absent** from `levels` is unknown
    and is never read as a zero: a zero says the run reached that cell
    and found nothing, which is a different answer.
    """

    stamp: str | None = None
    available: bool = False
    is_diagnostic: bool = False
    threshold_level: int = 0
    levels: dict[str, int] | None = None

    def usable(self, node_id_numbers: Sequence[str]) -> bool | None:
        """Return whether the run already covers this place.

        None when nothing is known about any node standing there.
        """
        if not self.available or self.is_diagnostic or self.levels is None:
            return None
        known = [self.levels[number] for number in node_id_numbers if number in self.levels]
        if not known:
            return None
        return max(known) >= self.threshold_level


def read_baseline(settings: Settings, preset: ModemPreset) -> Baseline:
    """Return the published run's usable level at each node.

    The site set is always the infrastructure one, which is the only map
    that describes coverage a fixed node holds open. A diagnostic run
    predicts from client nodes that move, so it answers nothing here and
    is refused rather than labelled. See `AGENTS.md` 9.25 and 9.26.
    """
    manifest = coverage_store.read_manifest(settings)
    document = coverage_store.read_node_levels(settings)
    if manifest is None or document is None:
        return Baseline()
    stamp = document.get("stamp")
    presets = document.get("presets")
    for_preset = presets.get(preset.name) if isinstance(presets, dict) else None
    if not isinstance(for_preset, dict):
        return Baseline(
            stamp=stamp if isinstance(stamp, str) else None,
            is_diagnostic=bool(manifest.get("is_diagnostic")),
        )
    site_sets = for_preset.get("site_sets")
    holder = site_sets.get(SITE_SET_INFRASTRUCTURE) if isinstance(site_sets, dict) else None
    threshold = for_preset.get("threshold_level")
    levels: dict[str, int] = {}
    if isinstance(holder, dict):
        for key, value in holder.items():
            if isinstance(value, dict) and isinstance(value.get("usable"), int):
                levels[str(key)] = int(value["usable"])
    return Baseline(
        stamp=stamp if isinstance(stamp, str) else None,
        available=True,
        is_diagnostic=bool(manifest.get("is_diagnostic")),
        threshold_level=int(threshold) if isinstance(threshold, int) else 0,
        levels=levels,
    )


def _node_numbers(point: DemandPoint) -> list[str]:
    """Return the node numbers of a demand point, as the artefact keys them.

    `coverage-at-nodes.json` keys on the node number as a decimal
    string. The gaps artefact carries the `!hexadecimal` identifier, so
    one of the two has to be converted and this is where.
    """
    numbers: list[str] = []
    for node_id in point.node_ids:
        try:
            numbers.append(str(int(node_id.lstrip("!"), 16)))
        except ValueError:
            continue
    return numbers


def candidate_site(settings: Settings, preset: ModemPreset, candidate: Candidate) -> Site:
    """Return one candidate as a site the engine can be asked about.

    The radio is the candidate radio, whatever stands there today. That
    is the point of a kind A candidate: "if the node at this address
    went to 1 W on a 9 m mast". Its own antenna is not read, because the
    question is about the mast that is not there yet.
    """
    radio = siting.candidate_radio(settings)
    profile = RadioProfile(
        node_id=CANDIDATE_NODE_ID,
        tx_power_dbm=radio.tx_power_dbm,
        antenna_gain_dbi=radio.antenna_gain_dbi,
        antenna_height_m=radio.height_m,
        cable_loss_db=radio.cable_loss_db,
        above_clutter=False,
        # **No calibration correction.** The fit is rejected outright on
        # live data, and a correction measured on somebody else's radio
        # is not a fact about a mast nobody has built. `AGENTS.md` 9.21.
        calibration_offset_db=0.0,
        locked=False,
        chipset="candidate",
        hardware_inferred=True,
        sources={
            "tx_power_dbm": Source.DEFAULT,
            "antenna_gain_dbi": Source.DEFAULT,
            "antenna_height_m": Source.DEFAULT,
            "cable_loss_db": Source.DEFAULT,
        },
    )
    return make_site(
        settings=settings,
        node_id=CANDIDATE_NODE_ID,
        node_num=0,
        display_name="candidate site",
        latitude=candidate.latitude,
        longitude=candidate.longitude,
        profile=profile,
        preset=preset,
    )


def receiver_loss_db(settings: Settings, latitude: float, longitude: float) -> float:
    """Return what the clutter at a demand point costs the handheld.

    The coverage job charges this as a raster over the whole region,
    from the same `coverage/clutter.py` and at the same receiver height.
    Here the question is asked at a few dozen points, so it is computed
    at those points instead of over 88 MB of ground. It is the same
    number, taken the cheap way round.
    """
    height_m = settings.coverage_rx_height_m
    return terminal_loss_db(
        clutter_at(settings, latitude, longitude),
        height_m,
        DEFAULT_FREQUENCY_MHZ,
        is_diffracting(class_at(settings, latitude, longitude)),
    )


def score_prediction(
    settings: Settings,
    preset: ModemPreset,
    site: Site,
    result: tuple[bytes, int, int, float, float, list[str]],
    demand: Sequence[DemandPoint],
) -> tuple[list[int], list[int]]:
    """Return which demand points this prediction reaches.

    **The candidate's own raster is sampled at the demand points, and no
    region grid is built.** The first return value is the index of every
    point the engine says is usable; the second is the index of every
    point that fell outside the raster entirely, which is unknown and
    not "no coverage".

    The two directions are combined for this one site before anything
    else, which is `AGENTS.md` 9.24. `usable` is the weaker direction of
    one radio: a place the node can shout to but cannot hear back from
    is not covered, and taking the best of each direction first would
    paint it as though it were.
    """
    raw, width, height, north, west, _missing = result
    # The engine field, already read out of the raster by
    # `coverage.levels_from_raster` before it crossed the process
    # boundary. It is one unsigned byte a cell, and a zero means no
    # radial of the sweep reached that cell.
    levels: Levels = np.frombuffer(raw, dtype=np.uint8).reshape(height, width)
    grid = Grid(north=north, west=west, width=width, height=height)
    here = site.clutter_loss_db
    down = shift(levels, downlink_offset_db(settings) - here)
    up = shift(levels, uplink_offset_db(settings, site) - here)
    usable = combine_min(down, up)

    served: list[int] = []
    outside: list[int] = []
    for index, point in enumerate(demand):
        level = _sample(usable, grid, point.latitude, point.longitude)
        if level is None:
            outside.append(index)
            continue
        if level == NO_COVERAGE:
            continue
        # The receiving end's clutter, charged here because the map
        # charges it over the whole region and this is the same number
        # at one point.
        dbm = to_dbm(level) - receiver_loss_db(settings, point.latitude, point.longitude)
        if dbm >= sensitivity_of(preset):
            served.append(index)
    return served, outside


def _sample(levels: Levels, grid: Grid, latitude: float, longitude: float) -> int | None:
    """Return the strongest level within one cell of a place, or None.

    One cell of reach for the reason `coverage.SAMPLE_REACH` gives: the
    engine marks a cell covered when a radial of its sweep passed
    through it, and the cell a sweep starts from has no radial through
    it at all. Ninety metres is the resolution of the grid itself, and
    far finer than the 365 m that is the best position precision the
    public broker ever relays.

    None means the place is outside this raster. That is unknown, and a
    caller must never write it as zero.
    """
    if not grid.holds(latitude, longitude):
        return None
    row = grid.row_of(latitude)
    column = grid.column_of(longitude)
    if not (0 <= row < grid.height and 0 <= column < grid.width):
        return None
    reach = siting.SAMPLE_REACH
    top = max(0, row - reach)
    bottom = min(grid.height, row + reach + 1)
    left = max(0, column - reach)
    right = min(grid.width, column + reach + 1)
    return int(levels[top:bottom, left:right].max())


def plan_candidates(
    settings: Settings,
    preset: ModemPreset,
    clusters: Sequence[Cluster],
    rows: Sequence[dict[str, object]],
    terrain: siting.Terrain,
    baseline: Baseline,
) -> tuple[list[Candidate], dict[int, list[DemandPoint]]]:
    """Return every screened candidate, best first inside each area.

    Both kinds compete in one ranking. A node that is already standing
    in the right place needs no land and no permission, so it wins a tie
    against a hilltop and the ranking says so by keeping it first at an
    equal score.
    """
    radio = siting.candidate_radio(settings)
    planned: list[Candidate] = []
    demand_of: dict[int, list[DemandPoint]] = {}
    for cluster in clusters:
        demand = list(cluster.points)
        demand_of[cluster.index] = demand
        # The places the published run already reaches. They are left
        # out of every score, because the question a candidate answers
        # is what a new node would **add**.
        already = frozenset(
            index
            for index, point in enumerate(demand)
            if baseline.usable(_node_numbers(point)) is True
        )
        candidates = siting.existing_candidates(cluster, rows)
        candidates += siting.ground_candidates(terrain, cluster, settings)
        comfort: dict[int, float] = {}
        for candidate in candidates:
            result = siting.screen(
                terrain,
                settings,
                preset,
                candidate.latitude,
                candidate.longitude,
                radio,
                demand,
                already,
            )
            candidate.method = METHOD_SCREEN
            candidate.state = result.state
            candidate.screen_score = len(result.served)
            candidate.screen_unknown = result.unknown_points
            candidate.margin_db = result.margin_db
            comfort[id(candidate)] = result.comfort_db
            if candidate.elevation_m is None:
                # A ground candidate came from the terrain and already
                # knows how high it stands. A node that is already there
                # does not, and the height is the first thing a reader
                # wants beside a place. It is read out of the same
                # terrain and stays None where we hold none, because a
                # height of zero would be a claim about sea level.
                here, known = terrain.elevation(
                    np.array([candidate.latitude]), np.array([candidate.longitude])
                )
                if bool(known[0]):
                    candidate.elevation_m = float(here[0])
            candidate.reason = (
                "no_terrain"
                if result.state == UNKNOWN
                else ("screened_only" if result.served else "screen_found_nothing")
            )
        candidates.sort(
            key=lambda item: (
                -item.screen_score,
                # Rounded into 5 dB steps so that a near tie on comfort
                # does not decide the order on its own. The screen is a
                # coarse model and a decibel of it means nothing.
                -round(comfort.get(id(item), 0.0) / 5.0),
                # A node already standing there beats new ground at an
                # equal score: it needs no land and no permission.
                0 if item.kind == KIND_EXISTING else 1,
                -(item.elevation_m or 0.0),
            )
        )
        planned.extend(candidates)
    return planned, demand_of


def confirm(
    settings: Settings,
    preset: ModemPreset,
    planned: Sequence[Candidate],
    demand_of: dict[int, list[DemandPoint]],
    baseline: Baseline,
) -> tuple[int, float]:
    """Run the engine on the top few of each area. Return count and seconds.

    The cap is two things at once and both are needed:
    `GAPS_SPLAT_PER_CLUSTER` keeps one area from taking the whole
    budget, and `GAPS_MAX_PREDICTIONS` keeps the run inside its budget
    whatever the number of areas.
    """
    chosen: list[Candidate] = []
    taken: dict[int, int] = {}
    for candidate in planned:
        if candidate.state == UNKNOWN or candidate.screen_score <= 0:
            continue
        if taken.get(candidate.cluster, 0) >= max(settings.gaps_splat_per_cluster, 0):
            continue
        if len(chosen) >= max(settings.gaps_max_predictions, 0):
            break
        taken[candidate.cluster] = taken.get(candidate.cluster, 0) + 1
        chosen.append(candidate)
    if not chosen:
        return 0, 0.0

    # The engine is asked for a 25 km radius, not the 60 km the coverage
    # map uses. A 1 W node at 9 m talking to a 1.5 m handheld does not
    # reach 60 km, and the cost grows with the square of the radius.
    narrowed = settings.model_copy(update={"coverage_radius_km": settings.gaps_candidate_radius_km})
    sites = [candidate_site(narrowed, preset, candidate) for candidate in chosen]

    wanted: set[str] = set()
    for site in sites:
        wanted.update(coverage_job.tiles_around(site, narrowed.coverage_radius_km))
    held = {name for name in wanted if read_cached_page(narrowed, name) is not None}
    logger.info(
        "siting, preset %s: %s predictions, %s of %s terrain tiles held",
        preset.name,
        len(sites),
        len(held),
        len(wanted),
    )

    started = time.monotonic()
    results = coverage_job.predict_sites(
        narrowed, sites, max(settings.gaps_workers, 0), settings.gaps_worker_nice
    )
    seconds = time.monotonic() - started

    for candidate, site, result in zip(chosen, sites, results, strict=True):
        candidate.run_stamp = baseline.stamp
        if result is None:
            # The engine refused. Unknown, and never "no benefit".
            candidate.method = METHOD_SPLAT
            candidate.state = UNKNOWN
            candidate.newly_usable = None
            candidate.reason = "engine_refused"
            continue
        demand = demand_of[candidate.cluster]
        served, outside = score_prediction(narrowed, preset, site, result, demand)
        newly: list[str] = []
        already = 0
        unknown_baseline = 0
        for index in served:
            point = demand[index]
            was = baseline.usable(_node_numbers(point))
            if was is True:
                already += 1
                continue
            if was is None:
                unknown_baseline += 1
            newly.extend(point.node_ids)
        candidate.method = METHOD_SPLAT
        candidate.newly_usable = len(newly)
        candidate.newly_usable_nodes = tuple(newly)
        candidate.already_usable = already
        candidate.baseline_unknown = unknown_baseline
        candidate.screen_unknown = max(candidate.screen_unknown, len(outside))
        candidate.state = OK if newly else BAD
        candidate.reason = "confirmed_by_engine" if newly else "engine_found_nothing"

    return len(chosen), seconds


def site_preset(
    settings: Settings, preset: ModemPreset, document: dict[str, object]
) -> dict[str, object]:
    """Return the whole siting answer for one preset, ready to be written."""
    listed = document.get("nodes")
    rows = [row for row in listed if isinstance(row, dict)] if isinstance(listed, list) else []
    points = siting.demand_points(rows, settings)
    clusters = siting.cluster_demand(points, settings)
    baseline = read_baseline(settings, preset)
    terrain = siting.Terrain(lambda name: read_cached_page(settings, name))

    planned, demand_of = plan_candidates(settings, preset, clusters, rows, terrain, baseline)
    predictions, seconds = confirm(settings, preset, planned, demand_of, baseline)

    radio = siting.candidate_radio(settings)
    # Confirmed first, then screened, then what could not be judged. A
    # candidate the engine refused must not sort above one it agreed
    # with just because the screen liked it.
    order = {OK: 0, BAD: 1, UNKNOWN: 2}
    planned.sort(
        key=lambda item: (
            item.cluster,
            order.get(item.state, 3),
            0 if item.method == METHOD_SPLAT else 1,
            -(item.newly_usable if item.newly_usable is not None else -1),
            -item.screen_score,
        )
    )

    return {
        "available": True,
        "preset": preset.name,
        "label": preset.label,
        "generated_at": datetime.now(UTC).isoformat(),
        "window_hours": document.get("window_hours"),
        "demand_point_count": len(points),
        "demand_node_count": sum(point.node_count for point in points),
        "areas": [
            {
                "area": cluster.index,
                "point_count": len(cluster.points),
                "node_count": cluster.node_count,
                "node_ids": list(cluster.node_ids),
                "centroid": [round(value, 5) for value in cluster.centroid],
                "bounds": [round(value, 5) for value in cluster.bounds],
                "width_km": round(cluster.width_km, 1),
                "points": [
                    {
                        "latitude": round(point.latitude, 5),
                        "longitude": round(point.longitude, 5),
                        "node_count": point.node_count,
                        "node_ids": list(point.node_ids),
                        "names": list(point.names),
                    }
                    for point in cluster.points
                ],
            }
            for cluster in clusters
        ],
        "candidates": [candidate.as_dict() for candidate in planned],
        "coverage": {
            "stamp": baseline.stamp,
            "available": baseline.available,
            "is_diagnostic": baseline.is_diagnostic,
            "site_set": SITE_SET_INFRASTRUCTURE,
        },
        # Every one of these is an assumption, and the page prints all
        # four. A reader who wants a different mast opens the planner.
        "assumed_radio": {
            "tx_power_dbm": radio.tx_power_dbm,
            "antenna_gain_dbi": radio.antenna_gain_dbi,
            "cable_loss_db": radio.cable_loss_db,
            "antenna_height_m": radio.height_m,
            "radius_km": settings.gaps_candidate_radius_km,
            "rx_height_m": settings.coverage_rx_height_m,
        },
        "cost": {
            "predictions": predictions,
            "max_predictions": settings.gaps_max_predictions,
            "workers": max(settings.gaps_workers, 0),
            "engine_seconds": round(seconds, 1),
            "core_seconds": round(seconds * max(settings.gaps_workers, 1), 1),
        },
        "thresholds": {
            "demand_cell_m": settings.gaps_demand_cell_m,
            "cluster_link_km": settings.gaps_cluster_link_km,
            "min_cluster": settings.gaps_min_cluster,
            "search_radius_km": settings.gaps_search_radius_km,
            "min_prominence_m": settings.gaps_min_prominence_m,
            "candidate_spacing_km": settings.gaps_candidate_spacing_km,
            "splat_per_cluster": settings.gaps_splat_per_cluster,
        },
        "missing_terrain_tiles": sorted(terrain.missing),
        "caveats": [{"key": key, "text": text} for key, text in siting.SITING_CAVEATS],
    }


async def run_once(session: AsyncSession, settings: Settings) -> list[str]:
    """Make one siting answer for every assessed preset. Return the names.

    The session reads the per node assessment the gaps job already wrote,
    and stores the answer (#351). It asks the mesh nothing: the baseline
    is the coverage run's own artefact, and everything else is terrain.
    An empty list is a working state: a box whose gaps job has not run
    yet has nothing to site against.
    """
    index = await store.read_index(session)
    if index is None:
        logger.info("no gap assessment has been made yet, so there is nothing to site against")
        return []
    listed = index.get("presets")
    names = [
        str(item["preset"])
        for item in (listed if isinstance(listed, list) else [])
        if isinstance(item, dict) and isinstance(item.get("preset"), str)
    ]

    written: list[str] = []
    for name in names:
        # The index carries `preset.name`, which is the channel name the
        # firmware uses, and not `preset.key`. `preset_for_channel` is
        # the one reader of that spelling. `preset_by_key` takes
        # `LONG_FAST` and would find nothing at all here.
        preset = modelled(preset_for_channel(name))
        document = await store.read_preset(session, name)
        if preset is None or document is None:
            continue
        answer = await asyncio.to_thread(site_preset, settings, preset, document)
        if not await store.write_siting(session, preset.name, answer):
            continue
        written.append(preset.name)
        cost = answer["cost"]
        areas = answer["areas"]
        logger.info(
            "siting, preset %s: %s areas, %s candidates, %s predictions in %ss of engine time",
            preset.name,
            len(areas) if isinstance(areas, list) else 0,
            len(answer["candidates"]) if isinstance(answer["candidates"], list) else 0,
            cost["predictions"] if isinstance(cost, dict) else 0,
            cost["engine_seconds"] if isinstance(cost, dict) else 0,
        )
    return written


async def main() -> None:
    """Make one siting answer."""
    settings = get_settings()
    if not settings.gaps_enabled or not settings.gaps_siting_enabled:
        logger.info("the coverage gaps siting job is turned off")
        return
    engine = make_engine(settings.database_url)
    factory = make_session_factory(engine)
    try:
        async with factory() as session:
            await run_once(session, settings)
    finally:
        await engine.dispose()


def run() -> None:
    """Make one siting answer and stop. The console entry point.

    The coverage cycle makes one after every coverage run. This is the
    other half of that, matching `sonoran-coverage-once` and
    `sonoran-gaps-once`.

        sonoran-gaps-siting-once

    The logging is set up here because nothing else in the process does
    it, and a command whose whole purpose is to be watched must print.
    """
    configure_logging(get_settings().log_level)
    asyncio.run(main())
