"""The radio climate of a place, from the shipped Köppen-Geiger crop (#239).

Every point lookup here reads the shipped data file, not a mock. The
issue asks for exactly that: Phoenix must come back desert and Flagstaff
continental temperate **from the data that ships**, so a crop cut one
row out, or a grid read upside down, fails here.

The coordinates were read off the source GeoTIFF by
`tools/make_climate_crop.py` on 2026-10-09:

    Phoenix (Sky Harbor)       33.4342 -112.0116  BWh
    Flagstaff (Pulliam)        35.1385 -111.6712  Dsb
    Flagstaff (downtown)       35.1983 -111.6513  Dsb
    Tucson (downtown)          32.2217 -110.9265  BWh
    Tucson (airport)           32.1161 -110.9410  BSh
    Prescott (downtown)        34.5400 -112.4685  Csa
    Prescott (airport)         34.6545 -112.4196  BSk
    Yuma                       32.6927 -114.6277  BWh
    Wickenburg                 33.9686 -112.7296  BWh
    Show Low                   34.2542 -110.0298  Csa
"""

import gzip
import hashlib
import re
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from sonoran.api.app import create_app
from sonoran.api.routes import climate as climate_routes
from sonoran.climate import (
    CROP,
    FALLBACK_CLIMATE,
    KOPPEN,
    PAGE_BYTES,
    climate_at,
    koppen_at,
    page,
    store,
)
from sonoran.climate.koppen import BY_CODE
from sonoran.config import Settings
from sonoran.coverage.params import CLIMATE_CODES

PROVENANCE = Path(store.__file__).with_name("PROVENANCE.md")

# The source's own legend.txt, value by value. The table must name the
# same symbol for the same number, or every lookup is a different class.
LEGEND = (
    "Af Am Aw BWh BWk BSh BSk Csa Csb Csc Cwa Cwb Cwc Cfa Cfb Cfc "
    "Dsa Dsb Dsc Dsd Dwa Dwb Dwc Dwd Dfa Dfb Dfc Dfd ET EF"
).split()


class TestTheTable:
    """The Köppen to ITM table. Reviewable, and complete."""

    def test_every_class_of_the_legend_is_mapped_exactly_once(self) -> None:
        codes = [item.code for item in KOPPEN]
        assert sorted(codes) == list(range(1, 31))
        assert len(codes) == len(set(codes)), "a class is mapped twice"

    def test_each_number_is_the_legend_symbol(self) -> None:
        for item in KOPPEN:
            assert item.symbol == LEGEND[item.code - 1], item

    def test_each_climate_is_one_the_engine_takes(self) -> None:
        for item in KOPPEN:
            assert item.climate in CLIMATE_CODES, item

    def test_each_class_has_a_reason(self) -> None:
        for item in KOPPEN:
            assert len(item.reason) > 20, item

    def test_no_class_is_given_a_maritime_climate(self) -> None:
        """Köppen cannot tell a coast from a mountain. See `koppen.py`."""
        assert not [item for item in KOPPEN if item.climate.startswith("maritime")]

    @pytest.mark.parametrize(
        ("symbol", "climate"),
        [
            # The groups, by the rule in the module docstring.
            ("Af", "equatorial"),
            ("Aw", "continental_subtropical"),
            ("BWh", "desert"),
            ("BWk", "desert"),
            # The judgement calls the issue names. Change one of these and
            # change the reason and docs/PLANNER.md 4.3 with it.
            ("BSh", "desert"),
            ("BSk", "desert"),
            ("Csa", "continental_temperate"),
            ("Csb", "continental_temperate"),
            ("Dsb", "continental_temperate"),
            ("Dfb", "continental_temperate"),
            ("ET", "continental_temperate"),
        ],
    )
    def test_the_judgement_calls(self, symbol: str, climate: str) -> None:
        found = next(item for item in KOPPEN if item.symbol == symbol)
        assert found.climate == climate

    def test_the_planner_doc_holds_the_same_table(self) -> None:
        """docs/PLANNER.md 4.3 is the reader's copy. It must not drift."""
        doc = (Path(__file__).resolve().parents[2] / "docs" / "PLANNER.md").read_text("utf-8")
        labels = {
            "equatorial": "Equatorial",
            "continental_subtropical": "Continental subtropical",
            "desert": "Desert",
            "continental_temperate": "Continental temperate",
        }
        for item in KOPPEN:
            row = re.search(rf"^\| {item.code} \| {item.symbol} \|[^|]*\| ([^|]+) \|", doc, re.M)
            assert row, f"docs/PLANNER.md has no row for {item.symbol}"
            assert row.group(1).strip() == labels[item.climate], item.symbol


