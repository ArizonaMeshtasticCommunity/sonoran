"""Unit tests for the empirical activity heatmap."""

from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient

from sonoran.api.app import create_app
from sonoran.config import Settings
from sonoran.jobs.activity_heatmap import _build_grids, _render_tile, box_blur


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
        (33.5, -111.5, 32, 10.0),
        (33.6, -111.4, 32, 5.0),
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
