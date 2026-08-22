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

import inspect
import json
import os
import re
import struct
import zlib
from collections import Counter
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

STATIC = Path("src/sonoran/web/static")
APP_CSS = Path("src/sonoran/web/static/app.css")
COVERAGE_JS = Path("src/sonoran/web/static/coverage.js")
INDEX_HTML = Path("src/sonoran/web/static/index.html")


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


def test_the_ramp_is_distinct_from_the_terrain_map() -> None:
    """The coverage edge and strength must remain visible over terrain."""
    assert RAMP == (
        (0xFF, 0x2D, 0x55),
        (0xFF, 0x7A, 0x00),
        (0xFF, 0xE6, 0x00),
        (0x00, 0xD9, 0x8B),
        (0x00, 0xA8, 0xFF),
    )
    assert COVER_ALPHA >= 230


def _gradient_stops(text: str, selector: str) -> list[tuple[int, int, int]]:
    """Return the colours of the `linear-gradient` in one CSS rule."""
    rule = re.search(re.escape(selector) + r"\s*\{(.*?)\}", text, re.S)
    assert rule, f"no rule for {selector}"
    gradient = re.search(r"linear-gradient\((.*?)\)", rule.group(1), re.S)
    assert gradient, f"no gradient in {selector}"
    return [
        (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))
        for value in re.findall(r"#([0-9a-fA-F]{6})", gradient.group(1))
    ]


@pytest.mark.parametrize(
    ("path", "selector"),
    [
        (STATIC / "app.css", ".coverage-ramp"),
        (STATIC / "embed-coverage.html", ".ramp"),
    ],
)
def test_every_legend_draws_the_ramp_the_tiles_use(path: Path, selector: str) -> None:
    """Python cannot write a stylesheet, so the values exist twice.

    This asserts the stops in order, not that each colour appears
    somewhere. The test it replaced did the second, and every colour in
    the old ramp was also a palette variable, so it would have passed
    with the gradient deleted outright. It did not notice when the tile
    ramp changed and the embed's legend did not.
    """
    assert _gradient_stops(path.read_text(encoding="utf-8"), selector) == list(RAMP)


def test_no_stylesheet_filter_reaches_a_coverage_tile() -> None:
    """The coverage overlay is the one thing whose colour means
    something, and a pane-wide filter inverted it.

    A rule that filters `.leaflet-tile-pane` itself catches every tile
    layer in it, the overlay included. The filter must name the basemap.
    """
    css = APP_CSS.read_text(encoding="utf-8")
    for rule in re.finditer(r"([^{}]+)\{([^}]*)\}", css):
        if "filter:" not in rule.group(2):
            continue
        assert rule.group(1).strip() != ".leaflet-tile-pane", (
            "this filter also inverts the coverage overlay"
        )


def test_every_base_layer_is_named_for_the_filter() -> None:
    """A map that forgets the class loses its dark basemap, and one
    that is added later inherits the bug invisibly."""
    for name in ("app.js", "coverage.js", "planner.js", "embed-coverage.js"):
        text = (STATIC / name).read_text(encoding="utf-8")
        assert text.count("basemap-tiles") == text.count("L.tileLayer(CONFIG.tileUrl"), name
    assert ".basemap-tiles" in APP_CSS.read_text(encoding="utf-8")


def test_the_map_layers_can_be_switched_independently() -> None:
    """Map, node, and signal controls must not depend on each other."""
    html = INDEX_HTML.read_text(encoding="utf-8")
    script = COVERAGE_JS.read_text(encoding="utf-8")

    assert "data-coverage-views" in html
    for state_name in ("showMap", "showNodes", "showSignal"):
        assert state_name in script
    assert "api/map/nodes?channel=" in script


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
                candidate_count=1,
                site_count=1,
                excluded_by_role={},
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


