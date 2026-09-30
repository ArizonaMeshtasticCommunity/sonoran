"""The coverage grid covers what the sites reach, not the whole region.

The run made its grid over the whole terrain region, 88 MB a layer, and
was killed at the jobs container's 640 MB twice on 2026-09-29. See
`footprint_grid` in `sonoran/jobs/coverage.py`.
"""

import math
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from sonoran.config import Settings
from sonoran.coverage.grid import NO_COVERAGE, region_grid
from sonoran.db.models import Node
from sonoran.jobs import coverage
from sonoran.radio.overrides import parse_overrides


def _settings(tmp_path: Path, **extra: object) -> Settings:
    return Settings(
        _env_file=None,
        coverage_cache_dir=str(tmp_path / "coverage"),
        landcover_cache_dir=str(tmp_path / "landcover"),
        **extra,  # type: ignore[arg-type]
    )


def _site(latitude: float, longitude: float) -> SimpleNamespace:
    return SimpleNamespace(latitude=latitude, longitude=longitude)


def test_one_site_gets_the_whole_degrees_its_footprint_touches(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    grid = coverage.footprint_grid(settings, [_site(33.5, -112.1)])  # type: ignore[list-item]
    # 60 km is about 0.54 degrees north and south, and about 0.65 east
    # and west at this latitude.
    assert grid.bounds() == (32.0, -113.0, 35.0, -111.0)


def test_every_footprint_fits_inside_the_grid(tmp_path: Path) -> None:
    """Nothing a site predicts may fall off the edge of the grid."""
    settings = _settings(tmp_path)
    sites = [_site(33.97, -112.73), _site(31.4, -110.4), _site(35.02, -111.6)]
    grid = coverage.footprint_grid(settings, sites)  # type: ignore[arg-type]
    radius = settings.coverage_radius_km
    for site in sites:
        reach_lat = radius / 111.0
        reach_lon = radius / (111.0 * math.cos(math.radians(abs(site.latitude) + reach_lat)))
        assert grid.south <= site.latitude - reach_lat
        assert grid.north >= site.latitude + reach_lat
        assert grid.west <= site.longitude - reach_lon
        assert grid.east >= site.longitude + reach_lon


def test_the_grid_is_smaller_than_the_region_for_this_mesh(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    region = region_grid(
        settings.terrain_lat_min,
        settings.terrain_lat_max,
        settings.terrain_lon_min,
        settings.terrain_lon_max,
    )
    # The corners of what the live run drew on 2026-09-29.
    sites = [_site(31.9, -112.2), _site(34.5, -110.9)]
    grid = coverage.footprint_grid(settings, sites)  # type: ignore[arg-type]
    assert grid.cells < region.cells / 2


def test_the_grid_never_leaves_the_region(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    grid = coverage.footprint_grid(settings, [_site(30.1, -115.9), _site(37.9, -108.1)])  # type: ignore[list-item]
    assert grid.bounds() == (30.0, -116.0, 38.0, -108.0)


def test_no_site_keeps_the_whole_region(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    assert coverage.footprint_grid(settings, []).bounds() == (30.0, -116.0, 38.0, -108.0)


def test_a_node_outside_the_grid_but_inside_the_region_is_a_zero() -> None:
    """Every site's reach is inside the grid, so nothing reaches there.

    It was a zero when the grid was the whole region, and absent means
    unknown to whatever reads the levels. It must stay a zero.
    """
    region = region_grid(30, 37, -116, -109)
    grid = region_grid(33, 33, -112, -112)
    layers = {"usable": grid.empty() + 50}
    points = [(1, 33.5, -111.5), (2, 36.0, -114.0), (3, 45.0, -100.0)]
    sampled = coverage._sample_nodes(points, grid, layers, region)
    assert sampled["1"] == {"usable": 50}
    assert sampled["2"] == {"usable": NO_COVERAGE}
    assert "3" not in sampled, "outside the region is still unknown"


def test_in_place_charging_changes_only_the_layer_it_is_given() -> None:
    levels = np.full((4, 4), 100, dtype=np.uint8)
    loss = np.full((4, 4), 10, dtype=np.uint8)
    other = levels.copy()
    coverage._charge_receiver(levels, loss)
    assert int(levels[0, 0]) == 90
    assert int(other[0, 0]) == 100


def _router(node_num: int, bits: int | None) -> Node:
    return Node(
        node_num=node_num,
        node_id=f"!{node_num:08x}",
        long_name=f"Router {node_num}",
        role="ROUTER_LATE",
        last_channel="MediumFast",
        last_lat=34.2098,
        last_lon=-112.3811,
        last_position_precision_bits=bits,
    )


def test_a_rounded_router_is_a_site_when_the_setting_allows_it(tmp_path: Path) -> None:
    """Towers 2 shares 13 bits, and was left out of every map."""
    rounded, exact = _router(1, 13), _router(2, None)
    overrides = parse_overrides("")

    strict = _settings(tmp_path)
    groups, left_out, coarse = coverage.group_by_preset(strict, [rounded, exact], overrides)
    assert [site.node_num for site in groups["MEDIUM_FAST"]] == [2]
    assert left_out["MEDIUM_FAST"][coverage.COARSE_POSITION] == 1
    assert [item["node_id"] for item in coarse] == ["!00000001"]

    allowing = _settings(tmp_path, coverage_min_precision_bits=13)
    groups, left_out, coarse = coverage.group_by_preset(allowing, [rounded, exact], overrides)
    by_num = {site.node_num: site for site in groups["MEDIUM_FAST"]}
    assert set(by_num) == {1, 2}
    assert coverage.COARSE_POSITION not in left_out["MEDIUM_FAST"]
    assert coarse == []
    # The footprint says it is approximate, and by how much.
    assert by_num[1].position_deviation_m == 2900.0
    assert by_num[2].position_deviation_m is None


def test_an_operator_position_is_never_marked_approximate(tmp_path: Path) -> None:
    rounded = _router(1, 13)
    overrides = parse_overrides(
        'nodes:\n  "!00000001":\n    latitude: 34.2\n    longitude: -112.4\n'
    )
    groups, _, _ = coverage.group_by_preset(_settings(tmp_path), [rounded], overrides)
    (site,) = groups["MEDIUM_FAST"]
    assert site.position_deviation_m is None
    assert (site.latitude, site.longitude) == (34.2, -112.4)
