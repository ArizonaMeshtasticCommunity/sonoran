"""Tests for the coverage engine outside the browser.

The engine is one WebAssembly file. The planner page runs it in a
browser worker. The coverage job runs it here. If the two ever answer
differently, a published map and an interactive plan stop agreeing, and
nothing on either page would say so.

`test_the_reference_scenario_matches_the_browser` is the test that
stops that. It pins the rasters of a fixed scenario by hash. The hash
was produced by the browser, with `tools/dev/engine_parity.js`.

If that test fails, the engine changed. Do not paste the new hash in to
make it pass. Find out what changed. `AGENTS.md` 9.13 says the same
about the terrain transform, for the same reason.
"""

import gc
import hashlib
from pathlib import Path

import numpy as np
import pytest

from sonoran.coverage.engine import (
    MASK_COVERED,
    PAGE_SIZE,
    EngineError,
    SplatInstance,
    SplatModule,
    predict,
)
from sonoran.coverage.params import EngineParams, erp_watts, received_dbm
from sonoran.coverage.units import METRES_PER_FOOT, feet_to_metres, metres_to_feet

# The reference scenario. `tools/dev/engine_parity.js` holds the same
# numbers, and the hash below came from running it there.
REFERENCE = EngineParams(
    latitude=34.0,
    longitude=-111.5,
    tx_height_m=12.0,
    rx_height_m=1.0,
    erp_watts=erp_watts(22.0, 5.8, 1.5),
    radius_m=20_000.0,
)

# The rasters the browser produced for `REFERENCE`, as
# sha256(signal + mask).
REFERENCE_SHA256 = "6ca92cfb0f3f31b8ac82a9eba2f2c9c7e9d147593c8ce34bfe16d3e19f749b87"

# What the browser reported for the same run.
REFERENCE_PAGES = 2
REFERENCE_RADIALS = 7200
REFERENCE_WIDTH = 1200
REFERENCE_HEIGHT = 2400
REFERENCE_COVERED = 176_726


def _made_up_page(index: int) -> bytes:
    """Return one elevation page of made-up terrain.

    Real terrain would tie the test to a downloaded tile. This pattern
    is the same on every machine, and it still exercises the cell order
    of `splat_load_page`, which flat ground would not.

    `tools/dev/engine_parity.js` builds the same bytes in JavaScript.
    """
    cells = PAGE_SIZE * PAGE_SIZE
    heights = (np.arange(cells, dtype=np.int64) * 7 + index * 101) % 900
    return heights.astype("<i2").tobytes()


@pytest.fixture(scope="module")
def module() -> SplatModule:
    """Compile the engine once for the whole file."""
    return SplatModule()


def test_the_reference_scenario_matches_the_browser(module: SplatModule) -> None:
    """One binary must answer the same in both languages.

    This is the test that lets the coverage map and the planner page
    both claim to be the same model.
    """
    instance = module.instance()
    with instance.run(REFERENCE) as run:
        pages = run.pages()
        assert len(pages) == REFERENCE_PAGES
        for index in range(len(pages)):
            run.load_page(index, _made_up_page(index))
        assert run.radial_count() == REFERENCE_RADIALS
        run.run_all_radials()
        run.rasterize()
        raster = run.raster()

    assert raster.region.width == REFERENCE_WIDTH
    assert raster.region.height == REFERENCE_HEIGHT

    digest = hashlib.sha256()
    digest.update(raster.signal)
    digest.update(raster.mask)
    assert digest.hexdigest() == REFERENCE_SHA256


def test_the_reference_scenario_covers_the_ground_the_browser_covered(
    module: SplatModule,
) -> None:
    """A count is easier to read than a hash when the hash breaks."""
    instance = module.instance()
    with instance.run(REFERENCE) as run:
        for index in range(len(run.pages())):
            run.load_page(index, _made_up_page(index))
        run.run_all_radials()
        run.rasterize()
        raster = run.raster()

    covered = sum(1 for byte in raster.mask if byte & MASK_COVERED)
    assert covered == REFERENCE_COVERED


def test_the_pages_a_run_needs_name_real_terrain_tiles(module: SplatModule) -> None:
    """The names must be the ones the terrain service serves."""
    instance = module.instance()
    with instance.run(REFERENCE) as run:
        names = [page.tile_name for page in run.pages()]
    assert names == ["N34W112", "N33W112"]


