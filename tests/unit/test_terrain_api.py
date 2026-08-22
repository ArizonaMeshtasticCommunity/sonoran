"""Tests for the terrain endpoints.

The endpoint reads files and can reach the tile source, so the tests
check the guards first: a bad name, and a tile outside the region this
service covers.
"""

import os
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from sonoran.api.app import create_app
from sonoran.config import Settings
from sonoran.terrain.srtm import PAGE_BYTES, PAGE_SIZE
from sonoran.terrain.store import (
    coordinates_in_region,
    in_region,
    is_tile_name,
    page_path,
    tile_bounds,
    write_page,
)


def _settings(cache: Path, **overrides: object) -> Settings:
    """Return settings that point at a temporary cache and never download."""
    values: dict[str, object] = {
        "_env_file": None,
        "terrain_cache_dir": str(cache),
        "terrain_allow_download": False,
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def _client(settings: Settings) -> TestClient:
    return TestClient(create_app(settings))


def _store_page(settings: Settings, tile: str, elevation: int = 700) -> None:
    """Write a flat page into the cache."""
    page = np.full(PAGE_SIZE * PAGE_SIZE, elevation, dtype="<i2")
    write_page(settings, tile, page.tobytes())


class TestTileNameGuard:
    """The name becomes part of a file path and part of a URL."""

    @pytest.mark.parametrize("name", ["N34W112", "S34E018", "N00E000"])
    def test_accepts_well_formed_names(self, name: str) -> None:
        assert is_tile_name(name)

    @pytest.mark.parametrize(
        "name",
        [
            "../etc/passwd",
            "N34W112.gz",
            "n34w112",
            "N34W12",
            "N345W112",
            "N34X112",
            "",
            "N34W112/../..",
        ],
    )
    def test_rejects_everything_else(self, name: str) -> None:
        assert not is_tile_name(name)

    def test_endpoint_rejects_a_bad_name(self, tmp_path: Path) -> None:
        response = _client(_settings(tmp_path)).get("/api/terrain/page/N34W112.gz")
        assert response.status_code == 422


class TestRegionGuard:
    """The service holds one region. It is not a proxy for the world."""

    @pytest.mark.parametrize(
        ("name", "expected"),
        [("N34W112", (34, -112)), ("S34E018", (-34, 18)), ("N51W001", (51, -1))],
    )
    def test_tile_bounds(self, name: str, expected: tuple[int, int]) -> None:
        assert tile_bounds(name) == expected

    def test_arizona_is_inside(self, tmp_path: Path) -> None:
        settings = _settings(tmp_path)
        assert in_region(settings, "N34W112")
        assert in_region(settings, "N31W110")

    def test_the_margin_reaches_past_the_state_line(self, tmp_path: Path) -> None:
        """A site near the border still needs terrain around it."""
        settings = _settings(tmp_path)
        assert in_region(settings, "N30W115")
        assert in_region(settings, "N37W109")

    def test_far_away_tiles_are_outside(self, tmp_path: Path) -> None:
        settings = _settings(tmp_path)
        assert not in_region(settings, "N51W001")
        assert not in_region(settings, "S34E018")
        assert not in_region(settings, "N45W112")

    def test_coordinates_use_the_same_region_as_the_tiles(self, tmp_path: Path) -> None:
        settings = _settings(
            tmp_path,
            terrain_lat_min=33,
            terrain_lat_max=33,
            terrain_lon_min=-113,
            terrain_lon_max=-112,
        )
        assert coordinates_in_region(settings, 33.5, -112.5)
        assert not coordinates_in_region(settings, 34.0, -112.5)

    def test_endpoint_refuses_a_tile_outside_the_region(self, tmp_path: Path) -> None:
        """Even when the page is cached, an outside tile is not served."""
        settings = _settings(tmp_path)
        _store_page(settings, "N51W001")
        response = _client(settings).get("/api/terrain/page/N51W001")
        assert response.status_code == 404

    def test_an_outside_tile_never_downloads(self, tmp_path: Path) -> None:
        """The region check runs before anything reaches the network."""
        settings = _settings(
            tmp_path, terrain_allow_download=True, terrain_source_url="http://0.0.0.0:1"
        )
        response = _client(settings).get("/api/terrain/page/N51W001")
        assert response.status_code == 404


class TestServingAPage:
    def test_returns_the_page_with_an_immutable_cache_header(self, tmp_path: Path) -> None:
        settings = _settings(tmp_path)
        _store_page(settings, "N34W112", elevation=1500)
        response = _client(settings).get("/api/terrain/page/N34W112")
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/octet-stream"
        assert len(response.content) == PAGE_BYTES
        assert "immutable" in response.headers["cache-control"]
        assert response.headers["etag"]

    def test_the_body_is_little_endian_int16(self, tmp_path: Path) -> None:
        """The browser reads the body straight into an Int16Array."""
        settings = _settings(tmp_path)
        _store_page(settings, "N34W112", elevation=1500)
        response = _client(settings).get("/api/terrain/page/N34W112")
        values = np.frombuffer(response.content, dtype="<i2")
        assert values.shape == (PAGE_SIZE * PAGE_SIZE,)
        assert int(values[0]) == 1500

    def test_a_missing_page_is_a_404(self, tmp_path: Path) -> None:
        """The planner reads this as sea level, as the engine does."""
        response = _client(_settings(tmp_path)).get("/api/terrain/page/N34W112")
        assert response.status_code == 404

    def test_a_damaged_page_is_not_served(self, tmp_path: Path) -> None:
        """A part written file must never reach the engine as terrain."""
        settings = _settings(tmp_path)
        path = page_path(settings, "N34W112")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\x00" * 128)
        response = _client(settings).get("/api/terrain/page/N34W112")
        assert response.status_code == 404


class TestRegionEndpoint:
    def test_reports_the_configured_bounds(self, tmp_path: Path) -> None:
        response = _client(_settings(tmp_path)).get("/api/terrain/region")
        assert response.status_code == 200
        body = response.json()
        assert body["lat_min"] == 30
        # The maximum is the far edge of the last tile, not its corner.
        assert body["lat_max"] == 38
        assert body["lon_min"] == -116
        assert body["lon_max"] == -108
        assert body["page_bytes"] == PAGE_BYTES


class TestWritePage:
    def test_the_write_is_atomic(self, tmp_path: Path) -> None:
        """A reader must never see a part written page."""
        settings = _settings(tmp_path)
        _store_page(settings, "N34W112")
        assert page_path(settings, "N34W112").stat().st_size == PAGE_BYTES
        assert not list(tmp_path.glob("*.tmp"))


def test_terrain_routes_are_read_only(tmp_path: Path) -> None:
    """The API rule holds for the new routes too."""
    client = _client(_settings(tmp_path))
    for method in ("post", "put", "patch", "delete"):
        response = getattr(client, method)("/api/terrain/page/N34W112")
        assert response.status_code == 405


class TestAnUnwritableCache:
    """A cache that cannot be written must not fail the request.

    The page is already made by that point. The usual cause is a volume
    that belongs to root while the process runs as somebody else, which
    is a problem to fix rather than a reason to serve nothing.
    """

    @pytest.mark.skipif(
        os.geteuid() == 0,
        reason="root writes a read-only directory, so the case cannot be made",
    )
    def test_write_page_reports_failure_instead_of_raising(self, tmp_path: Path) -> None:
        settings = _settings(tmp_path / "read-only" / "terrain")
        (tmp_path / "read-only").mkdir()
        (tmp_path / "read-only").chmod(0o500)
        try:
            written = write_page(settings, "N34W112", b"\x00" * PAGE_BYTES)
            assert written is False
        finally:
            (tmp_path / "read-only").chmod(0o700)

    def test_a_good_write_reports_success(self, tmp_path: Path) -> None:
        settings = _settings(tmp_path)
        assert write_page(settings, "N34W112", b"\x00" * PAGE_BYTES) is True