def test_a_stored_calibration_is_bounded_before_it_is_used(tmp_path: Path) -> None:
    """An old report must not bypass the calibration safety bound."""
    from sonoran.coverage import store

    settings = _settings(tmp_path)
    path = store.calibration_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "model_bias_db": 0.0,
                "residual_spread_db": 5.0,
                "nodes": [
                    {
                        "node_id": "!low",
                        "offset_db": -1830.35,
                        "observations": 7,
                        "counterparties": 7,
                        "reported": 2,
                    },
                    {
                        "node_id": "!bad",
                        "offset_db": "not-a-number",
                        "observations": 7,
                        "counterparties": 7,
                        "reported": 2,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    assert store.calibration_offsets(settings) == {"!low": -15.0}


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
    """Nothing sends a terrain page through the process pool.

    The initialiser takes one argument, the niceness, which is an int.
    Anything bigger crossing here is copied into every worker at start
    up, which is how the pool died on a small machine, so the test
    pins the size of what may cross rather than that nothing does.
    """
    import inspect

    from sonoran.jobs import coverage

    assert not hasattr(coverage, "_WORKER_PAGES")
    parameters = list(inspect.signature(coverage._worker_start).parameters.values())
    assert [(item.name, item.annotation) for item in parameters] == [("nice", int)]


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
        if workers >= 1:
            raise BrokenProcessPool("out of memory")
        return _grid.empty(), _grid.empty(), [], set()

    monkeypatch.setattr(coverage, "_predict", fake_predict)
    coverage.predict_preset(settings, grid, [], 4)
    # Zero, not one. One worker is still a worker process, and is the
    # answer for a small box, because a worker can be niced and a run
    # inside the jobs process cannot be without slowing every other job
    # down. Zero is the crash fallback and means "in this process".
    assert calls == [4, 0]


def test_the_ramp_span_is_served_and_not_copied() -> None:
    """Python writes the tiles, so Python owns the span.

    It used to be a literal 30 in three places. `render.py` moved to 60
    and a page holding its own copy would have drawn a legend that
    disagreed with the map beside it, which is worse than no legend.
    """
    from sonoran.coverage.store import Manifest

    assert "ramp_span_db" in Manifest.__dataclass_fields__
    assert Manifest.__dataclass_fields__["ramp_span_db"].default == RAMP_SPAN_DB

    for name in ("coverage.js", "embed-coverage.js"):
        text = (STATIC / name).read_text(encoding="utf-8")
        assert "ramp_span_db" in text, f"{name} must read the span from the run"
        assert "RAMP_SPAN_DB = 30" not in text
        assert "floor + 30" not in text


def test_the_span_is_wide_enough_to_say_something() -> None:
    """Measured on the live Arizona mesh: 16 sites, 1.5 million covered
    cells, median margin 35 dB and p95 55 dB.

    At the old 30 dB span, 60 percent of the map sat at the top stop
    and every cell there was the same blue. A colour that covers most
    of the map is not a measurement. See `coverage/render.py`.
    """
    live_percentiles = {5: 3, 25: 20, 50: 35, 75: 46, 95: 55}
    assert RAMP_SPAN_DB >= live_percentiles[95], (
        "the ramp must reach past the 95th percentile of a real map"
    )
    # And the median must land where the colours are furthest apart.
    middle = live_percentiles[50] / RAMP_SPAN_DB
    assert 0.4 < middle < 0.75, f"the median sits at {middle:.2f} of the ramp"


# --- the two ways a map can claim reach it does not have ----------------


def test_the_calibration_reaches_the_uplink_too() -> None:
    """The correction must not cancel itself out.

    The engine is set up with the corrected power, so taking the
    corrected power off again on the uplink cancels it exactly. It did,
    and the handheld is the weaker end almost everywhere, so `usable`
    was drawn from the uncalibrated prediction: a node measured 9 dB
    below its nameplate was still painted at its nameplate.
    """
    from sonoran.config import Settings
    from sonoran.coverage.sites import (
        HANDHELD_TX_POWER_DBM,
        make_site,
        uplink_offset_db,
    )
    from sonoran.radio.presets import preset_for_channel
    from sonoran.radio.resolve import resolve_profile

    settings = Settings(_env_file=None)
    preset = preset_for_channel("LongFast")
    assert preset is not None
    loss_db = 120.0

    for correction in (0.0, -9.0, +6.0):
        profile = resolve_profile("!d", "RAK4631", calibration_offset_db=correction)
        site = make_site(settings, "!d", 1, "d", 33.4, -112.0, profile, preset)
        # What the engine puts on the ground, which already holds the
        # correction because `engine_params` put it in the power.
        field = (
            profile.tx_power_dbm
            + profile.calibration_offset_db
            + profile.antenna_gain_dbi
            - profile.cable_loss_db
            - loss_db
        )
        uplink = field + uplink_offset_db(settings, site)
        # The handheld transmits; the node's antenna, cable and its own
        # measured correction all apply at the receiving end.
        expected = (
            HANDHELD_TX_POWER_DBM
            + settings.coverage_rx_gain_dbi
            + profile.antenna_gain_dbi
            - profile.cable_loss_db
            + correction
            - loss_db
        )
        assert uplink == pytest.approx(expected, abs=1e-9), correction


def test_usable_is_the_weaker_direction_of_one_node() -> None:
    """Not the weaker of the best of each direction.

    Taking the best downlink and the best uplink and then the weaker of
    the two lets one node answer for one direction and another node for
    the other. A tall router a handheld cannot answer, beside a solar
    node the handheld can reach but which cannot be heard back, then
    paints as usable both ways. The mesh does not work there.
    """
    from sonoran.coverage.grid import combine_min, to_dbm, to_level

    threshold = -134.0
    tall = (-130.0, -138.0)  # a mast: heard far, cannot hear back
    solar = (-136.0, -131.0)  # a small node: hears well, is not heard

    def level(value: float) -> np.ndarray:
        return np.array([[to_level(value)]], dtype=np.uint8)

    # Neither node closes both directions on its own.
    for down, up in (tall, solar):
        assert min(down, up) < threshold

    wrong = combine_min(
        np.maximum(level(tall[0]), level(solar[0])),
        np.maximum(level(tall[1]), level(solar[1])),
    )
    right = np.maximum(
        combine_min(level(tall[0]), level(tall[1])),
        combine_min(level(solar[0]), level(solar[1])),
    )
    assert to_dbm(int(wrong[0, 0])) >= threshold, "the old order painted this covered"
    assert to_dbm(int(right[0, 0])) < threshold, "and the right order does not"


def test_the_job_builds_usable_from_each_site() -> None:
    """`_predict` must return its own usable layer, not one derived
    from the other two afterwards."""
    import inspect

    from sonoran.jobs import coverage

    source = inspect.getsource(coverage._predict)
    assert "blit_max(usable, grid, combine_min(" in source
    assert "return downlink, uplink, usable, notes, missing" in source


def test_a_preset_that_kept_no_site_is_still_reported(tmp_path: Path) -> None:
    """A preset whose nodes were all clients used to vanish.

    `_build` iterated the sites it kept, so a preset with candidates
    and no survivors produced no summary at all, and a reader concluded
    the mesh does not use it. That is the opposite of what the counts
    are for.
    """
    import inspect

    from sonoran.jobs import coverage

    source = inspect.getsource(coverage._build)
    assert "set(groups) | set(left_out)" in source, "iterate every preset that had a candidate"
    assert "_empty_summary" in source

    summary = coverage._empty_summary("LONG_FAST", Counter({"NULL": 40, "CLIENT": 2}))
    assert summary.site_count == 0
    assert summary.candidate_count == 42
    assert summary.excluded_by_role == {"CLIENT": 2, "NULL": 40}
    assert summary.usable_area_km2 == 0.0
    assert summary.data_bounds is None


def test_a_half_built_run_is_cleared_before_the_next_one(tmp_path: Path) -> None:
    """A run that dies is never published, so nothing else removes it.

    `prune` reads `runs`; a pending directory sits beside it. A run of
    the Arizona mesh writes 16 MB, and a job failing every six hours
    adds that four times a day until the volume fills.
    """
    from sonoran.coverage import store

    settings = _settings(tmp_path)
    root = Path(settings.coverage_cache_dir)
    root.mkdir(parents=True, exist_ok=True)
    for stamp in ("20260101T000000Z", "20260102T000000Z"):
        (root / f"pending-{stamp}").mkdir()
    (root / "pending-20260103T000000Z").mkdir()

    assert store.clear_pending(settings, keep="20260103T000000Z") == 2
    assert [path.name for path in root.glob("pending-*")] == ["pending-20260103T000000Z"]
    # And the run in progress is untouched on a second call.
    assert store.clear_pending(settings, keep="20260103T000000Z") == 0


# --- keeping the box usable while a run happens ------------------------
#
# Tyler asked for this in the review thread: "have it run on a single
# low priority thread too". Logan's machine was audibly struggling
# through a run. The engine is a solid floating point loop with no IO
# to yield on, so without this it takes every core it is given and
# holds them for minutes, on a box that is also serving the dashboard
# and taking MQTT.


def test_the_worker_priority_is_only_ever_lowered() -> None:
    """A process cannot raise its own priority back afterwards.

    So a negative setting must be refused rather than acted on. If it
    were applied, the run would take priority over the API on the same
    box and there would be no way to undo it short of a restart.
    """
    from sonoran.jobs import coverage

    seen: list[int] = []
    original = os.nice

    def fake_nice(value: int) -> int:
        seen.append(value)
        return value

    try:
        os.nice = fake_nice  # type: ignore[assignment]
        coverage._be_nice(-5)
        coverage._be_nice(0)
        assert seen == []
        coverage._be_nice(10)
        assert seen == [10]
    finally:
        os.nice = original  # type: ignore[assignment]


def test_a_host_without_nice_is_left_alone() -> None:
    """The setting must not be able to stop a run on a platform that
    has no such thing."""
    from sonoran.jobs import coverage

    original = os.nice
    try:
        del os.nice  # type: ignore[attr-defined]
        coverage._be_nice(10)
    finally:
        os.nice = original  # type: ignore[assignment]


def test_the_niceness_reaches_the_workers(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """It is set in the initialiser, so it applies to every worker.

    Setting it in the parent would be wrong: the jobs process also runs
    the snapshot and the calibration, and it cannot put its priority
    back.
    """
    import inspect

    from sonoran.jobs import coverage

    source = inspect.getsource(coverage._predict)
    assert "initargs=(settings.coverage_worker_nice,)" in source
    assert "_be_nice" in inspect.getsource(coverage._worker_start)


# --- naming the sites an operator has to fix ---------------------------
#
# The assumptions panel says "34 of those are routers whose position the
# broker rounded off. Give each one a latitude and longitude in
# config/nodes.yaml". A count is not an instruction: without the names
# there is no way to act on it, and on the live mesh this is the single
# biggest thing standing between the map and the other 34 sites.


def test_the_page_writes_a_block_the_overrides_parser_accepts() -> None:
    """The snippet is pasted into a real file and read by a real parser.

    So the shape it writes has to be the shape `parse_overrides` reads.
    These two are in different languages and nothing else connects
    them, which is exactly how a format drifts.
    """
    from sonoran.radio.overrides import parse_overrides

    script = (STATIC / "coverage.js").read_text(encoding="utf-8")
    assert "function coarseYaml" in script

    # The same lines the function builds, for the shape it builds them
    # in. A change to one without the other fails here.
    text = "\n".join(
        [
            "nodes:",
            "  # Shaw Butte (ROUTER, 2,921 m out)",
            '  "!0a51b007":',
            "    latitude: 33.5891",
            "    longitude: -112.0912",
        ]
    )
    overrides = parse_overrides(text)
    assert overrides.position_of("!0a51b007") == (33.5891, -112.0912)

    # And the keys the script writes are the keys the parser reads.
    assert "latitude: ${site.rounded_lat}" in script
    assert "longitude: ${site.rounded_lon}" in script
    assert '"${site.node_id}":' in script


def test_the_named_list_is_bounded_and_the_count_is_not() -> None:
    """Nobody fixes two hundred sites by hand.

    The list is capped so the manifest stays small. The count in
    `excluded_by_role` is the whole number, so a shortened list can
    never read as the whole story.
    """
    from sonoran.jobs import coverage

    assert coverage.COARSE_REPORT_LIMIT <= 100
    source = inspect.getsource(coverage.group_by_preset)
    # The counter is incremented before the cap is tested, so the cap
    # cannot reach it.
    assert source.index("rejected[COARSE_POSITION] += 1") < source.index("COARSE_REPORT_LIMIT")


def test_the_one_shot_command_sets_its_logging_up() -> None:
    """A command made to be watched must say something.

    `sonoran-coverage-once` exists so an operator bringing a box up can
    see the first run happen. Nothing else in that process configures
    logging, so without this it runs for five minutes and prints not
    one line: no site count, no progress, no completion. It looked
    exactly like a hang.

    `jobs/scheduler.py::run` does the same thing for the same reason.
    """
    from sonoran.jobs import coverage

    source = inspect.getsource(coverage.run)
    assert "configure_logging" in source
    assert source.index("configure_logging") < source.index("asyncio.run")
