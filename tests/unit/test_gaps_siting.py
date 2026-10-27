"""The siting half of the coverage gaps feature.

Every test here plants a situation and asserts **the rule**. The
thresholds in `config.py` are starting points that
`docs/design/coverage-gaps.md` 11.1 says to measure on live data, so a
test that pinned one would pass for ever and prove nothing.

The most important test in the file is
`test_the_screen_passes_a_clear_line_of_sight`. A pre-filter may have
false positives, because the engine gets the last word on what reaches
it. It may never have a false negative: a candidate thrown away here is
thrown away in silence and nothing downstream can get it back.
"""

import inspect
import re
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from sonoran.api.app import create_app
from sonoran.config import Settings
from sonoran.coverage import store as coverage_store
from sonoran.coverage.clutter import knife_edge_db
from sonoran.gaps import siting
from sonoran.gaps.siting import BAD, OK, UNKNOWN, Candidate, DemandPoint
from sonoran.jobs import gaps_siting, scheduler
from sonoran.radio.presets import preset_by_key
from sonoran.terrain.srtm import PAGE_SIZE, page_cell, srtm2sdf_transform
from tests.unit.job_outputs import JobOutputs

LONG_FAST = preset_by_key("LONG_FAST")
assert LONG_FAST is not None

ROOT = Path(__file__).parent.parent.parent
STATIC = ROOT / "src" / "sonoran" / "web" / "static"


def _settings(**extra: object) -> Settings:
    return Settings(_env_file=None, **extra)  # type: ignore[arg-type]


def _flat_terrain(metres: int = 400, tile: str = "N33W112") -> siting.Terrain:
    """Return terrain that is one flat page and nothing else."""
    page = np.full((PAGE_SIZE, PAGE_SIZE), metres, dtype="<i2")
    return siting.Terrain(lambda name: page.tobytes() if name == tile else None)


def _demand(*places: tuple[float, float]) -> list[DemandPoint]:
    return [
        DemandPoint(latitude=lat, longitude=lon, node_ids=(f"!0000000{index}",), names=("n",))
        for index, (lat, lon) in enumerate(places)
    ]


def _row(**extra: object) -> dict[str, object]:
    """Return one assessed node row, as the gaps artefact holds it."""
    row: dict[str, object] = {
        "node_id": "!0a51a001",
        "display_name": "a node",
        "bad_count": 1,
        "unknown_count": 0,
        "position_confidence": "exact",
        "mobile": False,
        "latitude": 33.40,
        "longitude": -112.10,
        "rf_packets": 0,
        "signals": {},
    }
    row.update(extra)
    return row


# ------------------------------------------------- the page cell order


def test_the_page_cell_order_is_read_back_exactly_as_it_was_written() -> None:
    """`page_cell` reads what `srtm2sdf_transform` writes.

    This is the positive control for the whole siting half. Every
    elevation it uses comes out of a cached page through this one
    mapping, so one axis the wrong way round would put every candidate
    on the wrong hill and nothing would complain.

    The grid is built so that each cell names its own position in the
    reduced tile, where row 0 is the north edge and column 0 is the
    west edge. The transform then drops the north row and the east
    column and writes the rest backwards on both axes.
    """
    size = 8
    grid = np.zeros((size + 1, size + 1), dtype=np.int16)
    for row in range(size + 1):
        for column in range(size + 1):
            grid[row, column] = row * 100 + column
    page = srtm2sdf_transform(grid, page_size=size)

    floor_lat, floor_lon = 33, -112
    for row in range(1, size + 1):
        for column in range(size):
            latitude = floor_lat + 1 - row / size
            longitude = floor_lon + column / size
            # The same arithmetic `page_cell` does, at this page size.
            p = min(max(round((latitude - np.floor(latitude)) * size), 0), size - 1)
            q = min(max(size - 1 - round((longitude - np.floor(longitude)) * size), 0), size - 1)
            assert int(page[p, q]) == row * 100 + column


def test_page_cell_holds_every_point_inside_the_page() -> None:
    """A point on any edge lands on a cell that exists."""
    for latitude, longitude in (
        (33.0, -112.0),
        (33.99999, -111.00001),
        (33.5, -111.5),
    ):
        row, column = page_cell(latitude, longitude)
        assert 0 <= row < PAGE_SIZE
        assert 0 <= column < PAGE_SIZE