def test_a_page_of_the_wrong_size_is_refused(module: SplatModule) -> None:
    """A short page would be read as terrain and draw a wrong hill."""
    instance = module.instance()
    with instance.run(REFERENCE) as run:
        with pytest.raises(ValueError, match="expected"):
            run.load_page(0, b"\x00\x00")


def test_a_run_with_no_terrain_still_answers(module: SplatModule) -> None:
    """A tile the service does not hold is read as sea level.

    The prediction is then over flat ground. That is wrong, and the
    caller must say so, but it must not be a failure here.
    """
    instance = module.instance()
    raster = predict(instance, REFERENCE, [None, None])
    assert raster.region.width == REFERENCE_WIDTH
    assert any(byte & MASK_COVERED for byte in raster.mask)


def test_terrain_changes_the_prediction(module: SplatModule) -> None:
    """Proof the pages reach the model at all.

    A run that ignored its terrain would pass every other test in this
    file and draw a smooth circle on the map. See `docs/PLANNER.md` 5.
    """
    instance = module.instance()
    flat = predict(instance, REFERENCE, [None, None])
    hilly = predict(module.instance(), REFERENCE, [_made_up_page(0), _made_up_page(1)])
    assert flat.signal != hilly.signal


def test_a_bad_parameter_is_an_engine_error(module: SplatModule) -> None:
    """The engine refuses a region it cannot hold."""
    instance = module.instance()
    too_big = EngineParams(
        latitude=34.0,
        longitude=-111.5,
        tx_height_m=12.0,
        rx_height_m=1.0,
        erp_watts=1.0,
        radius_m=20_000.0,
        resolution_ippd=100_000,
    )
    with pytest.raises(EngineError):
        with instance.run(too_big):
            pass


def test_a_point_to_point_link_reports_a_loss_and_a_profile(module: SplatModule) -> None:
    instance = module.instance()
    with instance.run(REFERENCE) as run:
        for index in range(len(run.pages())):
            run.load_page(index, _made_up_page(index))
        link = run.point_to_point(34.05, -111.55, 1.0)

    assert link.distance_km == pytest.approx(7.2, abs=0.5)
    # The made-up terrain is a sawtooth of 900 m hills at 90 m spacing,
    # so the loss is far larger than any real path gives. Test the shape
    # of the answer, not a figure this terrain cannot produce.
    assert link.loss_db > 80.0
    assert link.dbm < 0.0
    assert 0.0 <= link.azimuth_deg <= 360.0
    assert link.profile, "a link must carry the ground under it"
    assert link.profile[0].distance_km < link.profile[-1].distance_km
    assert link.profile[-1].distance_km == pytest.approx(link.distance_km, rel=0.01)


def test_an_unknown_climate_is_refused_before_the_engine_sees_it() -> None:
    params = EngineParams(
        latitude=34.0,
        longitude=-111.5,
        tx_height_m=3.0,
        rx_height_m=1.0,
        erp_watts=1.0,
        radius_m=1000.0,
        radio_climate="temperate-ish",
    )
    with pytest.raises(ValueError, match="unknown radio climate"):
        params.to_arguments()


# --- units -------------------------------------------------------------


def test_a_height_reaches_the_engine_in_feet() -> None:
    """SPLAT! reads feet. Everything else here is metres.

    Passing metres straight through overstates every antenna by 3.28
    times and draws coverage that does not exist. See AGENTS.md 9.15.
    """
    params = EngineParams(
        latitude=34.0,
        longitude=-111.5,
        tx_height_m=30.0,
        rx_height_m=1.0,
        erp_watts=1.0,
        radius_m=1000.0,
    )
    assert params.tx_alt_feet == pytest.approx(98.425, abs=0.001)
    # The value the engine gets must not be the value in metres.
    assert params.tx_alt_feet != params.tx_height_m
    assert params.to_arguments()[2] == params.tx_alt_feet


def test_the_same_number_in_metres_and_in_feet_is_not_the_same_height() -> None:
    """This is the shape of the mistake, written as a test."""
    assert metres_to_feet(10.0) != 10.0
    assert feet_to_metres(metres_to_feet(10.0)) == pytest.approx(10.0)
    assert METRES_PER_FOOT == 0.3048


