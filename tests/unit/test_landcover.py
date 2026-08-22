"""Tests for what stands on the ground.

The terrain model says where the ground is. ITM has no clutter model of
its own, so this is what lets a prediction charge the loss that
buildings and trees take.

The reduction is the part worth pinning. A class is a name, not a
number: the average of water and built-up is not a meadow.
"""

from pathlib import Path

import numpy as np
import pytest

from sonoran.config import Settings
from sonoran.landcover.classes import CLASSES, UNKNOWN, UNKNOWN_CLASS, clutter_height_m, land_cover
from sonoran.landcover.store import (
    PAGE_BYTES,
    PAGE_SIZE,
    class_at,
    clutter_at,
    have_pages,
    is_tile_name,
    tile_name,
)


def _settings(tmp_path: Path) -> Settings:
    return Settings(_env_file=None, landcover_cache_dir=str(tmp_path))


def test_a_known_class_gives_its_clutter_height() -> None:
    assert clutter_height_m(10) == CLASSES[10].clutter_height_m
    assert clutter_height_m(50) > clutter_height_m(60), "a town blocks more than bare ground"


def test_built_up_is_the_class_that_matters_here() -> None:
    """Arizona is mostly shrub and bare ground, which is why a
    prediction with no clutter has worked tolerably. What it gets wrong
    is Phoenix and Tucson."""
    assert clutter_height_m(50) >= 9.0
    assert clutter_height_m(20) <= 2.0
    assert clutter_height_m(60) == 0.0


def test_an_unknown_class_predicts_as_open_ground() -> None:
    """The honest value. A guess at clutter that is not there would
    move every prediction for no reason."""
    assert land_cover(200) is UNKNOWN
    assert clutter_height_m(UNKNOWN_CLASS) == 0.0
    assert clutter_height_m(200) == 0.0


def test_a_deployment_with_no_pages_predicts_with_no_clutter(tmp_path: Path) -> None:
    """That is a working state, and it is what the planner has always
    done. It must not be a fault."""
    settings = _settings(tmp_path)
    assert not have_pages(settings)
    assert class_at(settings, 33.45, -112.07) == UNKNOWN_CLASS
    assert clutter_at(settings, 33.45, -112.07) == 0.0


def test_a_page_is_read_at_the_right_cell(tmp_path: Path) -> None:
    """Row zero is the north edge of the degree, as it is in a terrain
    page. Reading it upside down would put a town on a mountain."""
    settings = _settings(tmp_path)
    page = np.full(PAGE_SIZE * PAGE_SIZE, 20, dtype=np.uint8).reshape(PAGE_SIZE, PAGE_SIZE)
    page[0, 0] = 50  # the north west corner
    page[PAGE_SIZE - 1, PAGE_SIZE - 1] = 10  # the south east corner
    (tmp_path / "N33W112.class.u8").write_bytes(page.tobytes())

    assert have_pages(settings)
    assert class_at(settings, 33.9999, -111.9999) == 50
    assert class_at(settings, 33.0001, -111.0001) == 10
    assert class_at(settings, 33.5, -111.5) == 20


def test_a_page_of_the_wrong_size_is_ignored(tmp_path: Path) -> None:
    """A half written file must not be read as land cover."""
    settings = _settings(tmp_path)
    (tmp_path / "N33W112.class.u8").write_bytes(b"\x32" * (PAGE_BYTES // 2))
    assert class_at(settings, 33.5, -111.5) == UNKNOWN_CLASS


@pytest.mark.parametrize("name", ["N33W112", "S01E001", "N00W180"])
def test_a_tile_name_is_accepted(name: str) -> None:
    assert is_tile_name(name)


@pytest.mark.parametrize("name", ["../etc/passwd", "N33W112.png", "", "N3W112", "n33w112"])
def test_a_name_that_is_not_a_tile_is_refused(name: str) -> None:
    """The value becomes part of a file path."""
    assert not is_tile_name(name)


def test_a_tile_is_named_from_its_south_west_corner() -> None:
    assert tile_name(33, -112) == "N33W112"
    assert tile_name(-5, 7) == "S05E007"


def test_the_most_common_class_wins_a_page_cell() -> None:
    """Not the average. A class is a name, not a number: the average of
    water and built-up is not a meadow."""
    from tools.prefetch_landcover import reduce_to_page

    block = np.full((PAGE_SIZE * 3, PAGE_SIZE * 3), 20, dtype=np.uint8)
    block[0:3, 0:3] = 50
    # Two of nine cells built-up: shrubland still wins.
    block[3:5, 3:4] = 50

    page = np.frombuffer(reduce_to_page(block), dtype=np.uint8).reshape(PAGE_SIZE, PAGE_SIZE)
    assert page[0, 0] == 50
    assert page[1, 1] == 20
    assert page[500, 500] == 20


def test_a_source_block_too_small_for_a_page_is_refused() -> None:
    from tools.prefetch_landcover import reduce_to_page

    with pytest.raises(ValueError, match="too small"):
        reduce_to_page(np.zeros((10, 10), dtype=np.uint8))


# --- what the map may claim about clutter -------------------------------


def _one_degree_settings(tmp_path: Path, west: int) -> "Settings":
    from sonoran.config import Settings

    return Settings(
        _env_file=None,
        landcover_cache_dir=str(tmp_path),
        terrain_lat_min=33,
        terrain_lat_max=33,
        terrain_lon_min=west,
        terrain_lon_max=-112,
    )


def _write_page(tmp_path: Path, name: str, code: int) -> None:
    from sonoran.landcover.store import PAGE_SIZE

    (tmp_path / f"{name}.class.u8").write_bytes(
        np.full(PAGE_SIZE * PAGE_SIZE, code, dtype=np.uint8).tobytes()
    )


def test_a_region_with_every_page_says_so(tmp_path: Path) -> None:
    """`has_landcover` used to be true when one page existed anywhere.

    A missing degree charges no clutter over the whole of it, and the
    edge is a straight step of eighteen dB in a town. Nobody would
    attribute that to a file that failed to download.
    """
    from sonoran.coverage.grid import region_grid
    from sonoran.jobs.coverage import receiver_loss

    _write_page(tmp_path, "N33W112", 50)
    loss, missing = receiver_loss(
        _one_degree_settings(tmp_path, -112), region_grid(33, 33, -112, -112)
    )
    assert missing == [], "a region whose every degree has a page is covered"
    assert loss is not None
    assert int(loss.max()) > 0


def test_a_region_missing_a_degree_names_it(tmp_path: Path) -> None:
    from sonoran.coverage.grid import region_grid
    from sonoran.jobs.coverage import receiver_loss

    _write_page(tmp_path, "N33W112", 50)
    _, missing = receiver_loss(
        _one_degree_settings(tmp_path, -113), region_grid(33, 33, -113, -112)
    )
    assert missing == ["N33W113"]


def test_a_degree_the_region_does_not_touch_is_not_missing(tmp_path: Path) -> None:
    """The loop runs one degree past each edge, so a region that does
    not start on a whole degree is covered. Those extra degrees touch
    no cell, and a page that is not wanted is not one that is absent.

    Counting them made `has_landcover` false for every deployment.
    """
    from sonoran.coverage.grid import region_grid
    from sonoran.jobs.coverage import receiver_loss

    _write_page(tmp_path, "N33W112", 50)
    _, missing = receiver_loss(
        _one_degree_settings(tmp_path, -112), region_grid(33, 33, -112, -112)
    )
    for name in ("N34W112", "N33W111", "N34W111"):
        assert name not in missing, f"{name} is off the region and was counted"
