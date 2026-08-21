"""Tests for the coverage map: the grid, the tiles, and the two layers.

Three things here are easy to get wrong and impossible to see on a
finished map:

- A raster put on the region grid one cell out. Every ridge line moves
  90 m and nothing looks wrong.
- A tile read evenly in latitude. A web map tile is even in Web
  Mercator, so the coverage slides north by more than a kilometre at the
  top of Arizona and still looks like coverage.
- The uplink drawn as the downlink. A tall router talking to a handheld
  is not the same link as the reverse, and showing one as both promises
  reach that does not exist.
"""

import json
import struct
import zlib
from pathlib import Path

import numpy as np
import pytest

from sonoran.config import Settings
from sonoran.coverage.grid import (
    CELLS_PER_DEGREE,
    DBM_OFFSET,
    NO_COVERAGE,
    Grid,
    blit_max,
    combine_min,
    covered_area_km2,
    covered_cells,
    data_bounds,
    levels_from_raster,
    region_grid,
    to_dbm,
    to_level,
    union_bounds,
)
from sonoran.coverage.render import (
    COVER_ALPHA,
    RAMP,
    RAMP_SPAN_DB,
    TILE_SIZE,
    TileRef,
    colour_levels,
    sample_tile,
    tile_latitudes,
    tiles_for_grid,
    write_png,
)
from sonoran.coverage.sites import (
    HANDHELD_TX_POWER_DBM,
    downlink_offset_db,
    make_site,
    uplink_offset_db,
)
from sonoran.coverage.store import LAYERS, Manifest, PresetSummary, publish, read_manifest
from sonoran.radio.presets import preset_by_key
from sonoran.radio.resolve import resolve_profile

APP_CSS = Path("src/sonoran/web/static/app.css")


def _settings(tmp_path: Path, **extra: object) -> Settings:
    return Settings(
        _env_file=None,
        coverage_cache_dir=str(tmp_path / "coverage"),
        landcover_cache_dir=str(tmp_path / "landcover"),
        **extra,
    )


# --- the region grid ---------------------------------------------------


def test_the_region_grid_covers_the_terrain_box() -> None:
    """The map must cover the ground the terrain service serves.

    The settings hold inclusive degrees: 30 to 37 north means the box
    reaches 38 north.
    """
    grid = region_grid(30, 37, -116, -109)
    assert grid.north == 38.0
    assert grid.south == 30.0
    assert grid.west == -116.0
    assert grid.east == -108.0
    assert grid.width == 8 * CELLS_PER_DEGREE
    assert grid.height == 8 * CELLS_PER_DEGREE


def test_a_grid_reports_the_bounds_leaflet_takes() -> None:
    grid = region_grid(33, 33, -112, -112)
    assert grid.bounds() == (33.0, -112.0, 34.0, -111.0)


# --- putting a raster on the grid --------------------------------------


def _patch(north: float, west: float, size: int, dbm: float) -> tuple[np.ndarray, Grid]:
    grid = Grid(north=north, west=west, width=size, height=size)
    return np.full((size, size), to_level(dbm), dtype=np.uint8), grid


def test_a_raster_lands_on_the_grid_with_no_resampling() -> None:
    """Every engine raster shares the region lattice.

    So a raster is placed, not resampled. One cell of error moves every
    ridge line by 90 m and nothing on the map would look wrong.
    """
    grid = region_grid(33, 34, -112, -111)
    target = grid.empty()
    patch, patch_grid = _patch(north=35.0, west=-112.0, size=4, dbm=-100)

    set_count = blit_max(target, grid, patch, patch_grid)
    assert set_count == 16
    # Row 0 of the patch is the north edge of the region.
    assert to_dbm(target[0, 0]) == -100
    assert to_dbm(target[3, 3]) == -100
    assert target[4, 0] == NO_COVERAGE


def test_a_raster_offset_from_the_corner_lands_in_the_right_place() -> None:
    grid = region_grid(33, 34, -112, -111)
    target = grid.empty()
    # One degree south and one degree east of the region corner.
    patch, patch_grid = _patch(north=34.0, west=-111.0, size=2, dbm=-90)
    blit_max(target, grid, patch, patch_grid)

    row = CELLS_PER_DEGREE
    column = CELLS_PER_DEGREE
    assert to_dbm(target[row, column]) == -90
    assert target[row - 1, column] == NO_COVERAGE
    assert target[row, column - 1] == NO_COVERAGE


