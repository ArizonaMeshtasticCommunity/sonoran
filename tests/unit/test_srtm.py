"""Tests for the SRTM to SPLAT! page pipeline.

The `srtm2sdf` step must be bit-exact. The engine reads terrain profiles
straight out of these cells, so one wrong cell is one wrong hill.

The area-weighted reduction is a different matter. It cannot be made
bit-exact against GDAL, and the site planner does not ask for that
either. See `test_downsample_matches_gdal_within_one_metre`.
"""

import gzip
import hashlib
import os
from pathlib import Path

import numpy as np
import pytest

from sonoran.terrain.srtm import (
    DOWNSAMPLED_SIZE,
    HGT_SIZE,
    PAGE_BYTES,
    PAGE_SIZE,
    SRTM_NODATA,
    downsample_average,
    page_from_hgt,
    page_signed_floor_lon,
    parse_hgt,
    srtm2sdf_transform,
    tile_name,
    tile_urls,
)

FIXTURES = Path(__file__).parent.parent / "fixtures" / "terrain"

# The page this project makes from the London golden grid. The site
# planner makes the same page, and so did the SPLAT! backend before it.
# If this changes, the port has drifted. Do not update it to make a test
# pass. Find out what changed.
LONDON_PAGE_SHA256 = "a732131ee1531805f222184b84e7f466a98651bb57dbc88238b87fb50bb15b29"


def _london_grid() -> np.ndarray:
    """Return the golden 1201 x 1201 grid for N51W001."""
    raw = gzip.decompress((FIXTURES / "N51W001_1201_avg_i2le.bin.gz").read_bytes())
    return np.frombuffer(raw, dtype="<i2").reshape(DOWNSAMPLED_SIZE, DOWNSAMPLED_SIZE)


class TestTileNaming:
    """The engine reports pages. Each page needs the right tile."""

    def test_west_hemisphere(self) -> None:
        assert tile_name(50, 114) == "N50W115"
        assert tile_name(51, 113) == "N51W114"

    def test_south_and_east(self) -> None:
        assert tile_name(-34, 341) == "S34E018"
        assert tile_name(-35, 341) == "S35E018"

    def test_greenwich_meridian(self) -> None:
        """The two tiles either side of zero longitude differ."""
        assert tile_name(51, 0) == "N51W001"
        assert tile_name(51, 359) == "N51E000"

    def test_antimeridian(self) -> None:
        assert tile_name(-17, 179) == "S17W180"
        assert tile_name(-17, 180) == "S17E179"

    def test_arizona(self) -> None:
        """The region this deployment serves."""
        assert tile_name(34, 111) == "N34W112"
        assert tile_name(31, 109) == "N31W110"

    @pytest.mark.parametrize(
        ("min_west", "expected"),
        [(114, -115), (0, -1), (359, 0), (341, 18), (179, -180), (180, 179)],
    )
    def test_signed_floor_longitude(self, min_west: int, expected: int) -> None:
        assert page_signed_floor_lon(min_west) == expected

    def test_urls_prefer_v2(self) -> None:
        assert tile_urls("https://tiles.example", "N51W115") == [
            "https://tiles.example/v2/skadi/N51/N51W115.hgt.gz",
            "https://tiles.example/skadi/N51/N51W115.hgt.gz",
        ]

    def test_urls_tolerate_a_trailing_slash(self) -> None:
        assert tile_urls("https://tiles.example/", "N51W115")[0].startswith(
            "https://tiles.example/v2/"
        )


class TestParseHgt:
    """A tile is big-endian int16 with the north edge first."""

    def test_reads_big_endian(self) -> None:
        cells = HGT_SIZE * HGT_SIZE
        values = np.arange(cells, dtype=np.int32).astype(">i2")
        tile = parse_hgt(values.tobytes())
        assert tile.shape == (HGT_SIZE, HGT_SIZE)
        assert tile[0, 0] == 0
        assert tile[0, 1] == 1
        assert tile[1, 0] == HGT_SIZE % 32768

    def test_rejects_a_short_file(self) -> None:
        """A three arc-second tile would silently make nonsense terrain."""
        with pytest.raises(ValueError, match="hgt too small"):
            parse_hgt(b"\x00" * 100)


