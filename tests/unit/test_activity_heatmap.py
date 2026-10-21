"""Unit tests for the empirical activity heatmap."""

import asyncio
from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient

from sonoran.api.app import create_app
from sonoran.config import Settings
from sonoran.jobs.activity_heatmap import (
    _build_grids,
    _points,
    _render_tile,
    box_blur,
    run_once,
)


def test_box_blur_spreads_mass() -> None:
    grid = np.zeros((20, 20), dtype=np.float32)
    grid[10, 10] = 100.0

    blurred = box_blur(grid, radius=3)
    assert blurred[10, 10] < 100.0
    assert blurred[10, 10] > 0.0
    assert blurred[11, 11] > 0.0
    assert (blurred >= 0.0).all()


def test_build_grids_normalizes_within_unit_interval() -> None:
    settings = Settings(
        _env_file=None,
        terrain_lat_min=33.0,
        terrain_lat_max=34.0,
        terrain_lon_min=-112.0,
        terrain_lon_max=-111.0,
    )
    data = [
        (33.5, -111.5, 10.0),
        (33.6, -111.4, 5.0),
    ]
    grid, relative_grids, count_grid = _build_grids(settings, data)
    assert "position" in relative_grids
    pos_grid = relative_grids["position"]
    assert pos_grid.shape == (grid.height, grid.width)
    assert (pos_grid >= 0.0).all()
    assert (pos_grid <= 1.0).all()
    assert count_grid.max() > 0.0


def test_render_tile_produces_image_array() -> None:
    rel_score = np.array([[0.0, 0.5], [0.8, 1.0]], dtype=np.float32)
    count = np.array([[0.0, 1.0], [2.0, 5.0]], dtype=np.float32)
    image = _render_tile(rel_score, count)
    assert image.shape == (2, 2, 4)
    assert image.dtype == np.uint8
    # Cell with count == 0 must be transparent
    assert image[0, 0, 3] == 0
    # Cell with count > 0 must be non-zero alpha
    assert image[1, 1, 3] > 0


def test_heatmap_tile_endpoint_routing(tmp_path: Path) -> None:
    settings = Settings(_env_file=None, coverage_cache_dir=str(tmp_path))
    app = create_app(settings)
    client = TestClient(app)

    # 404 on invalid model
    res_bad = client.get("/api/map/heatmap/invalid/10/100/100.png")
    assert res_bad.status_code == 404

    # 404 on missing tile
    res_missing = client.get("/api/map/heatmap/position/10/100/100.png")
    assert res_missing.status_code == 404

    # 200 when tile exists on disk
    tile_file = tmp_path / "all" / "all" / "empirical_heatmap_position" / "10" / "100" / "100.png"
    tile_file.parent.mkdir(parents=True, exist_ok=True)
    fake_png = b"\x89PNG\r\n\x1a\nfake"
    tile_file.write_bytes(fake_png)

    res_ok = client.get("/api/map/heatmap/position/10/100/100.png")
    assert res_ok.status_code == 200
    assert res_ok.content == fake_png


# --- review fixes: identity, precision, memory, and the served path ----


def _row(precision: int | None = None, score: float = 10.0) -> tuple:
    """One scored position, as the database returns it: lat, lon, precision, score.

    The scoring rules (a packet is a node and a packet ID, each gateway
    once at its fewest hops) run in SQL now, and
    tests/integration/test_activity_heatmap_query.py tests them.
    """
    return (33.5, -111.5, precision, score)


def test_a_rounded_position_is_left_out() -> None:
    """The heatmap follows the coverage map's precise rule (#315).

    A position rounded to 13 bits sits at the centre of a cell about
    2.4 km across. A blob there shows activity where there may be no radio.
    """
    rows = [_row(precision=13), _row(precision=16), _row(precision=None)]
    assert len(_points(rows, minimum_bits=16)) == 2
    assert len(_points(rows, minimum_bits=0)) == 3


def test_the_default_region_fits_in_a_jobs_ceiling() -> None:
    """Would be caught: the 90 m terrain grid needed about 6 GB here."""
    grid, relative, count = _build_grids(Settings(_env_file=None), [(33.5, -111.5, 10.0)])
    cells = grid.width * grid.height
    assert cells <= 4_000_000, f"{cells} cells"
    assert relative["position"].shape == count.shape == (grid.height, grid.width)


class _Rows:
    def __init__(self, rows: list[tuple]) -> None:
        self.rows = rows

    async def execute(self, _query: object) -> list[tuple]:
        return self.rows


def test_the_job_writes_the_tiles_the_route_serves(tmp_path: Path) -> None:
    """Would be caught: a job and a route that disagree on the path."""
    settings = Settings(
        _env_file=None,
        coverage_cache_dir=str(tmp_path),
        terrain_lat_min=33,
        terrain_lat_max=33,
        terrain_lon_min=-112,
        terrain_lon_max=-112,
        coverage_min_zoom=8,
        coverage_max_zoom=8,
    )
    asyncio.run(run_once(_Rows([_row()]), settings))
    written = sorted(tmp_path.rglob("*.png"))
    assert written, "the job wrote no tile"
    z, x, y = written[0].parts[-3], written[0].parts[-2], written[0].stem
    client = TestClient(create_app(settings))
    response = client.get(f"/api/map/heatmap/position/{z}/{x}/{y}.png")
    assert response.status_code == 200
    assert response.content == written[0].read_bytes()