class TestTheShippedData:
    """The file that ships, read as the running code reads it."""

    def test_the_file_is_the_crop_the_provenance_names(self) -> None:
        raw = gzip.decompress(store.DATA_FILE.read_bytes())
        assert len(raw) == CROP.rows * CROP.columns == 960 * 960
        digest = hashlib.sha256(raw).hexdigest()
        assert digest in PROVENANCE.read_text("utf-8"), "the data changed without its provenance"

    def test_the_licence_and_the_attribution_sit_beside_the_data(self) -> None:
        text = PROVENANCE.read_text("utf-8")
        assert "CC BY 4.0" in text
        assert "https://creativecommons.org/licenses/by/4.0/" in text
        assert "10.1038/s41597-023-02549-6" in text
        assert "Changes made" in text

    def test_the_crop_is_the_default_terrain_region(self) -> None:
        settings = Settings(_env_file=None)  # type: ignore[call-arg]
        assert CROP.south == settings.terrain_lat_min
        assert CROP.north == settings.terrain_lat_max + 1
        assert CROP.west == settings.terrain_lon_min
        assert CROP.east == settings.terrain_lon_max + 1

    def test_every_value_in_the_file_is_a_class_or_none(self) -> None:
        grid = np.frombuffer(gzip.decompress(store.DATA_FILE.read_bytes()), dtype=np.uint8)
        assert set(np.unique(grid).tolist()) <= {0, *BY_CODE}

    def test_the_cell_counts_in_the_planner_doc_are_the_data(self) -> None:
        """The doc says how much ground each class covers. It must be true."""
        grid = np.frombuffer(gzip.decompress(store.DATA_FILE.read_bytes()), dtype=np.uint8)
        counts = np.bincount(grid, minlength=31)
        doc = (Path(__file__).resolve().parents[2] / "docs" / "PLANNER.md").read_text("utf-8")
        for item in KOPPEN:
            row = re.search(
                rf"^\| {item.code} \| {item.symbol} \|[^|]*\|[^|]*\| ([0-9 ]+) \|", doc, re.M
            )
            assert row, item.symbol
            assert int(row.group(1).replace(" ", "")) == counts[item.code], item.symbol


class TestPointLookups:
    """Phoenix and Flagstaff are 200 km apart and in different climates."""

    @pytest.mark.parametrize(
        ("place", "latitude", "longitude", "symbol", "climate"),
        [
            ("Phoenix", 33.4342, -112.0116, "BWh", "desert"),
            ("Flagstaff airport", 35.1385, -111.6712, "Dsb", "continental_temperate"),
            ("Flagstaff downtown", 35.1983, -111.6513, "Dsb", "continental_temperate"),
            ("Tucson downtown", 32.2217, -110.9265, "BWh", "desert"),
            ("Tucson airport", 32.1161, -110.9410, "BSh", "desert"),
            ("Prescott downtown", 34.5400, -112.4685, "Csa", "continental_temperate"),
            ("Prescott airport", 34.6545, -112.4196, "BSk", "desert"),
            ("Yuma", 32.6927, -114.6277, "BWh", "desert"),
            ("Wickenburg", 33.9686, -112.7296, "BWh", "desert"),
            ("Show Low", 34.2542, -110.0298, "Csa", "continental_temperate"),
        ],
    )
    def test_a_place(
        self, place: str, latitude: float, longitude: float, symbol: str, climate: str
    ) -> None:
        answer = climate_at(latitude, longitude)
        assert answer.koppen is not None, place
        assert answer.koppen.symbol == symbol, place
        assert answer.climate == climate, place
        assert answer.known
        assert symbol in answer.describe()

    def test_the_two_ends_of_the_issue_differ(self) -> None:
        assert climate_at(33.4342, -112.0116).climate == "desert"
        assert climate_at(35.1983, -111.6513).climate == "continental_temperate"