class TestSrtm2Sdf:
    """This step must be bit-exact. See the module docstring."""

    def test_matches_the_backend_page_for_london(self) -> None:
        """The whole tile, cell for cell.

        The London tile is used because it holds sub-zero cells, so the
        neighbour-average repair runs. A dry tile would never reach it.
        """
        page = srtm2sdf_transform(_london_grid())
        data = page.astype("<i2").tobytes()
        assert len(data) == PAGE_BYTES
        assert hashlib.sha256(data).hexdigest() == LONDON_PAGE_SHA256

    def test_the_london_grid_exercises_the_repair(self) -> None:
        """Guard the test above. A dry fixture would prove nothing."""
        grid = _london_grid()
        walked = grid[1:DOWNSAMPLED_SIZE, 0:PAGE_SIZE]
        assert int((walked < 0).sum()) == 34

    def test_rejects_a_grid_of_the_wrong_size(self) -> None:
        with pytest.raises(ValueError, match="expected"):
            srtm2sdf_transform(np.zeros((10, 10), dtype=np.int16))

    def test_walks_south_to_north_and_east_to_west(self) -> None:
        """The northernmost row and the easternmost column are dropped.

        With no sub-zero cell there is no repair, so the result is the
        remaining window reversed on both axes.
        """
        size = 4
        grid = np.arange((size + 1) * (size + 1), dtype=np.int16).reshape(size + 1, size + 1)
        page = srtm2sdf_transform(grid, page_size=size)
        window = grid[1 : size + 1, 0:size]
        assert np.array_equal(page, window[::-1, ::-1])
        # The first cell written is the south-west corner of the window.
        assert page[0, 0] == grid[size, size - 1]

    def test_repair_averages_the_higher_neighbours(self) -> None:
        """A sub-zero cell takes the average of neighbours above it."""
        size = 4
        grid = np.full((size + 1, size + 1), 10, dtype=np.int16)
        grid[2, 2] = -5
        page = srtm2sdf_transform(grid, page_size=size)
        # Every neighbour is 10, so the repaired cell is 10.
        assert page[size - 2, size - 1 - 2] == 10

    def test_repair_floors_at_zero(self) -> None:
        """With no neighbour above the bad value, nothing survives below zero.

        The C code keeps the last neighbour it read and then applies the
        floor. Every neighbour here is also sub-zero, so the result is
        the floor itself.
        """
        size = 4
        grid = np.full((size + 1, size + 1), -20, dtype=np.int16)
        page = srtm2sdf_transform(grid, page_size=size)
        assert int(page.min()) == 0
        assert int(page.max()) == 0

    def test_repair_reads_cells_it_already_wrote(self) -> None:
        """The walk changes the grid as it goes.

        A cell repaired early can be the neighbour that repairs a later
        one. This is why the walk cannot run in parallel.
        """
        size = 4
        grid = np.full((size + 1, size + 1), -1, dtype=np.int16)
        grid[1, 0] = 100
        page = srtm2sdf_transform(grid, page_size=size)
        # The repair spreads from the one positive cell, so at least one
        # sub-zero cell ends up above the floor.
        assert int(page.max()) > 0


