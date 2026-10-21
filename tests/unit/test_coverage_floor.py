"""The signal floor of the coverage map (#334, item 4).

The colour tiles hold colours, not levels. The job therefore also writes
one grey margin tile for each colour tile, and the dashboard colours it
in the browser above the floor the reader chose. These tests pin:

- The margin byte round-trips exactly: byte 0 is no usable coverage, and
  byte `n` is `n - 1` dB above what the radio needs.
- The colour tiles are byte-identical to the tiles written before the
  floor existed. The public embed serves those and nothing else.
- No public path reaches a margin tile.
- A run made before this change still renders, and the page can tell
  that it has no margin data.
"""

import hashlib
import json
import shutil
import subprocess
import zlib
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from sonoran.api.app import create_app
from sonoran.config import Settings
from sonoran.coverage import store
from sonoran.coverage.grid import NO_COVERAGE, region_grid, to_level
from sonoran.coverage.render import (
    COVER_ALPHA,
    MARGIN_ENCODING,
    RAMP,
    RAMP_SPAN_DB,
    TILE_SIZE,
    colour_levels,
    margin_db,
    margin_levels,
    write_grey_png,
    write_png,
)
from sonoran.radio.presets import PRESETS, ModemPreset, sensitivity_of

STATIC = Path("src/sonoran/web/static")
INDEX_HTML = STATIC / "index.html"
CASES = Path("tests/unit/js/coverage_floor_cases.mjs")

THRESHOLD = -139.0


def _levels(*margins: int) -> np.ndarray:
    floor = to_level(THRESHOLD)
    return np.array([[floor + margin for margin in margins]], dtype=np.uint8)


# --- the encoding ------------------------------------------------------


@pytest.mark.parametrize("margin", [0, 5, 10, 20, 60, 100, 194])
def test_a_margin_round_trips_exactly(margin: int) -> None:
    """Every floor the panel offers, the top of the ramp, and past it.

    The levels are whole dB and the threshold meets them as a whole byte
    (`to_level`), so the margin is a whole number and nothing is rounded
    on the way into the byte.
    """
    encoded = margin_levels(_levels(margin), THRESHOLD)
    assert encoded.dtype == np.uint8
    assert margin_db(int(encoded[0, 0])) == margin


def test_the_largest_margin_a_level_can_hold_still_fits() -> None:
    """A threshold at the weakest level leaves 254 dB of room, byte 255."""
    levels = np.array([[255]], dtype=np.uint8)
    encoded = margin_levels(levels, -199.0)
    assert int(encoded[0, 0]) == 255
    assert margin_db(255) == 254


def test_ground_below_the_threshold_stays_empty_in_the_margin_tile() -> None:
    """Byte zero is the one thing a margin tile says about weak ground."""
    floor = to_level(THRESHOLD)
    levels = np.array([[floor - 1, NO_COVERAGE, floor]], dtype=np.uint8)
    encoded = margin_levels(levels, THRESHOLD)
    assert encoded.tolist() == [[0, 0, 1]]
    assert margin_db(0) is None


def test_the_margin_tile_is_empty_exactly_where_the_colour_tile_is() -> None:
    """The two tiles describe the same cells, so neither shows more."""
    rng = np.random.default_rng(334)
    levels = rng.integers(0, 256, size=(TILE_SIZE, TILE_SIZE), dtype=np.uint8)
    colour = colour_levels(levels, THRESHOLD)
    encoded = margin_levels(levels, THRESHOLD)
    assert np.array_equal(colour[..., 3] > 0, encoded > 0)


@pytest.mark.parametrize("preset", PRESETS, ids=lambda preset: preset.name)
def test_every_modelled_preset_keeps_the_margin_on_the_colour_tile_threshold(
    preset: ModemPreset,
) -> None:
    """A half dB sensitivity meets the grid as the same byte in both tiles.

    Since #362 five presets have a sensitivity on a half dB, for example
    Medium slow at -128.5 dBm. A level is a whole dB, so `to_level`
    rounds the threshold to a byte for the colour tile. The margin tile
    must count from that same byte. A margin counted from the unrounded
    sensitivity would put a floor half a dB away from the colour ramp,
    and a cell on the edge would show in one tile and not the other.
    """
    threshold = sensitivity_of(preset)
    levels = np.arange(256, dtype=np.uint8).reshape(16, 16)
    colour = colour_levels(levels, threshold)
    encoded = margin_levels(levels, threshold)
    assert np.array_equal(colour[..., 3] > 0, encoded > 0)
    usable = encoded > 0
    expected = levels.astype(np.int16)[usable] - to_level(threshold)
    assert np.array_equal(encoded[usable].astype(np.int16) - 1, expected)