def test_terrain_that_is_not_held_is_unknown_and_not_sea_level() -> None:
    """A missing page is not flat ground.

    Reading a zero without the mask beside it would put a candidate on
    imaginary ground at sea level, in a region whose real floor is
    several hundred metres.
    """
    terrain = _flat_terrain()
    metres, known = terrain.elevation(np.array([34.5]), np.array([-115.5]))
    assert not bool(known[0])
    assert float(metres[0]) == 0.0
    assert "N34W116" in terrain.missing


# ----------------------------------------------------------- the demand


def test_a_node_with_no_fault_we_can_measure_is_not_demand() -> None:
    """The unknown bucket is not a reason to build anything."""
    assert not siting.is_demand(_row(bad_count=0, unknown_count=4))


def test_a_coarse_position_can_never_be_sited_for() -> None:
    """A position accurate to kilometres cannot choose a hilltop."""
    assert not siting.is_demand(_row(position_confidence="coarse"))
    assert not siting.is_demand(_row(position_confidence="none"))


def test_a_mobile_node_is_listed_per_node_and_left_out_of_the_area() -> None:
    """A footprint drawn to serve a node that moves serves nobody tomorrow."""
    assert not siting.is_demand(_row(mobile=True))
    # And it is still a node with a fault, which the per node half holds.
    assert _row(mobile=True)["bad_count"] == 1


def test_a_node_that_is_already_fine_is_not_demand() -> None:
    """Inside coverage, heard on the air, and with margin, is not a gap."""
    fine = _row(
        rf_packets=12,
        signals={
            "outside_predicted_usable": {"state": OK},
            "weak_best_link": {"state": OK},
        },
    )
    assert not siting.is_demand(fine)
    # Take away any one of the three and it is demand again.
    assert siting.is_demand(_row(rf_packets=0, signals=fine["signals"]))


def test_five_radios_in_one_house_are_one_place_that_wants_help() -> None:
    """Otherwise a single address decides where the mesh builds next."""
    rows = [
        _row(node_id=f"!0000000{index}", latitude=33.4000 + index * 0.0002) for index in range(5)
    ]
    rows.append(_row(node_id="!000000ff", latitude=33.5, longitude=-112.2))
    points = siting.demand_points(rows, _settings())

    assert len(points) == 2
    assert sorted(point.node_count for point in points) == [1, 5]


def test_a_demand_point_stands_where_its_nodes_said_they_were() -> None:
    """No position is invented. The point is the mean of what was reported."""
    rows = [
        _row(node_id="!00000001", latitude=33.4000, longitude=-112.1000),
        _row(node_id="!00000002", latitude=33.4010, longitude=-112.1010),
    ]
    point = siting.demand_points(rows, _settings())[0]
    assert abs(point.latitude - 33.4005) < 1e-6
    assert abs(point.longitude - -112.1005) < 1e-6


# --------------------------------------------------------- the clusters


def test_two_places_are_a_node_and_not_an_area() -> None:
    """The per node list already holds them. `GAPS_MIN_CLUSTER` is 3."""
    points = _demand((33.40, -112.10), (33.41, -112.11))
    assert siting.cluster_demand(points, _settings()) == []


def test_three_places_close_together_are_an_area() -> None:
    points = _demand((33.40, -112.10), (33.41, -112.11), (33.42, -112.12))
    clusters = siting.cluster_demand(points, _settings())

    assert len(clusters) == 1
    assert clusters[0].node_count == 3
    south, west, north, east = clusters[0].bounds
    assert south < north and west < east


def test_single_linkage_follows_a_chain_and_not_a_ball() -> None:
    """A valley of struggling nodes is a chain.

    Four points 6 km apart in a line are one neighbourhood at a linkage
    of 8 km, although the two ends are 18 km apart.
    """
    step = 6.0 / 111.32
    points = _demand(*[(33.0 + step * index, -112.0) for index in range(4)])
    clusters = siting.cluster_demand(points, _settings(gaps_cluster_link_km=8.0))

    assert len(clusters) == 1
    assert len(clusters[0].points) == 4
    assert clusters[0].width_km > 15.0


def test_two_neighbourhoods_far_apart_stay_apart() -> None:
    near = [(33.40, -112.10), (33.41, -112.11), (33.42, -112.12)]
    far = [(34.40, -111.10), (34.41, -111.11), (34.42, -111.12)]
    clusters = siting.cluster_demand(_demand(*near, *far), _settings())

    assert len(clusters) == 2