class TestDownsample:
    """The area-weighted reduction, 3601 to 1201."""

    def test_shape_and_type(self) -> None:
        src = np.zeros((HGT_SIZE, HGT_SIZE), dtype=np.int16)
        out = downsample_average(src)
        assert out.shape == (DOWNSAMPLED_SIZE, DOWNSAMPLED_SIZE)
        assert out.dtype == np.int16

    def test_a_flat_tile_stays_flat(self) -> None:
        src = np.full((HGT_SIZE, HGT_SIZE), 1234, dtype=np.int16)
        assert np.array_equal(downsample_average(src), np.full((1201, 1201), 1234))

    def test_nodata_takes_no_part_in_the_average(self) -> None:
        """A no-data cell must not drag a real elevation towards -32768.

        The gap is one cell wide. A whole window of no-data is the
        separate case below.
        """
        src = np.full((HGT_SIZE, HGT_SIZE), 500, dtype=np.int16)
        src[0, 0] = SRTM_NODATA
        out = downsample_average(src)
        assert out[0, 0] == 500

    def test_a_cell_with_no_measurement_stays_nodata(self) -> None:
        src = np.full((HGT_SIZE, HGT_SIZE), SRTM_NODATA, dtype=np.int16)
        assert downsample_average(src)[600, 600] == SRTM_NODATA

    def test_rounds_half_away_from_zero(self) -> None:
        """GDAL rounds .5 away from zero, not to the nearest even value.

        Rounding to even would give 2 and -2 here, so the two halves of
        this test disagree only under the wrong rule.
        """
        src = np.zeros((4, 4), dtype=np.int16)
        # A ratio of exactly two, so each output cell is a plain 2 x 2 mean.
        src[0:2, 0:2] = [[1, 1], [2, 2]]  # mean 1.5
        src[2:4, 2:4] = [[-1, -1], [-2, -2]]  # mean -1.5
        out = downsample_average(src, src_size=4, dst_size=2)
        assert out[0, 0] == 2
        assert out[1, 1] == -2


@pytest.mark.skipif(
    os.environ.get("SONORAN_TERRAIN_NETWORK_TESTS") != "1",
    reason="set SONORAN_TERRAIN_NETWORK_TESTS=1 to download a real tile",
)
def test_downsample_matches_gdal_within_one_metre(tmp_path: Path) -> None:
    """Compare a real tile against the grid the SPLAT! backend produced.

    This cannot be exact. GDAL and this code disagree on cells whose true
    average sits within about 1e-4 of a half metre, and each picks a
    different side. The site planner has the same disagreement and asks
    for 99.9 percent exact with a largest error of one metre. This port
    is held to the same bar.
    """
    import urllib.request

    golden_path = FIXTURES / "N51W115_1201_avg_i2le.bin.gz"
    if not golden_path.exists():
        pytest.skip("the N51W115 golden grid is not vendored")

    url = "https://elevation-tiles-prod.s3.amazonaws.com/v2/skadi/N51/N51W115.hgt.gz"
    with urllib.request.urlopen(url, timeout=120) as response:
        raw = gzip.decompress(response.read())

    got = downsample_average(parse_hgt(raw)).astype(np.int32)
    want = np.frombuffer(gzip.decompress(golden_path.read_bytes()), dtype="<i2")
    want = want.reshape(DOWNSAMPLED_SIZE, DOWNSAMPLED_SIZE).astype(np.int32)

    difference = np.abs(got - want)
    exact = float((difference == 0).mean())
    assert exact >= 0.999, f"only {exact:.5%} of cells are exact"
    assert int(difference.max()) <= 1


class TestPageFromHgt:
    """The whole pipeline, end to end."""

    def test_returns_a_page_of_the_documented_size(self) -> None:
        src = np.full((HGT_SIZE, HGT_SIZE), 300, dtype=np.int16)
        page = page_from_hgt(src.astype(">i2").tobytes())
        assert len(page) == PAGE_BYTES
        values = np.frombuffer(page, dtype="<i2")
        assert values.min() == 300
        assert values.max() == 300

    def test_output_is_little_endian(self) -> None:
        """The browser reads the page straight into an Int16Array."""
        src = np.full((HGT_SIZE, HGT_SIZE), 1, dtype=np.int16)
        page = page_from_hgt(src.astype(">i2").tobytes())
        assert page[:2] == b"\x01\x00"