def test_the_margin_tile_is_a_grey_png_a_browser_can_read() -> None:
    """Colour type 0, eight bits, one byte for each pixel."""
    image = np.zeros((TILE_SIZE, TILE_SIZE), dtype=np.uint8)
    image[10, 20] = 11
    png = write_grey_png(image)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert png[12:16] == b"IHDR"
    width, height, depth, colour_type = (
        int.from_bytes(png[16:20], "big"),
        int.from_bytes(png[20:24], "big"),
        png[24],
        png[25],
    )
    assert (width, height, depth, colour_type) == (TILE_SIZE, TILE_SIZE, 8, 0)
    length = int.from_bytes(png[33:37], "big")
    assert png[37:41] == b"IDAT"
    rows = zlib.decompress(png[41 : 41 + length])
    stride = TILE_SIZE + 1
    assert len(rows) == stride * TILE_SIZE
    assert rows[10 * stride] == 0
    assert rows[10 * stride + 1 + 20] == 11


RAMP_TABLE = Path("tests/unit/js/coverage_ramp_margins.json")


def ramp_table() -> dict[str, object]:
    """Return the colour `colour_levels` gives every margin a byte holds.

    The threshold is the weakest level, so margins run 0 to 254. The
    browser colours a margin tile with `colourMargins`, and
    `coverage_floor_cases.mjs` checks every entry of this table against
    it. So the floor at 0 dB draws the colour tile, pixel for pixel.
    """
    threshold = -199.0
    floor = to_level(threshold)
    levels = np.array([[floor + margin for margin in range(255)]], dtype=np.uint8)
    pixels = colour_levels(levels, threshold)[0]
    spec = store.margin_spec()
    return {
        "span": RAMP_SPAN_DB,
        "alpha": spec["alpha"],
        "ramp": spec["ramp"],
        "pixels": [pixel.tolist() for pixel in pixels],
    }


def test_the_table_the_browser_is_checked_against_is_what_python_draws() -> None:
    """If this fails, the ramp moved. Write the table again from
    `ramp_table` and run the node cases: they say whether the browser
    still agrees."""
    saved = json.loads(RAMP_TABLE.read_text(encoding="utf-8"))
    assert saved == ramp_table()


# --- the colour tiles do not change -------------------------------------

# The SHA-256 of two colour tiles, taken from `render.py` before the
# floor existed. The public embed serves these bytes. If this fails, the
# public map changed: find out why, and do not update the hash to pass.
GOLDEN_COLOUR_TILES = {
    -139.0: "fcb43f685e68e0e5a041115d6aff473b1424c3d8f1e5e503b83a332d1ead611b",
    -130.0: "e4f171336d5ae4aaf4416f4bf451d9d8f721ff3aa1777ab02bcd2f3235ebd684",
}


@pytest.mark.parametrize("threshold", sorted(GOLDEN_COLOUR_TILES))
def test_the_colour_tiles_are_byte_identical_to_before_the_floor(threshold: float) -> None:
    index = np.arange(256)
    levels = ((index[:, None] + index[None, :]) % 256).astype(np.uint8)
    png = write_png(colour_levels(levels, threshold))
    assert hashlib.sha256(png).hexdigest() == GOLDEN_COLOUR_TILES[threshold]