def test_the_worst_area_is_reported_first() -> None:
    """The owner asked to see the group one node would help the most."""
    small = [(33.40, -112.10), (33.41, -112.11), (33.42, -112.12)]
    large = [(34.40, -111.10), (34.41, -111.11), (34.42, -111.12), (34.43, -111.13)]
    clusters = siting.cluster_demand(_demand(*small, *large), _settings())

    assert clusters[0].node_count == 4
    assert clusters[0].index == 0


def test_the_number_of_areas_is_capped_so_the_engine_budget_is_bounded() -> None:
    """Eight areas times three predictions is the whole budget."""
    places: list[tuple[float, float]] = []
    for group in range(12):
        for member in range(3):
            places.append((33.0 + group * 1.0, -112.0 + member * 0.01))
    clusters = siting.cluster_demand(_demand(*places), _settings(gaps_max_clusters=8))

    assert len(clusters) == 8


# ---------------------------------------------------------- the screen


def test_the_screen_passes_a_clear_line_of_sight() -> None:
    """**The assertion this whole screen exists for.**

    A pre-filter with false negatives loses the answer in silence. Flat
    ground, nine metres of mast, a handheld four kilometres away: the
    screen must say yes.
    """
    terrain = _flat_terrain()
    settings = _settings()
    result = siting.screen(
        terrain,
        settings,
        LONG_FAST,
        33.45,
        -111.65,
        siting.candidate_radio(settings),
        _demand((33.48, -111.65)),
    )

    assert result.served == (0,)
    assert result.state == OK
    assert result.margin_db[0] > 0


def _ridged(at_latitude: float, metres: int) -> siting.Terrain:
    """Return flat terrain with a wall of rock across one latitude."""
    page = np.full((PAGE_SIZE, PAGE_SIZE), 400, dtype="<i2")
    row, _ = page_cell(at_latitude, -111.65)
    page[row - 2 : row + 3, :] = metres
    return siting.Terrain(lambda name: page.tobytes() if name == "N33W112" else None)


def test_a_planted_ridge_costs_the_path_most_of_its_margin() -> None:
    """A ridge is the thing the screen exists to see.

    Over 3 km a kilometre of rock takes about fifty decibels off the
    margin. That is the discrimination the ranking runs on: two sites
    that both reach every demand point are not equally good, and the
    one looking through a mountain is the worse of them.
    """
    settings = _settings()
    radio = siting.candidate_radio(settings)
    demand = _demand((33.33, -111.65))
    clear = siting.screen(_flat_terrain(), settings, LONG_FAST, 33.30, -111.65, radio, demand)
    ridge = _ridged(33.315, 1400)
    blocked = siting.screen(ridge, settings, LONG_FAST, 33.30, -111.65, radio, demand)

    assert clear.margin_db[0] - blocked.margin_db[0] > 40.0


def test_the_screen_rejects_a_path_a_ridge_really_does_close() -> None:
    """At twenty two kilometres the same wall closes the link outright.

    **It does not close it at three kilometres, and that is correct
    rather than a fault.** A single knife edge is a famously optimistic
    model, and Long fast demodulates 25 dB below its own noise floor, so
    a 1 W node has sixty decibels of margin to spend over a short path.
    The screen is allowed to be generous. It is not allowed to say no to
    a site the engine would have liked. See `docs/GAPS.md` 10.4.
    """
    settings = _settings()
    result = siting.screen(
        _ridged(33.40, 2000),
        settings,
        LONG_FAST,
        33.30,
        -111.65,
        siting.candidate_radio(settings),
        _demand((33.50, -111.65)),
    )

    assert result.served == ()
    assert result.state == BAD
    assert result.margin_db[0] < 0


def test_a_candidate_with_no_terrain_is_unknown_and_never_no_benefit() -> None:
    """Three states. The third one is loud."""
    settings = _settings()
    terrain = _flat_terrain()
    result = siting.screen(
        terrain,
        settings,
        LONG_FAST,
        35.5,
        -115.5,
        siting.candidate_radio(settings),
        _demand((35.52, -115.5)),
    )

    assert result.state == UNKNOWN
    assert result.served == ()
    assert result.unknown_points == 1