def test_a_raster_reaching_past_the_region_is_cut_at_the_edge() -> None:
    """A node near the border predicts over ground we do not serve."""
    grid = region_grid(33, 33, -112, -112)
    target = grid.empty()
    patch, patch_grid = _patch(north=34.5, west=-112.5, size=CELLS_PER_DEGREE, dbm=-100)

    set_count = blit_max(target, grid, patch, patch_grid)
    assert 0 < set_count < patch.size
    assert to_dbm(target[0, 0]) == -100


def test_a_raster_wholly_outside_the_region_sets_nothing() -> None:
    grid = region_grid(33, 33, -112, -112)
    target = grid.empty()
    patch, patch_grid = _patch(north=60.0, west=10.0, size=4, dbm=-90)
    assert blit_max(target, grid, patch, patch_grid) == 0
    assert not (target != NO_COVERAGE).any()


def test_the_stronger_node_wins_a_cell() -> None:
    """A place is served by the best node that reaches it."""
    grid = region_grid(33, 33, -112, -112)
    target = grid.empty()
    weak, weak_grid = _patch(north=34.0, west=-112.0, size=4, dbm=-120)
    strong, strong_grid = _patch(north=34.0, west=-112.0, size=4, dbm=-90)

    blit_max(target, grid, weak, weak_grid)
    blit_max(target, grid, strong, strong_grid)
    assert to_dbm(target[0, 0]) == -90

    # And the weaker one does not take it back.
    blit_max(target, grid, weak, weak_grid)
    assert to_dbm(target[0, 0]) == -90


def test_a_cell_nothing_reached_never_wins() -> None:
    """NO_COVERAGE is the smallest byte, so a maximum handles it.

    A hole in one node's coverage must not punch a hole in another's.
    """
    grid = region_grid(33, 33, -112, -112)
    target = grid.empty()
    strong, strong_grid = _patch(north=34.0, west=-112.0, size=4, dbm=-90)
    blit_max(target, grid, strong, strong_grid)

    empty_grid = Grid(north=34.0, west=-112.0, width=4, height=4)
    empty = np.full((4, 4), NO_COVERAGE, dtype=np.uint8)
    assert blit_max(target, grid, empty, empty_grid) == 0
    assert to_dbm(target[0, 0]) == -90


def test_two_grids_of_different_resolution_are_refused() -> None:
    grid = region_grid(33, 33, -112, -112)
    other = Grid(north=34.0, west=-112.0, width=4, height=4, cells_per_degree=3600)
    with pytest.raises(ValueError, match="resolution"):
        blit_max(grid.empty(), grid, np.zeros((4, 4), dtype=np.uint8), other)


# --- the two directions ------------------------------------------------


def test_a_place_only_one_direction_reaches_is_not_usable() -> None:
    """The mesh must hear the handheld and the handheld the mesh."""
    down = np.array([[to_level(-90), to_level(-90), NO_COVERAGE]], dtype=np.uint8)
    up = np.array([[to_level(-100), NO_COVERAGE, to_level(-100)]], dtype=np.uint8)
    usable = combine_min(down, up)
    assert to_dbm(usable[0, 0]) == -100  # the weaker of the two decides
    assert usable[0, 1] == NO_COVERAGE
    assert usable[0, 2] == NO_COVERAGE


def test_the_two_directions_differ_only_by_the_transmit_powers() -> None:
    """One engine run gives both layers. See coverage/sites.py.

    The whole antenna of the node cancels between the two directions,
    because it helps the same amount whichever end transmits.
    """
    settings = Settings(_env_file=None)
    preset = preset_by_key("LONG_FAST")
    assert preset is not None
    profile = resolve_profile("!a", "RAK4631")
    site = make_site(settings, "!a", 1, "a", 33.4, -112.0, profile, preset)

    difference = uplink_offset_db(settings, site) - downlink_offset_db(settings)
    assert difference == pytest.approx(HANDHELD_TX_POWER_DBM - profile.tx_power_dbm)