def test_the_job_writes_a_margin_tile_beside_each_colour_tile(tmp_path: Path) -> None:
    """And the colour tile it writes is the one it always wrote."""
    from sonoran.coverage.render import sample_tile, tiles_for_grid
    from sonoran.jobs.coverage import render_layer

    settings = Settings(
        _env_file=None,
        coverage_cache_dir=str(tmp_path),
        coverage_min_zoom=8,
        coverage_max_zoom=8,
    )
    grid = region_grid(33, 33, -112, -112)
    levels = grid.empty()
    floor = to_level(THRESHOLD)
    # A strip that is usable, and a strip below the threshold.
    levels[100:300, 100:600] = floor + 12
    levels[700:900, 100:600] = floor - 5

    written = render_layer(
        tmp_path, "LongFast", "infrastructure", "usable", levels, grid, settings, THRESHOLD
    )
    assert written > 0

    colours = sorted((tmp_path / "LongFast" / "infrastructure" / "usable" / "8").rglob("*.png"))
    margins = sorted(
        (tmp_path / "LongFast" / "infrastructure" / "usable" / store.MARGIN_DIR / "8").rglob(
            "*.png"
        )
    )
    assert len(colours) == written
    assert len(margins) == written

    for tile in tiles_for_grid(grid, 8):
        patch = sample_tile(levels, grid, tile)
        colour = store.tile_path(
            tmp_path, "LongFast", "infrastructure", "usable", tile.zoom, tile.x, tile.y
        )
        margin = store.margin_tile_path(
            tmp_path, "LongFast", "infrastructure", "usable", tile.zoom, tile.x, tile.y
        )
        assert colour.exists() == margin.exists()
        if colour.exists():
            assert colour.read_bytes() == write_png(colour_levels(patch, THRESHOLD))
            assert margin.read_bytes() == write_grey_png(margin_levels(patch, THRESHOLD))


def test_no_colour_tile_path_can_name_a_margin_tile(tmp_path: Path) -> None:
    """The colour routes take a whole number for the zoom. The margin
    tiles sit under a directory whose name is not one."""
    margin = store.margin_tile_path(tmp_path, "LongFast", "infrastructure", "usable", 7, 20, 50)
    assert store.MARGIN_DIR in margin.parts
    assert not store.MARGIN_DIR.isdigit()
    for zoom in range(0, 17):
        colour = store.tile_path(tmp_path, "LongFast", "infrastructure", "usable", zoom, 20, 50)
        assert store.MARGIN_DIR not in colour.parts


# --- what a run says about itself ----------------------------------------


def test_a_new_run_says_how_its_margin_tiles_are_encoded() -> None:
    spec = store.margin_spec()
    assert spec["encoding"] == MARGIN_ENCODING
    assert spec["ramp"] == [list(colour) for colour in RAMP]
    assert spec["alpha"] == COVER_ALPHA


def test_an_old_manifest_reads_as_no_margin_data() -> None:
    """A run made before this change has no field, and the page reads
    that as "the floor is not available", never as an empty map."""
    assert store.Manifest.__dataclass_fields__["margin_tiles"].default is None


def test_the_job_writes_the_margin_spec_into_the_manifest() -> None:
    import inspect

    from sonoran.jobs import coverage

    source = inspect.getsource(coverage)
    assert "margin_tiles=store.margin_spec()" in source


# --- the routes ----------------------------------------------------------

STAMP = "20261008T000000Z"
COLOUR_PNG = b"\x89PNG\r\n\x1a\ncolour"
MARGIN_PNG = b"\x89PNG\r\n\x1a\nmargin"
ZOOM, X, Y = 7, 20, 50