def test_the_engine_takes_whole_numbers_where_it_declared_them() -> None:
    """Three of the sixteen arguments are i32, not f64.

    JavaScript hides that. `wasmtime` refuses a float there, so a change
    that turns one of them into a float breaks every run.
    """
    arguments = REFERENCE.to_arguments()
    assert isinstance(arguments[9], int)  # radio climate
    assert isinstance(arguments[10], int)  # polarization
    assert isinstance(arguments[15], int)  # resolution


# --- power -------------------------------------------------------------


def test_erp_adds_the_gain_and_takes_off_the_cable() -> None:
    """30 dBm into a lossless isotropic antenna is one watt."""
    assert erp_watts(30.0, 0.0, 0.0) == pytest.approx(1.0)
    assert erp_watts(30.0, 3.0, 3.0) == pytest.approx(1.0)
    assert erp_watts(33.0, 0.0, 0.0) == pytest.approx(2.0, rel=0.01)


def test_the_receiver_gain_is_added_to_the_field() -> None:
    assert received_dbm(-120.0, 2.15, 0.0) == pytest.approx(-117.85)
    assert received_dbm(-120.0, 2.15, 1.15) == pytest.approx(-119.0)


# --- what an instance costs --------------------------------------------


needs_proc = pytest.mark.skipif(
    not Path("/proc/self/statm").exists(), reason="the measurement reads /proc"
)


def _resident_mb() -> int:
    """Return how much memory this process holds, in megabytes."""
    with open("/proc/self/statm", encoding="ascii") as handle:
        return int(handle.read().split()[1]) * 4096 // 1024 // 1024


def _reference_raster(instance: SplatInstance) -> bytes:
    """Run the reference scenario and return a hash of the rasters."""
    with instance.run(REFERENCE) as run:
        for index in range(len(run.pages())):
            run.load_page(index, _made_up_page(index))
        run.run_all_radials()
        run.rasterize()
        raster = run.raster()
    return hashlib.sha256(raster.signal + raster.mask).digest()


def test_one_instance_answers_many_runs_the_same(module: SplatModule) -> None:
    """An instance is made for a process, not for a prediction.

    A new instance for each site grows a new linear memory of several
    hundred megabytes, and the memory killer ended a three hundred node
    run on exactly that. See `AGENTS.md` 9.16.4. Reuse is only safe if
    the second run on one instance answers the same as the first, which
    is what this asserts.
    """
    with module.instance() as shared:
        first = _reference_raster(shared)
        second = _reference_raster(shared)
    assert first == second

    with module.instance() as fresh:
        assert _reference_raster(fresh) == first


@needs_proc
def test_an_instance_that_is_dropped_and_not_closed_keeps_its_heap(
    module: SplatModule,
) -> None:
    """The measurement that names the bug, in the units that matter.

    A dropped instance is never given back. The store holds the three
    host functions, which are bound methods of the instance, so the two
    hold each other, and the cyclic collector does not take them: it
    counts objects, and the heap is memory that no Python object
    accounts for.

    A worker doing this once for each site grew until the memory killer
    ended the run. See `AGENTS.md` 9.16.4.
    """
    _reference_raster(module.instance())  # warm the allocator
    before = _resident_mb()
    for _ in range(4):
        _reference_raster(module.instance())
    gc.collect()
    dropped = _resident_mb() - before

    before = _resident_mb()
    for _ in range(4):
        with module.instance() as instance:
            _reference_raster(instance)
    closed = _resident_mb() - before

    assert dropped > 40, "the leak must be visible, or this test proves nothing"
    assert closed < 10, "a closed instance must give its heap back"


@needs_proc
def test_reusing_one_instance_costs_no_more_memory(module: SplatModule) -> None:
    """Which is why a worker holds one and not one for each site."""
    with module.instance() as instance:
        _reference_raster(instance)
        before = _resident_mb()
        for _ in range(4):
            _reference_raster(instance)
        assert _resident_mb() - before < 10


def test_the_coverage_job_holds_one_instance_for_each_worker() -> None:
    """The rule above must hold where the memory killer found it."""
    from sonoran.jobs import coverage

    coverage._worker_start()
    try:
        assert coverage._WORKER_INSTANCE is not None
        # The worker uses the instance it was given and makes none.
        assert "instance" not in coverage._worker_site.__code__.co_names
    finally:
        if coverage._WORKER_INSTANCE is not None:
            coverage._WORKER_INSTANCE.close()
        coverage._WORKER_INSTANCE = None
        coverage._WORKER_MODULE = None