def test_a_louder_node_is_heard_further_than_it_hears() -> None:
    """A one watt router out-shouts a handheld by eight dB."""
    settings = Settings(_env_file=None)
    preset = preset_by_key("LONG_FAST")
    assert preset is not None
    profile = resolve_profile("!a", "STATION_G2")
    assert profile.tx_power_dbm == 30.0
    site = make_site(settings, "!a", 1, "a", 33.4, -112.0, profile, preset)

    difference = uplink_offset_db(settings, site) - downlink_offset_db(settings)
    assert difference == pytest.approx(HANDHELD_TX_POWER_DBM - 30.0)
    assert difference < 0, "the uplink must be the worse direction here"


# --- levels ------------------------------------------------------------


def test_a_cell_the_sweep_never_reached_carries_no_level() -> None:
    """The signal byte holds whatever it held. Read the mask first."""
    signal = bytes([120, 130])
    mask = bytes([0b1111_1000, 0b0000_0111])
    levels = levels_from_raster(signal, mask, 0b1111_1000, 2, 1)
    assert to_dbm(levels[0, 0]) == -80
    assert levels[0, 1] == NO_COVERAGE


def test_the_low_three_bits_of_a_mask_are_not_a_coverage_flag() -> None:
    """That is why the test is against 248 and not against zero."""
    levels = levels_from_raster(bytes([150]), bytes([0b0000_0101]), 0b1111_1000, 1, 1)
    assert levels[0, 0] == NO_COVERAGE


def test_a_level_below_minus_one_hundred_and_twenty_eight_survives() -> None:
    """A signed byte cannot hold the sensitivity of Long fast.

    Levels were held as signed bytes once. Every level clipped at -127,
    every level then sat above every threshold, and the usable filter
    passed the whole map. The offset byte is what stops that.
    """
    assert to_dbm(to_level(-139.0)) == -139.0
    assert to_dbm(to_level(-147.5)) == pytest.approx(-148.0, abs=1.0)
    assert to_level(-139.0) == -139 + DBM_OFFSET

    weak = np.array([[to_level(-150.0)]], dtype=np.uint8)
    strong = np.array([[to_level(-100.0)]], dtype=np.uint8)
    assert covered_cells(weak, -139.0) == 0, "a level below the preset must not count"
    assert covered_cells(strong, -139.0) == 1


# --- area and bounds ---------------------------------------------------


def test_area_is_weighted_by_latitude() -> None:
    """A cell of longitude narrows as it goes north.

    Counting cells without that overstates the north of a region.
    """
    south = Grid(north=1.0, west=0.0, width=100, height=100)
    north = Grid(north=61.0, west=0.0, width=100, height=100)
    levels = np.full((100, 100), to_level(-100), dtype=np.uint8)
    assert covered_area_km2(levels, south, -139) > covered_area_km2(levels, north, -139)


def test_only_cells_above_the_threshold_count() -> None:
    levels = np.array([[to_level(-100), to_level(-150), NO_COVERAGE]], dtype=np.uint8)
    grid = Grid(north=34.0, west=-112.0, width=3, height=1)
    assert covered_cells(levels, -100) == 1
    assert covered_area_km2(levels, grid, -100) > 0


def test_the_data_bounds_hold_the_coverage_and_not_the_region() -> None:
    """The page opens on this. The region is far larger."""
    grid = region_grid(33, 34, -112, -111)
    levels = grid.empty()
    levels[100:110, 200:220] = to_level(-100)

    box = data_bounds(levels, grid, -139)
    assert box is not None
    south, west, north, east = box
    assert north < grid.north
    assert south > grid.south
    assert west > grid.west
    assert east < grid.east


def test_no_coverage_gives_no_data_bounds() -> None:
    grid = region_grid(33, 33, -112, -112)
    assert data_bounds(grid.empty(), grid, -139) is None
    assert union_bounds([]) is None
    assert union_bounds([[], []]) is None


def test_union_bounds_holds_every_box() -> None:
    assert union_bounds([[1.0, 2.0, 3.0, 4.0], [0.0, 5.0, 2.0, 9.0]]) == [0.0, 2.0, 3.0, 9.0]


# --- tiles -------------------------------------------------------------


def test_a_tile_is_read_in_mercator_and_not_evenly_in_latitude() -> None:
    """A row near the top of a tile covers more ground than one below.

    Reading evenly slides the coverage north by over a kilometre at the
    top of Arizona, and it still looks like coverage.
    """
    latitudes = tile_latitudes(TileRef(6, 12, 25))
    assert len(latitudes) == TILE_SIZE
    assert latitudes[0] > latitudes[-1]
    steps = -np.diff(latitudes)
    assert steps[0] != pytest.approx(steps[-1], rel=1e-3)