def test_a_place_the_published_run_already_reaches_is_not_a_reason_to_build() -> None:
    """The score is what a new node would add, not what it would repeat."""
    settings = _settings()
    terrain = _flat_terrain()
    demand = _demand((33.48, -111.65), (33.47, -111.66))
    everything = siting.screen(
        terrain, settings, LONG_FAST, 33.45, -111.65, siting.candidate_radio(settings), demand
    )
    minus_one = siting.screen(
        terrain,
        settings,
        LONG_FAST,
        33.45,
        -111.65,
        siting.candidate_radio(settings),
        demand,
        frozenset({0}),
    )

    assert len(everything.served) == 2
    assert minus_one.served == (1,)


def test_the_weaker_direction_of_one_candidate_decides() -> None:
    """`AGENTS.md` 9.24, at the screen as at the engine.

    The candidate shouts at 30 dBm and the handheld answers at 22, so
    the uplink is the weaker of the two and it is the uplink that sets
    the margin. Raising only the candidate's power must not move the
    answer once the uplink is the limit.
    """
    settings = _settings()
    terrain = _flat_terrain()
    demand = _demand((33.70, -111.65))
    quiet = siting.candidate_radio(_settings(gaps_candidate_tx_power_dbm=30.0))
    loud = siting.candidate_radio(_settings(gaps_candidate_tx_power_dbm=40.0))

    one = siting.screen(terrain, settings, LONG_FAST, 33.45, -111.65, quiet, demand)
    two = siting.screen(terrain, settings, LONG_FAST, 33.45, -111.65, loud, demand)

    assert one.margin_db == two.margin_db


def test_a_knife_edge_costs_nothing_on_a_clear_path() -> None:
    """The one place the screen may not be pessimistic."""
    assert knife_edge_db(-1.0) == 0.0
    assert knife_edge_db(-0.78) == 0.0
    assert knife_edge_db(0.0) > 0.0
    assert knife_edge_db(2.0) > knife_edge_db(1.0)


# ---------------------------------------------------- the local maxima


def _hill(latitude: float, longitude: float, height: int = 300, radius: int = 30) -> np.ndarray:
    page = np.full((PAGE_SIZE, PAGE_SIZE), 400, dtype="<i2")
    row, column = page_cell(latitude, longitude)
    for down in range(-radius, radius + 1):
        for across in range(-radius, radius + 1):
            away = (down * down + across * across) ** 0.5
            if away <= radius:
                page[row + down, column + across] = int(400 + height * (1 - away / radius))
    return page


def test_a_hill_is_a_candidate_and_a_plain_is_not() -> None:
    """The prominence test is the one that matters.

    The highest cell of a flat plain is still the highest cell, and it
    is not a site. Nothing must come back from flat ground.
    """
    settings = _settings()
    flat = _flat_terrain()
    assert siting.local_maxima(flat, (33.45, -111.75, 33.55, -111.65), settings) == []

    page = _hill(33.50, -111.70)
    hilly = siting.Terrain(lambda name: page.tobytes() if name == "N33W112" else None)
    peaks = siting.local_maxima(hilly, (33.45, -111.75, 33.55, -111.65), settings)

    assert len(peaks) == 1
    assert abs(peaks[0].latitude - 33.50) < 0.001
    assert abs(peaks[0].longitude - -111.70) < 0.001
    assert peaks[0].elevation_m == 700.0
    assert peaks[0].prominence_m >= settings.gaps_min_prominence_m


def test_ground_with_no_terrain_offers_no_candidate() -> None:
    """A window half filled with "we hold nothing" is not a hill."""
    settings = _settings()
    assert siting.local_maxima(_flat_terrain(), (35.4, -115.7, 35.5, -115.6), settings) == []


def test_one_ridge_does_not_fill_every_slot_with_itself() -> None:
    """The thinning keeps the highest and clears the space around it."""
    points = [
        siting.HighPoint(
            latitude=33.50 + index * 0.001,
            longitude=-111.70,
            elevation_m=700 - index,
            prominence_m=100,
        )
        for index in range(40)
    ]
    kept = siting.thin(points, spacing_km=1.5, limit=60)

    assert len(kept) < 5
    assert kept[0].elevation_m == 700


def test_the_candidate_count_is_capped() -> None:
    points = [
        siting.HighPoint(
            latitude=33.0 + index * 0.1, longitude=-111.70, elevation_m=700, prominence_m=100
        )
        for index in range(50)
    ]
    assert len(siting.thin(points, spacing_km=1.5, limit=10)) == 10


# ------------------------------------------------------- the candidates