def _write_run(root: Path, *, with_margin: bool) -> None:
    run = root / "runs" / STAMP
    colour = store.tile_path(run, "LongFast", "infrastructure", "usable", ZOOM, X, Y)
    colour.parent.mkdir(parents=True, exist_ok=True)
    colour.write_bytes(COLOUR_PNG)
    if with_margin:
        margin = store.margin_tile_path(run, "LongFast", "infrastructure", "usable", ZOOM, X, Y)
        margin.parent.mkdir(parents=True, exist_ok=True)
        margin.write_bytes(MARGIN_PNG)
    manifest: dict[str, object] = {
        "stamp": STAMP,
        "is_diagnostic": False,
        "bounds": [33.0, -113.0, 34.0, -112.0],
        "min_zoom": 6,
        "max_zoom": 11,
        "presets": [{"preset": "LongFast", "sensitivity_dbm": THRESHOLD}],
    }
    if with_margin:
        manifest["margin_tiles"] = store.margin_spec()
    (run / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (root / "index.json").write_text(json.dumps({"current": STAMP}), encoding="utf-8")


def _client(root: Path, **extra: object) -> TestClient:
    return TestClient(create_app(Settings(_env_file=None, coverage_cache_dir=str(root), **extra)))


MARGIN_URL = f"/api/coverage/tiles/{STAMP}/LongFast/infrastructure/usable/margin/{ZOOM}/{X}/{Y}.png"
COLOUR_URL = f"/api/coverage/tiles/{STAMP}/LongFast/infrastructure/usable/{ZOOM}/{X}/{Y}.png"


def test_the_dashboard_reads_a_margin_tile(tmp_path: Path) -> None:
    _write_run(tmp_path, with_margin=True)
    client = _client(tmp_path)
    response = client.get(MARGIN_URL)
    assert response.status_code == 200
    assert response.content == MARGIN_PNG
    assert response.headers["content-type"] == "image/png"
    assert "immutable" in response.headers["Cache-Control"]
    assert "margin" in response.headers["ETag"]
    # The colour tile is where it was.
    assert client.get(COLOUR_URL).content == COLOUR_PNG


def test_an_old_run_answers_a_margin_tile_with_404_and_keeps_its_map(tmp_path: Path) -> None:
    _write_run(tmp_path, with_margin=False)
    client = _client(tmp_path)
    assert client.get(MARGIN_URL).status_code == 404
    assert client.get(COLOUR_URL).content == COLOUR_PNG
    assert "margin_tiles" not in client.get("/api/coverage").json()


def test_the_margin_route_checks_what_the_colour_route_checks(tmp_path: Path) -> None:
    _write_run(tmp_path, with_margin=True)
    client = _client(tmp_path)
    base = f"/api/coverage/tiles/{STAMP}/LongFast"
    for path in (
        f"{base}/infrastructure/sideways/margin/{ZOOM}/{X}/{Y}.png",
        f"{base}/nonsense/usable/margin/{ZOOM}/{X}/{Y}.png",
        f"{base}/infrastructure/usable/margin/{ZOOM}/999/{Y}.png",
        f"{base}/infrastructure/usable/margin/17/{X}/{Y}.png",
    ):
        assert client.get(path).status_code == 422, path


def test_no_public_path_serves_a_margin_tile(tmp_path: Path) -> None:
    """The public embed serves the colour tile and nothing new."""
    from sonoran.api.routes import embed

    embed._publishable = None
    try:
        _write_run(tmp_path, with_margin=True)
        client = _client(tmp_path, embed_enabled=True)
        public = f"/api/embed/tiles/{STAMP}/LongFast/usable/{ZOOM}/{X}/{Y}.png"
        allowed = client.get(public)
        assert allowed.status_code == 200
        assert allowed.content == COLOUR_PNG
        for path in (
            f"/api/embed/tiles/{STAMP}/LongFast/usable/margin/{ZOOM}/{X}/{Y}.png",
            f"/api/embed/tiles/{STAMP}/LongFast/margin/{ZOOM}/{X}/{Y}.png",
            f"/api/embed/tiles/{STAMP}/LongFast/usable/{ZOOM}/{X}/{Y}.margin.png",
            f"/api/embed/tiles/{STAMP}/margin/usable/{ZOOM}/{X}/{Y}.png",
        ):
            response = client.get(path)
            assert response.status_code >= 400, path
            assert response.content != MARGIN_PNG, path
        # And the public summary carries nothing about it.
        summary = client.get("/api/embed/coverage").json()
        assert "margin_tiles" not in summary
    finally:
        embed._publishable = None


def test_the_public_page_never_asks_for_a_margin_tile() -> None:
    script = (STATIC / "embed-coverage.js").read_text(encoding="utf-8")
    assert "margin" not in script


# --- the page ------------------------------------------------------------


def _panel() -> str:
    html = INDEX_HTML.read_text(encoding="utf-8")
    start = html.index('id="coverage-options"')
    return html[start : html.index('<div class="map-shell">', start)]


def test_the_floor_is_a_select_in_the_map_group_starting_at_zero() -> None:
    panel = _panel()
    map_group = panel[: panel.index("</fieldset>")]
    assert "data-coverage-signal-floor" in map_group
    select = map_group[map_group.index("data-coverage-signal-floor") :]
    select = select[: select.index("</select>")]
    values = [part.split('"')[1] for part in select.split("value=")[1:]]
    assert values == ["0", "5", "10", "20"]
    assert 'value="0" selected' in select


def test_the_floor_rules_pass_under_node() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    done = subprocess.run([str(node), str(CASES)], capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "all cases passed" in done.stdout