def test_a_tile_outside_the_grid_is_empty() -> None:
    grid = region_grid(33, 33, -112, -112)
    levels = np.full((grid.height, grid.width), to_level(-100), dtype=np.uint8)
    far = sample_tile(levels, grid, TileRef(6, 0, 0))
    assert (far == NO_COVERAGE).all()


def test_the_tiles_of_a_zoom_cover_the_grid() -> None:
    grid = region_grid(33, 34, -112, -111)
    tiles = tiles_for_grid(grid, 7)
    assert tiles
    assert all(0 <= tile.x < 128 and 0 <= tile.y < 128 for tile in tiles)
    # A finer zoom needs more tiles for the same ground.
    assert len(tiles_for_grid(grid, 8)) > len(tiles)


def test_ground_below_the_threshold_is_left_clear() -> None:
    """The basemap must stay readable. Painting the rest hides it."""
    levels = np.array([[to_level(-100), to_level(-150), NO_COVERAGE]], dtype=np.uint8)
    image = colour_levels(levels, -100)
    assert image[0, 0, 3] == COVER_ALPHA
    assert image[0, 1, 3] == 0
    assert image[0, 2, 3] == 0


def test_the_ramp_runs_from_the_limit_to_the_span_above_it() -> None:
    weak = np.array([[to_level(-139)]], dtype=np.uint8)
    strong = np.array([[to_level(-139 + RAMP_SPAN_DB)]], dtype=np.uint8)
    assert tuple(colour_levels(weak, -139)[0, 0, :3]) == RAMP[0]
    assert tuple(colour_levels(strong, -139)[0, 0, :3]) == RAMP[-1]


def test_the_ramp_colours_are_the_ones_the_stylesheet_draws() -> None:
    """Python cannot read a stylesheet, so the values exist twice.

    The legend on the page is a CSS gradient and the tiles come from
    this table. Two palettes would put a legend on the page that does
    not describe the map beside it.
    """
    css = APP_CSS.read_text(encoding="utf-8")
    for red, green, blue in RAMP:
        assert f"#{red:02x}{green:02x}{blue:02x}" in css


def test_a_written_tile_is_a_png_a_browser_can_read() -> None:
    image = np.zeros((TILE_SIZE, TILE_SIZE, 4), dtype=np.uint8)
    image[10, 20] = (0xF4, 0x70, 0x3F, COVER_ALPHA)
    png = write_png(image)

    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    length = struct.unpack(">I", png[8:12])[0]
    assert png[12:16] == b"IHDR"
    width, height, depth, colour_type = struct.unpack(">IIBB", png[16 : 16 + 10])
    assert (width, height, depth, colour_type) == (TILE_SIZE, TILE_SIZE, 8, 6)
    # signature 8, then length 4, type 4, payload, crc 4.
    idat_length_at = 8 + 4 + 4 + length + 4
    assert png[idat_length_at + 4 : idat_length_at + 8] == b"IDAT"
    assert png.endswith(b"IEND\xae\x42\x60\x82")

    # And the pixels come back.
    body_length = struct.unpack(">I", png[idat_length_at : idat_length_at + 4])[0]
    start = idat_length_at + 8
    body = png[start : start + body_length]
    rows = zlib.decompress(body)
    stride = TILE_SIZE * 4 + 1
    assert len(rows) == stride * TILE_SIZE
    assert rows[10 * stride] == 0  # the filter byte of the row
    assert rows[10 * stride + 1 + 20 * 4 : 10 * stride + 1 + 20 * 4 + 4] == bytes(
        (0xF4, 0x70, 0x3F, COVER_ALPHA)
    )


# --- the run on disk ---------------------------------------------------


def _manifest(stamp: str) -> Manifest:
    return Manifest(
        stamp=stamp,
        generated_at="2026-08-20T00:00:00+00:00",
        engine="test",
        bounds=[30.0, -116.0, 38.0, -108.0],
        min_zoom=6,
        max_zoom=11,
        radius_km=35.0,
        rx_height_m=1.5,
        rx_gain_dbi=2.15,
        handheld_tx_power_dbm=22.0,
        has_terrain=True,
        has_landcover=False,
        calibrated_nodes=0,
        missing_terrain_tiles=[],
        seconds=1.0,
        presets=[
            PresetSummary(
                preset="LongFast",
                label="Long fast",
                sensitivity_dbm=-139.0,
                node_count=1,
                positioned_count=1,
                skipped_count=0,
                usable_area_km2=1.0,
                downlink_area_km2=1.0,
                tile_count=1,
            )
        ],
    )