def test_a_node_already_standing_there_is_the_cheapest_candidate() -> None:
    """Kind A. No land, no permission, no new site."""
    points = _demand((33.40, -112.10), (33.41, -112.11), (33.42, -112.12))
    cluster = siting.cluster_demand(points, _settings())[0]
    rows = [_row(node_id="!0a51a001", latitude=33.41, longitude=-112.11)]

    found = siting.existing_candidates(cluster, rows)

    assert len(found) == 1
    assert found[0].kind == siting.KIND_EXISTING
    assert found[0].node_id == "!0a51a001"


def test_a_node_whose_position_is_coarse_is_never_offered_as_a_site() -> None:
    """A candidate is a claim about a place."""
    points = _demand((33.40, -112.10), (33.41, -112.11), (33.42, -112.12))
    cluster = siting.cluster_demand(points, _settings())[0]
    rows = [_row(latitude=33.41, longitude=-112.11, position_confidence="coarse")]

    assert siting.existing_candidates(cluster, rows) == []


def test_the_candidate_radio_is_an_assumption_and_names_itself() -> None:
    """A 1 W node on a 9 m mast, and the page prints all four values."""
    radio = siting.candidate_radio(_settings())

    assert radio.tx_power_dbm == 30.0
    assert radio.height_m == 9.0
    # The antenna comes from the stock figures and not from a new number.
    from sonoran.radio.hardware import STOCK_ANTENNA_GAIN_DBI

    assert radio.antenna_gain_dbi == STOCK_ANTENNA_GAIN_DBI


def test_a_candidate_that_was_not_judged_reports_no_count_at_all() -> None:
    """`newly_usable` is null and never zero when the state is unknown."""
    candidate = Candidate(
        kind=siting.KIND_GROUND,
        cluster=0,
        latitude=33.4,
        longitude=-112.1,
        state=UNKNOWN,
        reason="no_terrain",
    )
    served = candidate.as_dict()

    assert served["state"] == UNKNOWN
    assert served["newly_usable"] is None
    assert "not the same as no benefit" in str(served["sentence"])


def test_every_reason_a_candidate_can_carry_has_a_sentence() -> None:
    """A reason with no sentence renders as a machine name on the page."""
    source = inspect.getsource(gaps_siting) + inspect.getsource(siting)
    import re

    for match in re.finditer(r'reason = \(?\s*"([a-z_]+)"', source):
        assert match.group(1) in siting.CANDIDATE_REASONS, match.group(1)
    for match in re.finditer(r'reason="([a-z_]+)"', source):
        assert match.group(1) in siting.CANDIDATE_REASONS, match.group(1)


# ------------------------------------------------------- the baseline


def test_a_node_absent_from_the_coverage_artefact_is_unknown() -> None:
    """Absent is unknown. It is never "already covered" and never zero."""
    baseline = gaps_siting.Baseline(available=True, threshold_level=61, levels={"1": 90})
    point = DemandPoint(33.4, -112.1, ("!00000002",), ("n",))

    assert baseline.usable(gaps_siting._node_numbers(point)) is None


def test_a_stored_level_below_the_threshold_is_not_covered() -> None:
    baseline = gaps_siting.Baseline(available=True, threshold_level=61, levels={"1": 30})
    point = DemandPoint(33.4, -112.1, ("!00000001",), ("n",))

    assert baseline.usable(gaps_siting._node_numbers(point)) is False


def test_a_diagnostic_run_answers_nothing_about_the_baseline() -> None:
    """A diagnostic predicts from client nodes that move. `AGENTS.md` 9.25."""
    baseline = gaps_siting.Baseline(
        available=True, is_diagnostic=True, threshold_level=61, levels={"1": 200}
    )
    point = DemandPoint(33.4, -112.1, ("!00000001",), ("n",))

    assert baseline.usable(gaps_siting._node_numbers(point)) is None


def _published(monkeypatch, layer: str, level: int) -> None:  # type: ignore[no-untyped-def]
    """Publish a run whose node levels carry one layer for node 1."""
    document = {
        "stamp": "20261027T000000Z",
        "presets": {
            "LongFast": {
                "threshold_level": 61,
                "site_sets": {"infrastructure": {"1": {layer: level}}},
            }
        },
    }
    monkeypatch.setattr(coverage_store, "read_manifest", lambda settings: {})
    monkeypatch.setattr(coverage_store, "read_node_levels", lambda settings: document)