class TestOutsideTheData:
    """A place with no class falls back, and says it did."""

    @pytest.mark.parametrize(
        ("latitude", "longitude"),
        [
            (40.0, -112.0),  # north of the crop
            (29.99, -112.0),  # south of it
            (33.4, -116.5),  # west of it, California
            (33.4, -108.0),  # the east edge is outside
            (38.0, -112.0),  # the north edge is outside
            (31.0, -114.0),  # inside, but the Gulf of California has no class
            (float("nan"), -112.0),
        ],
    )
    def test_falls_back_to_desert_and_says_so(self, latitude: float, longitude: float) -> None:
        answer = climate_at(latitude, longitude)
        assert answer.climate == FALLBACK_CLIMATE == "desert"
        assert answer.koppen is None
        assert not answer.known
        assert answer.describe() == "not known here, using desert"

    def test_an_unreadable_file_falls_back_rather_than_raising(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        broken = tmp_path / "broken.u8.gz"
        broken.write_bytes(gzip.compress(b"\x04" * 100))
        monkeypatch.setattr(store, "DATA_FILE", broken)
        store._grid.cache_clear()
        try:
            assert koppen_at(33.4342, -112.0116) is None
            assert climate_at(33.4342, -112.0116).describe() == "not known here, using desert"
            assert page(33, -113) is None
        finally:
            monkeypatch.undo()
            store._grid.cache_clear()


class TestPages:
    """One degree square, north row first, as the planner reads it."""

    def test_a_page_reads_back_the_same_class_as_a_point(self) -> None:
        body = page(35, -112)
        assert body is not None and len(body) == PAGE_BYTES
        # Flagstaff downtown, read the way planner-params.js reads it.
        latitude, longitude = 35.1983, -111.6513
        row = int((36 - latitude) * 120)
        column = int((longitude - -112) * 120)
        assert body[row * 120 + column] == koppen_at(latitude, longitude) == 18

    def test_a_negative_longitude_is_named_for_its_west_edge(self) -> None:
        """AGENTS.md 9.13.1: 112.07 W is in the square whose west edge is 113 W."""
        body = page(33, -113)
        assert body is not None
        row = int((34 - 33.4342) * 120)
        column = int((-112.0116 - -113) * 120)
        assert body[row * 120 + column] == 4

    @pytest.mark.parametrize(("latitude", "longitude"), [(38, -112), (29, -112), (33, -117)])
    def test_no_page_outside_the_crop(self, latitude: int, longitude: int) -> None:
        assert page(latitude, longitude) is None


def _client(**overrides: object) -> TestClient:
    values: dict[str, object] = {"_env_file": None, "terrain_allow_download": False}
    values.update(overrides)
    return TestClient(create_app(Settings(**values)))  # type: ignore[arg-type]


class TestTheEndpoints:
    """GET only, one region only, and nothing about the site is sent."""

    def test_a_page_in_the_region(self) -> None:
        response = _client().get("/api/climate/page/N35W112")
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/octet-stream"
        assert "immutable" in response.headers["cache-control"]
        assert response.content == page(35, -112)

    def test_a_bad_name_is_refused(self) -> None:
        assert _client().get("/api/climate/page/N35W112.gz").status_code == 422

    def test_a_tile_outside_the_region_is_refused(self) -> None:
        assert _client().get("/api/climate/page/N40W112").status_code == 404
        assert _client().get("/api/climate/page/S34E018").status_code == 404

    def test_the_configured_region_bounds_the_endpoint_not_the_crop(self) -> None:
        """A deployment with a smaller region serves less, though the crop holds it."""
        narrow = _client(terrain_lat_min=33, terrain_lat_max=34)
        assert narrow.get("/api/climate/page/N33W112").status_code == 200
        assert narrow.get("/api/climate/page/N35W112").status_code == 404

    def test_a_wider_region_still_has_no_class_past_the_crop(self) -> None:
        wide = _client(terrain_lat_max=40)
        assert wide.get("/api/climate/page/N39W112").status_code == 404

    def test_the_table_is_served_whole(self) -> None:
        body = _client().get("/api/climate/classes").json()
        assert body["fallback"] == "desert"
        assert body["cells_per_degree"] == 120
        assert [item["code"] for item in body["classes"]] == list(range(1, 31))
        assert "Beck" in body["source"]
        dsb = next(item for item in body["classes"] if item["symbol"] == "Dsb")
        assert dsb["climate"] == "continental_temperate"

    def test_there_is_no_point_lookup(self) -> None:
        """The planner never sends a site to the server (PLANNER.md 2).

        The routes are read off the router itself. `test_api_smoke.py`
        walks the whole app for the GET-only rule.
        """
        found = {
            (route.path, frozenset(route.methods))  # type: ignore[attr-defined]
            for route in climate_routes.router.routes
        }
        assert found == {
            ("/api/climate/classes", frozenset({"GET"})),
            ("/api/climate/page/{tile}", frozenset({"GET"})),
        }


class TestTheCoverageJob:
    """The published map and the calibration use the site's climate too."""

    @pytest.mark.parametrize(
        ("latitude", "longitude", "climate"),
        [
            (33.4342, -112.0116, "desert"),
            (35.1983, -111.6513, "continental_temperate"),
            # Outside the data: what every site got before #239.
            (40.0, -112.0, "desert"),
        ],
    )
    def test_a_site_predicts_with_its_own_climate(
        self, latitude: float, longitude: float, climate: str
    ) -> None:
        from sonoran.coverage.sites import engine_params, make_site
        from sonoran.radio.presets import preset_by_key
        from sonoran.radio.resolve import resolve_profile

        settings = Settings(_env_file=None)  # type: ignore[call-arg]
        preset = preset_by_key("LONG_FAST")
        assert preset is not None
        profile = resolve_profile("!a", "RAK4631")
        site = make_site(settings, "!a", 1, "a", latitude, longitude, profile, preset)
        params = engine_params(settings, site)
        assert params.radio_climate == climate
        # AGENTS.md 9.16.1: the climate is an i32 to the engine.
        argument = params.to_arguments()[9]
        assert argument == CLIMATE_CODES[climate]
        assert isinstance(argument, int)

    @pytest.mark.parametrize(
        ("latitude", "longitude", "climate"),
        [(33.4342, -112.0116, "desert"), (35.1983, -111.6513, "continental_temperate")],
    )
    def test_the_calibration_predicts_with_the_same_climate(
        self, latitude: float, longitude: float, climate: str
    ) -> None:
        from sonoran.jobs.calibrate import Peer, _params
        from sonoran.radio.presets import preset_by_key
        from sonoran.radio.resolve import resolve_profile

        preset = preset_by_key("LONG_FAST")
        assert preset is not None
        peer = Peer("!a", 1, latitude, longitude, resolve_profile("!a", "RAK4631"), preset)
        params = _params(Settings(_env_file=None), peer)  # type: ignore[call-arg]
        assert params.radio_climate == climate
