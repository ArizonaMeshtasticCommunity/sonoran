"""The siting half, end to end, against a real database and the engine.

The unit tests pin the parts. This runs the whole thing the way the
jobs container does: real schema, real rows, the per node job, a
coverage run, the terrain cache, the engine, and the API that serves
what was written.

Every test that needs terrain writes a page into the cache itself. A
deployment with no terrain is a working state and gets its own test,
because it is the state a new box starts in and the answer it must give
is `unknown` and never "no benefit".
"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient
from sqlalchemy import text

from sonoran.api.app import create_app
from sonoran.config import Settings
from sonoran.coverage import store as coverage_store
from sonoran.gaps import store
from sonoran.jobs import coverage, gaps, gaps_siting
from sonoran.terrain.srtm import PAGE_SIZE, page_cell, tile_name_of
from tests.integration.conftest import role_url
from tests.integration.test_gaps import (
    BASE,
    _add_node,
    _busy,
    _run,
)
from tests.integration.test_gaps import clean as _clean

# The same "leave the tables as they were found" fixture, bound into
# this module so that pytest finds it by name. These tests write into
# the same node-number range and would otherwise read each other's rows.
clean = _clean


def _jobs_url(timescale_url: str) -> str:
    return role_url(timescale_url, "azmsh_jobs")


def _settings(timescale_url: str, tmp_path: Path, **extra: object) -> Settings:
    extra.setdefault("gaps_min_packets", 5)
    extra.setdefault("gaps_min_active_hours", 3)
    # Small, so each test is about the pipeline and not about the engine.
    extra.setdefault("gaps_candidate_radius_km", 8.0)
    # Zero means "in this process", which keeps a test off the spawn
    # path. One test asks for a worker on purpose.
    extra.setdefault("gaps_workers", 0)
    return Settings(
        _env_file=None,
        database_url_jobs=_jobs_url(timescale_url),
        database_url_api=_jobs_url(timescale_url).replace("azmsh_jobs", "azmsh_api"),
        coverage_cache_dir=str(tmp_path / "coverage"),
        landcover_cache_dir=str(tmp_path / "landcover"),
        terrain_cache_dir=str(tmp_path / "terrain"),
        terrain_allow_download=False,
        coverage_radius_km=8.0,
        coverage_min_zoom=7,
        coverage_max_zoom=8,
        coverage_workers=1,
        **extra,
    )


# The tiles these tests put in the cache.
#
# A cluster around 33.45 N, 112.07 W sits in N33W113, and the search
# window grown by `GAPS_SEARCH_RADIUS_KM` reaches into N33W112 as well.
# Writing only one of them would leave half of every window unknown,
# which is a real state the feature handles and not the state these
# tests mean to be in.
TERRAIN_TILES = ("N33W113", "N33W112")


def _write_terrain(settings: Settings, hill: tuple[float, float] | None = None) -> None:
    """Put flat terrain into the cache, so the engine has ground.

    Flat at 400 m, with an optional cone. Each page is written in the
    exact form `page_from_hgt` produces, because `read_cached_page`
    checks the length and the siting half reads the cells back through
    `terrain/srtm.py::page_cell`.

    The hill goes into the tile that really holds it, which is found
    with `tile_name_of`. Putting it in the wrong tile is the mistake
    this helper exists to make impossible: a longitude of -112.12 sits
    in **N33W113**, because a tile is named for its south-west corner.
    """
    root = Path(settings.terrain_cache_dir)
    root.mkdir(parents=True, exist_ok=True)
    on_tile = tile_name_of(*hill) if hill is not None else None
    for name in TERRAIN_TILES:
        page = np.full((PAGE_SIZE, PAGE_SIZE), 400, dtype="<i2")
        if hill is not None and name == on_tile:
            row, column = page_cell(*hill)
            radius = 40
            for down in range(-radius, radius + 1):
                for across in range(-radius, radius + 1):
                    away = (down * down + across * across) ** 0.5
                    if away <= radius:
                        page[row + down, column + across] = int(400 + 400 * (1 - away / radius))
        (root / f"{name}.page.i16").write_bytes(page.tobytes())


def _struggling(connection, node_num: int, latitude: float, longitude: float) -> None:  # type: ignore[no-untyped-def]
    """Add a node that is an MQTT gateway nothing has ever heard on air.

    That is `radio_isolated: bad`, which is the strongest thing the per
    node half can find and the clearest reason to want a node nearby.
    """
    _add_node(connection, node_num, latitude, longitude, role="CLIENT")
    connection.execute(
        text("UPDATE node SET is_mqtt_gateway = true WHERE node_num = :num"),
        {"num": node_num},
    )
    _busy(connection, node_num, node_num * 10, lambda hour: [(node_num, None, 6.0)], hours=8)


def _siting(settings: Settings, preset: str = "LongFast") -> dict:
    document = store.read_siting(settings, preset)
    assert document is not None, "the siting job wrote nothing"
    return document


def _run_siting(settings: Settings) -> list[str]:
    import asyncio

    return asyncio.run(gaps_siting.run_once(settings))


# ------------------------------------------------------ the whole thing


def test_the_whole_siting_pipeline_from_rows_to_the_api(
    timescale_url: str, migrated_engine, tmp_path: Path, clean: None
):  # type: ignore[no-untyped-def]
    """Rows in, a place on the ground out, and the API serves it."""
    settings = _settings(timescale_url, tmp_path)
    _write_terrain(settings, hill=(33.52, -112.12))
    with migrated_engine.begin() as connection:
        # Four struggling nodes within a few kilometres, and a router
        # that gives the coverage run something to predict from.
        for index, (latitude, longitude) in enumerate(
            [(33.45, -112.07), (33.46, -112.08), (33.47, -112.09), (33.44, -112.06)]
        ):
            _struggling(connection, BASE + 200 + index, latitude, longitude)
        _add_node(connection, BASE + 260, 33.30, -112.20, role="ROUTER")

    _run(settings, coverage.run_once)
    _run(settings, gaps.run_once)
    assert _run_siting(settings) == ["LongFast"]

    document = _siting(settings)
    assert document["available"] is True
    areas = document["areas"]
    assert len(areas) == 1
    assert areas[0]["node_count"] == 4
    assert areas[0]["point_count"] == 4

    candidates = document["candidates"]
    assert candidates, "an area with four nodes and real terrain must offer a candidate"
    # Both kinds are offered: a node already standing there, and ground.
    kinds = {row["kind"] for row in candidates}
    assert "existing_node" in kinds
    assert "ground" in kinds

    # The engine ran on the top few and said something specific.
    confirmed = [row for row in candidates if row["method"] == "splat"]
    assert confirmed, "no candidate reached the engine"
    assert len(confirmed) <= settings.gaps_splat_per_cluster
    for row in confirmed:
        assert isinstance(row["newly_usable"], int)
        assert row["state"] in ("ok", "bad")
        assert row["run_stamp"] == coverage_store.current_stamp(settings)
    assert any(row["newly_usable"] > 0 for row in confirmed)

    # And the cost is reported, because a job that holds a core on a
    # shared box has to say what it cost.
    cost = document["cost"]
    assert cost["predictions"] == len(confirmed)
    assert cost["predictions"] <= settings.gaps_max_predictions
    assert cost["engine_seconds"] > 0

    # The API serves the written file and nothing else.
    client = TestClient(create_app(settings))
    served = client.get("/api/gaps/areas").json()
    assert served["available"] is True
    assert len(served["areas"]) == 1
    assert "candidates" not in served
    assert served["caveats"], "the limits travel with the answer"

    rows = client.get("/api/gaps/candidates").json()
    assert rows["matched_count"] == len(candidates)
    assert rows["assumed_radio"]["tx_power_dbm"] == settings.gaps_candidate_tx_power_dbm
    assert rows["assumed_radio"]["antenna_height_m"] == settings.gaps_candidate_height_m

    one = client.get("/api/gaps/candidates?area=0").json()
    assert one["matched_count"] == len(candidates)
    assert client.get("/api/gaps/candidates?area=7").json()["matched_count"] == 0


def test_a_box_with_no_terrain_says_unknown_and_never_no_benefit(
    timescale_url: str, migrated_engine, tmp_path: Path, clean: None
):  # type: ignore[no-untyped-def]
    """The state a new deployment starts in, and it must not lie.

    With no terrain page the ground under a candidate is unknown. A
    candidate that was not judged reports no count at all: `null`, never
    zero, because zero is a finding and this is an admission.
    """
    settings = _settings(timescale_url, tmp_path)
    with migrated_engine.begin() as connection:
        for index, (latitude, longitude) in enumerate(
            [(33.45, -112.07), (33.46, -112.08), (33.47, -112.09)]
        ):
            _struggling(connection, BASE + 300 + index, latitude, longitude)

    _run(settings, gaps.run_once)
    assert _run_siting(settings) == ["LongFast"]

    document = _siting(settings)
    assert len(document["areas"]) == 1
    # No ground candidate can be found without terrain, and the nodes
    # already standing there cannot be judged.
    for row in document["candidates"]:
        assert row["kind"] == "existing_node"
        assert row["state"] == "unknown"
        assert row["newly_usable"] is None
        assert "not the same as no benefit" in row["sentence"]
    assert document["cost"]["predictions"] == 0
    assert "N33W113" in document["missing_terrain_tiles"]


# ------------------------------------------------------- what is demand


def test_a_node_that_moves_is_never_sited_for(
    timescale_url: str, migrated_engine, tmp_path: Path, clean: None
):  # type: ignore[no-untyped-def]
    """A footprint drawn to serve a node that moves serves nobody tomorrow."""
    settings = _settings(timescale_url, tmp_path, gaps_mobile_spread_km=0.5)
    _write_terrain(settings)
    now = datetime.now(UTC)
    with migrated_engine.begin() as connection:
        for index, (latitude, longitude) in enumerate(
            [(33.45, -112.07), (33.46, -112.08), (33.47, -112.09)]
        ):
            _struggling(connection, BASE + 400 + index, latitude, longitude)
        # The first of them wandered ten kilometres during the window.
        for hop, latitude in enumerate((33.45, 33.55)):
            connection.execute(
                text(
                    "INSERT INTO position_metrics (node_num, packet_id, latitude, longitude, "
                    "time) VALUES (:n, :p, :lat, :lon, :t)"
                ),
                {
                    "n": BASE + 400,
                    "p": 77_000 + hop,
                    "lat": latitude,
                    "lon": -112.07,
                    "t": now - timedelta(hours=hop + 1),
                },
            )

    _run(settings, gaps.run_once)
    _run_siting(settings)

    document = _siting(settings)
    moving = f"!{BASE + 400:08x}"
    for area in document["areas"]:
        assert moving not in area["node_ids"]
    # Two nodes left is not an area at all, so nothing is sited.
    assert document["areas"] == []


def test_a_coarse_position_is_never_sited_for_and_never_offered_as_a_site(
    timescale_url: str, migrated_engine, tmp_path: Path, clean: None
):  # type: ignore[no-untyped-def]
    """A position the broker fuzzed cannot choose a hilltop."""
    settings = _settings(timescale_url, tmp_path)
    _write_terrain(settings)
    with migrated_engine.begin() as connection:
        for index, (latitude, longitude) in enumerate(
            [(33.45, -112.07), (33.46, -112.08), (33.47, -112.09)]
        ):
            _struggling(connection, BASE + 500 + index, latitude, longitude)
        connection.execute(
            text("UPDATE node SET last_position_precision_bits = 12 WHERE node_num = :num"),
            {"num": BASE + 500},
        )

    _run(settings, gaps.run_once)
    _run_siting(settings)

    document = _siting(settings)
    coarse = f"!{BASE + 500:08x}"
    for area in document["areas"]:
        assert coarse not in area["node_ids"]
    for row in document["candidates"]:
        assert row["node_id"] != coarse


# -------------------------------------------------------- one preset only


def test_two_presets_get_two_siting_answers_that_borrow_nothing(
    timescale_url: str, migrated_engine, tmp_path: Path, clean: None
):  # type: ignore[no-untyped-def]
    """A node on Long fast cannot hear a node on Medium fast. `AGENTS.md` 9.7."""
    settings = _settings(timescale_url, tmp_path)
    _write_terrain(settings)
    with migrated_engine.begin() as connection:
        for index, (latitude, longitude) in enumerate(
            [(33.45, -112.07), (33.46, -112.08), (33.47, -112.09)]
        ):
            _struggling(connection, BASE + 600 + index, latitude, longitude)
        # One neighbourhood on the other preset, far away.
        for index, (latitude, longitude) in enumerate(
            [(33.10, -111.40), (33.11, -111.41), (33.12, -111.42), (33.13, -111.43)]
        ):
            node = BASE + 620 + index
            _add_node(connection, node, latitude, longitude, channel="MediumFast", role="CLIENT")
            connection.execute(
                text("UPDATE node SET is_mqtt_gateway = true WHERE node_num = :num"),
                {"num": node},
            )
            _busy(
                connection,
                node,
                node * 10,
                lambda hour, n=node: [(n, None, 6.0)],
                channel="MediumFast",
                hours=8,
            )

    _run(settings, gaps.run_once)
    written = _run_siting(settings)
    assert set(written) == {"LongFast", "MediumFast"}

    long_fast = _siting(settings, "LongFast")
    medium = _siting(settings, "MediumFast")
    long_ids = {node for area in long_fast["areas"] for node in area["node_ids"]}
    medium_ids = {node for area in medium["areas"] for node in area["node_ids"]}

    assert long_ids
    assert medium_ids
    assert not (long_ids & medium_ids), "a node was counted on two presets at once"
    # And there is no merged answer anywhere.
    assert store.read_siting(settings, "Every") is None


# ------------------------------------------------------- the engine cost


def test_the_engine_never_runs_more_times_than_the_budget_allows(
    timescale_url: str, migrated_engine, tmp_path: Path, clean: None
):  # type: ignore[no-untyped-def]
    """The ceiling is a setting, not a hope.

    This job runs on a three core box that also serves a public
    dashboard. A run that could not be bounded would be a run that takes
    the last core whenever the mesh got worse.
    """
    settings = _settings(timescale_url, tmp_path, gaps_max_predictions=1)
    _write_terrain(settings, hill=(33.52, -112.12))
    with migrated_engine.begin() as connection:
        for index, (latitude, longitude) in enumerate(
            [(33.45, -112.07), (33.46, -112.08), (33.47, -112.09), (33.44, -112.06)]
        ):
            _struggling(connection, BASE + 700 + index, latitude, longitude)

    _run(settings, gaps.run_once)
    _run_siting(settings)

    document = _siting(settings)
    assert document["cost"]["predictions"] == 1
    assert len([row for row in document["candidates"] if row["method"] == "splat"]) == 1
    # And the rest are still reported, as screened rows that say so.
    screened = [row for row in document["candidates"] if row["method"] == "terrain_screen"]
    assert screened
    for row in screened:
        assert row["newly_usable"] is None


def test_a_prediction_over_a_worker_process_answers_the_same(
    timescale_url: str, migrated_engine, tmp_path: Path, clean: None
):  # type: ignore[no-untyped-def]
    """The pool path, which must be spawn and never fork.

    `AGENTS.md` 9.16.5: fork copies only the calling thread, so a lock
    another thread held is held for ever in the child and the pool waits
    for a result that never comes. There is no error and no timeout.
    """
    with migrated_engine.begin() as connection:
        for index, (latitude, longitude) in enumerate(
            [(33.45, -112.07), (33.46, -112.08), (33.47, -112.09)]
        ):
            _struggling(connection, BASE + 800 + index, latitude, longitude)

    answers = []
    for workers in (0, 1):
        settings = _settings(
            timescale_url, tmp_path / f"w{workers}", gaps_workers=workers, gaps_max_predictions=1
        )
        _write_terrain(settings)
        _run(settings, gaps.run_once)
        _run_siting(settings)
        confirmed = [row for row in _siting(settings)["candidates"] if row["method"] == "splat"]
        assert confirmed
        answers.append(
            [(row["latitude"], row["longitude"], row["newly_usable"]) for row in confirmed]
        )

    assert answers[0] == answers[1]


# ------------------------------------------------------------- the API


def test_the_api_reads_the_artefact_and_computes_nothing(
    timescale_url: str, migrated_engine, tmp_path: Path, clean: None
):  # type: ignore[no-untyped-def]
    """Delete the file and the endpoint says so, rather than recomputing."""
    settings = _settings(timescale_url, tmp_path)
    _write_terrain(settings)
    with migrated_engine.begin() as connection:
        for index, (latitude, longitude) in enumerate(
            [(33.45, -112.07), (33.46, -112.08), (33.47, -112.09)]
        ):
            _struggling(connection, BASE + 900 + index, latitude, longitude)

    _run(settings, gaps.run_once)
    _run_siting(settings)

    client = TestClient(create_app(settings))
    assert client.get("/api/gaps/areas").json()["available"] is True

    path = store.siting_path(settings, "LongFast")
    assert path is not None
    path.unlink()

    body = client.get("/api/gaps/areas").json()
    assert body["available"] is False
    assert body["reason"] == "no_siting_run"
    assert body["areas"] == []
    # And the limits are still served, because they do not depend on a run.
    assert body["caveats"]


def test_a_channel_that_names_no_preset_is_refused_not_guessed(
    timescale_url: str, migrated_engine, tmp_path: Path, clean: None
):  # type: ignore[no-untyped-def]
    """Weather rides on top of a preset and does not name one."""
    settings = _settings(timescale_url, tmp_path)
    client = TestClient(create_app(settings))

    body = client.get("/api/gaps/candidates?channel=Weather").json()
    assert body["available"] is False
    assert body["reason"] == "not_a_preset"
    assert body["candidates"] == []


def test_the_siting_routes_take_no_writes(
    timescale_url: str, migrated_engine, tmp_path: Path, clean: None
):  # type: ignore[no-untyped-def]
    settings = _settings(timescale_url, tmp_path)
    client = TestClient(create_app(settings))
    for path in ("/api/gaps/areas", "/api/gaps/candidates"):
        for call in (client.post, client.put, client.patch, client.delete):
            assert call(path).status_code in (404, 405)


def test_a_torn_file_is_never_served(
    timescale_url: str, migrated_engine, tmp_path: Path, clean: None
):  # type: ignore[no-untyped-def]
    """The job writes to a temporary name and renames over the old file."""
    settings = _settings(timescale_url, tmp_path)
    root = Path(settings.coverage_cache_dir) / "gaps"
    root.mkdir(parents=True, exist_ok=True)
    (root / "index.json").write_text(json.dumps({"presets": [{"preset": "LongFast"}]}))
    (root / "siting-LongFast.json").write_text("{ not json at all")

    client = TestClient(create_app(settings))
    body = client.get("/api/gaps/areas").json()
    assert body["available"] is False