def test_the_baseline_reads_the_uplink_level_of_a_run(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """A run writes only `uplink` (#402). The baseline must not lose it."""
    _published(monkeypatch, "uplink", 90)
    baseline = gaps_siting.read_baseline(Settings(), LONG_FAST)

    assert baseline.levels == {"1": 90}


def test_the_baseline_still_reads_a_run_published_before_402(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """The published run stays until the next run replaces it."""
    _published(monkeypatch, "usable", 90)
    baseline = gaps_siting.read_baseline(Settings(), LONG_FAST)

    assert baseline.levels == {"1": 90}


# ------------------------------------------------ where the engine runs


def test_the_siting_half_runs_inside_the_coverage_cycle(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """It uses the engine, so it may never be a task of its own.

    The scheduler runs tasks with `asyncio.gather`. A task registered
    beside the others is free to start during a coverage build, and on a
    three core box that also serves a public dashboard that is the last
    core.
    """
    import asyncio
    from typing import cast

    from sqlalchemy.ext.asyncio import AsyncSession

    calls: list[str] = []

    async def covered(session: AsyncSession, settings: Settings) -> None:
        calls.append("coverage")

    async def sited(session: AsyncSession, settings: Settings) -> list[str]:
        calls.append("siting")
        return []

    monkeypatch.setattr(scheduler.coverage, "run_once", covered)
    monkeypatch.setattr(scheduler.gaps_siting, "run_once", sited)

    asyncio.run(
        scheduler._coverage_cycle(cast(AsyncSession, object()), _settings(), run_calibration=False)
    )

    assert calls == ["coverage", "siting"]


def test_the_siting_half_is_never_registered_as_a_peer_task() -> None:
    tasks = scheduler.build_tasks(_settings(coverage_enabled=True, gaps_enabled=True))

    # rf-rollup and read-models are plain SQL, no engine, so they may
    # stand beside coverage (read-models steps aside on its own, #371).
    assert [task.name for task in tasks] == [
        "snapshot",
        "activity_heatmap",
        "coverage",
        "gaps",
        "rf-rollup",
        "read-models",
    ]


def test_the_siting_half_can_be_turned_off_on_its_own(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import asyncio
    from typing import cast

    from sqlalchemy.ext.asyncio import AsyncSession

    calls: list[str] = []

    async def covered(session: AsyncSession, settings: Settings) -> None:
        calls.append("coverage")

    async def sited(settings: Settings) -> list[str]:
        calls.append("siting")
        return []

    monkeypatch.setattr(scheduler.coverage, "run_once", covered)
    monkeypatch.setattr(scheduler.gaps_siting, "run_once", sited)

    asyncio.run(
        scheduler._coverage_cycle(
            cast(AsyncSession, object()),
            _settings(gaps_siting_enabled=False),
            run_calibration=False,
        )
    )

    assert calls == ["coverage"]


# ----------------------------------------------------- the compute cost


def test_no_region_grid_is_ever_built_for_a_candidate() -> None:
    """One is 88 MB and the question is a few dozen point lookups.

    A blit onto a region grid would also be the wrong answer: a
    candidate's footprint must never join the published map.
    """
    source = inspect.getsource(gaps_siting) + inspect.getsource(siting)
    assert "region_grid" not in source
    assert "blit_max" not in source


def test_the_engine_is_asked_for_the_candidate_radius_and_not_the_map_radius() -> None:
    """A 1 W node at 9 m does not reach 60 km, and cost grows as radius squared."""
    settings = _settings()
    assert settings.gaps_candidate_radius_km < settings.coverage_radius_km
    source = inspect.getsource(gaps_siting.confirm)
    assert "gaps_candidate_radius_km" in source


def test_the_prediction_budget_is_a_setting_and_not_a_hope() -> None:
    settings = _settings()
    assert settings.gaps_max_predictions == 24
    assert settings.gaps_max_clusters * settings.gaps_splat_per_cluster == 24
    # One niced worker on a box that also serves a dashboard.
    assert settings.gaps_workers == 1
    assert settings.gaps_worker_nice > 0


def test_there_is_no_health_score_in_the_siting_half_either() -> None:
    """A colour never comes from a number here any more than it does there."""
    source = inspect.getsource(siting) + inspect.getsource(gaps_siting)
    for banned in ("health_score", "score_0_100", "/ 100.0"):
        assert banned not in source


# -------------------------------------------------------- what it says


def test_the_caveats_name_what_a_siting_suggestion_cannot_know() -> None:
    """Design 6.7, in plain words, and served by the API.

    A recommendation that does not carry these is a lie of omission.
    """
    keys = {key for key, _ in siting.SITING_CAVEATS}

    assert "land_is_invisible" in keys
    assert "no_power_or_backhaul" in keys
    assert "nobody_asked_the_owner" in keys
    assert "demand_set_is_biased_to_existing_nodes" in keys
    for _, text in siting.SITING_CAVEATS:
        assert text.endswith(".")


def test_the_screen_is_never_called_a_prediction() -> None:
    """Every row carries how it was arrived at, so nobody confuses them."""
    assert siting.METHOD_SCREEN == "terrain_screen"
    assert siting.METHOD_SPLAT == "splat"


# --------------------------------------------------------------- the API


@pytest.fixture(autouse=True)
def _outputs(job_outputs: JobOutputs) -> None:
    """Every route test here reads the job outputs from memory (#351)."""


def _client(cache: str) -> TestClient:
    return TestClient(create_app(_settings(coverage_cache_dir=cache)))


def test_a_missing_siting_run_is_a_working_state(tmp_path: Path) -> None:
    """The siting half runs inside the coverage cycle, which takes hours."""
    with _client(str(tmp_path)) as client:
        for path in ("/api/gaps/areas", "/api/gaps/candidates"):
            body = client.get(path).json()
            assert body["available"] is False
            assert body["candidates"] == []
            # The limits are served even when there is nothing to site.
            assert body["caveats"]


def test_the_siting_routes_are_get_only(tmp_path: Path) -> None:
    """The public API is read only. `docs/QA.md` 9.1."""
    with _client(str(tmp_path)) as client:
        for path in ("/api/gaps/areas", "/api/gaps/candidates"):
            for call in (client.post, client.put, client.patch, client.delete):
                assert call(path).status_code in (404, 405)


def test_the_siting_routes_compute_nothing() -> None:
    """They read the stored answer (#351). `docs/ISSUES.md` 2.9."""
    from sonoran.api.routes import gaps as route

    source = inspect.getsource(route)
    for computed in ("site_preset", "siting.", "select("):
        assert computed not in source, computed


def test_the_areas_endpoint_serves_the_stored_answer_and_nothing_else(
    tmp_path: Path, job_outputs: JobOutputs
) -> None:
    job_outputs.write_index({"presets": [{"preset": "LongFast"}]})
    job_outputs.write_preset("LongFast", {"preset": "LongFast", "nodes": []})
    job_outputs.write_siting(
        "LongFast",
        {
            "available": True,
            "preset": "LongFast",
            "areas": [{"area": 0, "node_count": 4}],
            "candidates": [{"area": 0, "kind": "ground", "state": "ok"}],
            "caveats": [],
        },
    )
    with _client(str(tmp_path)) as client:
        areas = client.get("/api/gaps/areas").json()
        assert areas["available"] is True
        assert areas["areas"] == [{"area": 0, "node_count": 4}]
        # The rows have their own endpoint and do not ride on this one.
        assert "candidates" not in areas

        found = client.get("/api/gaps/candidates?area=0").json()
        assert found["matched_count"] == 1
        assert client.get("/api/gaps/candidates?area=9").json()["matched_count"] == 0


def test_the_embed_can_never_see_the_siting_half() -> None:
    """A list of places to build is a list of houses that need visiting.

    The same rule as the per node half, enumerated over the whole app so
    that a route added under the embed prefix cannot slip past.
    """
    app = create_app(_settings(embed_enabled=True))
    served: list[str] = []
    stack = list(app.routes)
    while stack:
        route = stack.pop()
        included = getattr(route, "original_router", None)
        if included is not None:
            stack.extend(getattr(included, "routes", []))
            continue
        path = getattr(route, "path", None)
        if isinstance(path, str):
            served.append(path)

    embedded = [path for path in served if path.startswith(("/api/embed", "/embed"))]
    assert embedded, "the embed routes were not enumerated"
    for path in embedded:
        assert "gap" not in path.lower()
        assert "siting" not in path.lower()
        assert "candidate" not in path.lower()
    # And the routes this feature adds really are registered somewhere.
    assert "/api/gaps/areas" in served
    assert "/api/gaps/candidates" in served


def test_the_embed_page_loads_no_siting_script() -> None:
    page = (STATIC / "embed-coverage.html").read_text(encoding="utf-8")
    assert "siting" not in page.lower()
    assert "candidate" not in page.lower()


# --------------------------------------------------------- the front end


def test_the_siting_script_loads_before_the_router() -> None:
    """app.js runs the router as its last act. `AGENTS.md` 9.14.2."""
    text = (STATIC / "index.html").read_text(encoding="utf-8")
    assert text.index("static/siting.js") < text.index("static/app.js")


def test_the_siting_script_exports_the_global_the_page_needs() -> None:
    page = (STATIC / "siting.js").read_text(encoding="utf-8")
    assert "window.SonoranSiting" in page


def test_the_siting_page_uses_base_relative_api_paths() -> None:
    page = (STATIC / "siting.js").read_text(encoding="utf-8")
    assert "document.baseURI" in page
    assert "'/api/" not in page


def test_the_page_draws_no_line_between_two_nodes() -> None:
    """Nothing here names both ends of one link, so a line means nothing.

    A cluster outline is a box drawn round the demand and is not a claim
    about a radio path, which is why `L.rectangle` is allowed and
    `L.polyline` is not.
    """
    page = (STATIC / "siting.js").read_text(encoding="utf-8")
    for drawing in ("L.polyline", "arrowHead", "L.Polyline"):
        assert drawing not in page


def test_a_candidate_pin_cannot_be_mistaken_for_a_node() -> None:
    """A node is a circle on this page. A candidate must not be one."""
    page = (STATIC / "siting.js").read_text(encoding="utf-8")
    assert "divIcon" in page
    assert "gap-candidate-pin" in page


def test_the_caveats_are_still_decided_by_the_server() -> None:
    """The list left the page; the words are still not the page's to soften.

    This used to require a permanently visible limits list on the page.
    Will asked for it to go (2026-09-26) along with the rest of the
    explanatory prose, so what remains to protect is the part that made
    the list trustworthy: the caveats are written by `gaps/siting.py` and
    served by the API, not composed in the browser, so nothing in the
    frontend can quietly reword them.

    Asserted against the SERVER, deliberately. `siting.js` now mentions
    `caveats` only in a comment explaining the removal, so checking the
    JavaScript would pass on that comment and prove nothing -- which is
    how this test first "passed" after the change.
    """
    siting = (ROOT / "src" / "sonoran" / "gaps" / "siting.py").read_text(encoding="utf-8")
    assert "caveat" in siting.lower(), "the server no longer decides the caveats"


def test_the_radio_it_assumed_is_still_sent_and_still_fixed_in_one_place() -> None:
    """The page stopped printing it. It is still an assumption.

    The four figures -- 30 dBm, a 2.15 dBi antenna, no cable loss, a 9 m
    mast -- were printed under the heading, and that line went with the
    rest of the prose on 2026-09-26. They are not a setting a reader can
    change, so the thing worth protecting is that they are decided in ONE
    place and still sent, which keeps them showable and keeps them from
    being quietly different from what the engine actually ran.
    """
    # Read from config.py, which is where they actually live. Pointing
    # this at gaps/siting.py first was a guess about where a figure is
    # decided, and it was wrong -- the settings are named
    # `gaps_candidate_*` and carry the defaults the docs quote.
    config = (ROOT / "src" / "sonoran" / "config.py").read_text(encoding="utf-8")
    for setting, expected in (
        ("gaps_candidate_tx_power_dbm", "30.0"),
        ("gaps_candidate_height_m", "9.0"),
        ("gaps_candidate_radius_km", "25.0"),
    ):
        found = re.search(rf"{setting}:\s*float\s*=\s*([0-9.]+)", config)
        assert found, f"{setting} is no longer a setting"
        assert found.group(1) == expected, (
            f"{setting} is now {found.group(1)}, not the {expected} the page used to print; "
            "if that was deliberate, the figure changed for every prediction"
        )
    # Still reported, so anything that wants to show them can. Asserted
    # against the job that writes it and the route that passes it on --
    # NOT `gaps/siting.py`, which is the scoring module and never had it.
    job = (ROOT / "src" / "sonoran" / "jobs" / "gaps_siting.py").read_text(encoding="utf-8")
    route = (ROOT / "src" / "sonoran" / "api" / "routes" / "gaps.py").read_text(encoding="utf-8")
    assert "assumed_radio" in job, "the job no longer records the assumed radio"
    assert "assumed_radio" in route, "the API no longer passes the assumed radio on"


def test_the_page_tells_a_screened_row_from_a_predicted_one() -> None:
    """`terrain_screen` is a ranking. `splat` is the engine."""
    page = (STATIC / "siting.js").read_text(encoding="utf-8")
    assert "terrain_screen" in page
    assert "splat" in page