def test_a_run_becomes_visible_in_one_step(tmp_path: Path) -> None:
    """A reader must never see half a run.

    A map that says it was made at nine and shows the mesh as it was at
    six is worse than no map.
    """
    settings = _settings(tmp_path)
    assert read_manifest(settings) is None

    from sonoran.coverage import store

    pending = store.pending_dir(settings, "20260820T000000Z")
    (pending / "LongFast" / "usable" / "6" / "12").mkdir(parents=True)
    (pending / "LongFast" / "usable" / "6" / "12" / "25.png").write_bytes(b"x")

    publish(settings, "20260820T000000Z", _manifest("20260820T000000Z"))
    read = read_manifest(settings)
    assert read is not None
    assert read["stamp"] == "20260820T000000Z"
    assert store.read_tile(settings, "LongFast", "usable", 6, 12, 25) == b"x"
    assert store.read_tile(settings, "LongFast", "usable", 6, 12, 99) is None


def test_old_runs_are_removed(tmp_path: Path) -> None:
    from sonoran.coverage import store

    settings = _settings(tmp_path)
    for stamp in ("20260820T000001Z", "20260820T000002Z", "20260820T000003Z"):
        store.pending_dir(settings, stamp).mkdir(parents=True)
        publish(settings, stamp, _manifest(stamp))

    kept = sorted(path.name for path in store.runs_dir(settings).iterdir())
    assert kept == ["20260820T000002Z", "20260820T000003Z"]


def test_a_stamped_tile_never_moves_to_a_new_run(tmp_path: Path) -> None:
    """A cache key must always identify the same bytes."""
    from sonoran.coverage import store

    settings = _settings(tmp_path)
    for stamp, content in (
        ("20260820T000001Z", b"first"),
        ("20260820T000002Z", b"second"),
    ):
        pending = store.pending_dir(settings, stamp)
        tile = pending / "LongFast" / "usable" / "6" / "12" / "25.png"
        tile.parent.mkdir(parents=True)
        tile.write_bytes(content)
        publish(settings, stamp, _manifest(stamp))

    assert (
        store.read_run_tile(settings, "20260820T000001Z", "LongFast", "usable", 6, 12, 25)
        == b"first"
    )
    assert (
        store.read_run_tile(settings, "20260820T000002Z", "LongFast", "usable", 6, 12, 25)
        == b"second"
    )
    assert store.read_tile(settings, "LongFast", "usable", 6, 12, 25) == b"second"


def test_a_broken_index_reads_as_no_run(tmp_path: Path) -> None:
    """A half written file must not stop the page loading."""
    from sonoran.coverage import store

    settings = _settings(tmp_path)
    path = store.index_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    assert store.current_stamp(settings) is None
    assert read_manifest(settings) is None


def test_an_index_pointing_at_a_run_that_is_gone_reads_as_no_run(tmp_path: Path) -> None:
    from sonoran.coverage import store

    settings = _settings(tmp_path)
    path = store.index_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"current": "20260820T000000Z"}), encoding="utf-8")
    assert store.current_root(settings) is None
    assert read_manifest(settings) is None


def test_every_layer_has_a_label() -> None:
    from sonoran.coverage.store import LAYER_LABELS

    assert set(LAYERS) == set(LAYER_LABELS)
    assert LAYERS[0] == "usable", "the honest layer must be the first one a page shows"


def test_a_run_stamp_that_is_not_a_stamp_is_refused(tmp_path: Path) -> None:
    """The stamp is read from a file and becomes part of a path.

    Nothing else writes that file, so this is not a hole today. It is
    checked anyway, because a path built from a value read off disk is
    the shape of one.
    """
    from sonoran.coverage import store

    settings = _settings(tmp_path)
    path = store.index_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)

    for bad in ("../../etc", "/etc/passwd", "20260820T000000Z/../..", "", "not-a-stamp"):
        path.write_text(json.dumps({"current": bad}), encoding="utf-8")
        assert store.current_stamp(settings) is None, bad
        assert store.current_root(settings) is None
        assert store.read_tile(settings, "LongFast", "usable", 6, 12, 25) is None
        assert store.read_run_tile(settings, bad, "LongFast", "usable", 6, 12, 25) is None

    path.write_text(json.dumps({"current": "20260820T000000Z"}), encoding="utf-8")
    assert store.current_stamp(settings) == "20260820T000000Z"


# --- what a run holds in memory ----------------------------------------
#
# A three hundred node run over Arizona wants about forty terrain pages.
# The first build sent the whole set to every worker process through the
# pool, which is 110 MB in the parent and another copy in each worker,
# and the pool died on a machine that could not carry it. The pages are
# now read from the disk cache by whichever process needs them.


def test_a_worker_reads_terrain_from_the_disk_cache(tmp_path: Path) -> None:
    """Nothing sends a terrain page through the process pool."""
    from sonoran.jobs import coverage

    assert not hasattr(coverage, "_WORKER_PAGES")
    assert coverage._worker_start.__code__.co_argcount == 0


def test_the_page_hold_is_bounded(tmp_path: Path) -> None:
    """A page is 2.7 MB. The hold must not grow with the region."""
    from sonoran.jobs import coverage
    from sonoran.terrain.srtm import PAGE_BYTES

    settings = _settings(tmp_path, terrain_cache_dir=str(tmp_path / "terrain"))
    (tmp_path / "terrain").mkdir(parents=True)
    names = [f"N3{index // 10}W1{10 + index % 10:02d}" for index in range(40)]
    for name in names:
        (tmp_path / "terrain" / f"{name}.page.i16").write_bytes(b"\x00" * PAGE_BYTES)

    coverage._page_cache.clear()
    try:
        for name in names:
            assert coverage.read_page(settings, name) is not None
        assert len(coverage._page_cache) == coverage.PAGE_CACHE_SIZE
        # The names still in the hold are the ones asked for last.
        assert list(coverage._page_cache) == names[-coverage.PAGE_CACHE_SIZE :]
    finally:
        coverage._page_cache.clear()


def test_a_page_that_is_absent_is_held_as_absent(tmp_path: Path) -> None:
    """Asking again must not read the disk again for every site."""
    from sonoran.jobs import coverage

    settings = _settings(tmp_path, terrain_cache_dir=str(tmp_path / "terrain"))
    coverage._page_cache.clear()
    try:
        assert coverage.read_page(settings, "N34W112") is None
        assert "N34W112" in coverage._page_cache
    finally:
        coverage._page_cache.clear()


def test_the_run_keeps_tile_names_and_not_tile_bytes(tmp_path: Path) -> None:
    """`ensure_terrain` answers with names. Bytes would be the bug."""
    import asyncio

    from sonoran.jobs import coverage
    from sonoran.terrain.srtm import PAGE_BYTES

    settings = _settings(
        tmp_path, terrain_cache_dir=str(tmp_path / "terrain"), terrain_allow_download=False
    )
    (tmp_path / "terrain").mkdir(parents=True)
    (tmp_path / "terrain" / "N34W112.page.i16").write_bytes(b"\x00" * PAGE_BYTES)

    held = asyncio.run(coverage.ensure_terrain(settings, ["N34W112", "N34W113"]))
    assert held == {"N34W112"}


def test_a_dead_worker_pool_costs_time_and_not_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A pool that dies must fall back, not lose every preset.

    The retry must also start from empty grids. A retry that carried
    the half finished accumulators would blit every site that already
    landed a second time.
    """
    from concurrent.futures.process import BrokenProcessPool

    from sonoran.jobs import coverage

    settings = _settings(tmp_path)
    grid = region_grid(33, 33, -112, -112)
    calls: list[int] = []

    def fake_predict(
        _settings: Settings, _grid: Grid, _sites: object, workers: int
    ) -> tuple[object, object, list[dict[str, object]], set[str]]:
        calls.append(workers)
        if workers > 1:
            raise BrokenProcessPool("out of memory")
        return _grid.empty(), _grid.empty(), [], set()

    monkeypatch.setattr(coverage, "_predict", fake_predict)
    coverage.predict_preset(settings, grid, [], 4)
    assert calls == [4, 1]
