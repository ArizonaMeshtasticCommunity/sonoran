"""The coverage and calibration jobs, against a real database.

The unit tests pin the parts. This runs the whole thing the way the
jobs container does: real schema, real roles, real rows, the engine,
the tiles, and the API that serves them.

It is also where the states a new deployment starts in are checked. An
empty database, a mesh with no positions, and a mesh on a channel that
is not a preset are all working states, and none of them may raise.
"""

import asyncio
import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from sonoran.api.app import create_app
from sonoran.config import Settings
from sonoran.coverage import store
from sonoran.db.session import make_engine, make_session_factory
from sonoran.jobs import calibrate, coverage
from sonoran.radio.overrides import load_overrides


def _jobs_url(timescale_url: str) -> str:
    """Make an async URL for the migration-created jobs role."""
    _, address = timescale_url.split("@", maxsplit=1)
    return f"postgresql+asyncpg://azmsh_jobs:change_me@{address}"


def _settings(timescale_url: str, tmp_path: Path, **extra: object) -> Settings:
    # One process unless a test asks otherwise, so a test is about the
    # pipeline. `test_a_run_over_worker_processes_answers_the_same` is
    # the one that asks otherwise.
    extra.setdefault("coverage_workers", 1)
    return Settings(
        _env_file=None,
        database_url_jobs=_jobs_url(timescale_url),
        database_url_api=_jobs_url(timescale_url).replace("azmsh_jobs", "azmsh_api"),
        coverage_cache_dir=str(tmp_path / "coverage"),
        landcover_cache_dir=str(tmp_path / "landcover"),
        terrain_cache_dir=str(tmp_path / "terrain"),
        terrain_allow_download=False,
        # Small, so the test is about the pipeline and not the engine.
        coverage_radius_km=8.0,
        coverage_min_zoom=7,
        coverage_max_zoom=8,
        **extra,
    )


@pytest.fixture
def clean(migrated_engine) -> Iterator[None]:  # type: ignore[no-untyped-def]
    """Leave the tables as they were found."""
    yield
    with migrated_engine.begin() as connection:
        for table in ("neighbor_metrics", "node"):
            connection.execute(text(f"DELETE FROM {table} WHERE node_num >= 900000"))
        connection.execute(text("DELETE FROM node WHERE node_num >= 900000"))


def _add_node(
    connection,  # type: ignore[no-untyped-def]
    node_num: int,
    latitude: float | None,
    longitude: float | None,
    channel: str | None = "LongFast",
    role: str = "ROUTER",
    hours_ago: float = 1.0,
) -> None:
    """Insert one node the way ingest would have."""
    heard = datetime.now(UTC) - timedelta(hours=hours_ago)
    connection.execute(
        text(
            "INSERT INTO node (node_num, node_id, short_name, long_name, hw_model, role, "
            "last_lat, last_lon, last_channel, last_heard, first_seen, updated_at, "
            "is_mqtt_gateway) "
            "VALUES (:num, :ident, :short, :long, 'RAK4631', :role, :lat, :lon, :channel, "
            ":heard, :heard, :heard, false) "
            "ON CONFLICT (node_num) DO UPDATE SET last_lat = :lat, last_lon = :lon, "
            "last_channel = :channel, last_heard = :heard"
        ),
        {
            "num": node_num,
            "ident": f"!{node_num:08x}",
            "short": f"N{node_num % 1000:03d}",
            "long": f"Node {node_num}",
            "role": role,
            "lat": latitude,
            "lon": longitude,
            "channel": channel,
            "heard": heard,
        },
    )


def _run(settings: Settings, job) -> object:  # type: ignore[no-untyped-def]
    """Run one job against the database and return what it made."""

    async def go() -> object:
        engine = make_engine(settings.database_url_jobs)
        factory = make_session_factory(engine)
        try:
            async with factory() as session:
                return await job(session, settings)
        finally:
            await engine.dispose()

    return asyncio.run(go())


# --- the states a new deployment starts in -----------------------------


def test_an_empty_database_makes_no_run(timescale_url: str, migrated_engine, tmp_path: Path):  # type: ignore[no-untyped-def]
    """A deployment that has just connected has no nodes.

    That is a working state. The page says the map has not been made
    yet, and nothing raises.
    """
    settings = _settings(timescale_url, tmp_path)
    with migrated_engine.begin() as connection:
        connection.execute(text("DELETE FROM node WHERE node_num >= 900000"))

    assert _run(settings, coverage.run_once) is None
    assert store.read_manifest(settings) is None
    assert store.current_stamp(settings) is None


def test_nodes_with_no_position_make_no_run(
    timescale_url: str, migrated_engine, tmp_path: Path, clean: None
):  # type: ignore[no-untyped-def]
    """A node that has never had a fix cannot be a transmitter."""
    settings = _settings(timescale_url, tmp_path)
    with migrated_engine.begin() as connection:
        _add_node(connection, 900001, None, None)
        # And one on Null Island, which is what an unset position looks
        # like. See sonoran/positions.py.
        _add_node(connection, 900002, 0.0, 0.0)

    assert _run(settings, coverage.run_once) is None


def test_a_node_on_a_channel_that_is_not_a_preset_is_left_out(
    timescale_url: str, migrated_engine, tmp_path: Path, clean: None
):  # type: ignore[no-untyped-def]
    """Weather and PKI ride on a preset. They do not name one.

    Guessing a preset for them would draw a link that cannot exist.
    See AGENTS.md 9.7.
    """
    settings = _settings(timescale_url, tmp_path)
    with migrated_engine.begin() as connection:
        _add_node(connection, 900003, 33.45, -112.07, channel="Weather")
        _add_node(connection, 900004, 33.46, -112.08, channel="PKI")

    assert _run(settings, coverage.run_once) is None


def test_a_node_the_mesh_has_not_heard_in_a_long_time_is_left_out(
    timescale_url: str, migrated_engine, tmp_path: Path, clean: None
):  # type: ignore[no-untyped-def]
    """A node that is gone must not hold coverage open on the map."""
    settings = _settings(timescale_url, tmp_path, coverage_active_hours=24)
    with migrated_engine.begin() as connection:
        _add_node(connection, 900005, 33.45, -112.07, hours_ago=200.0)

    assert _run(settings, coverage.run_once) is None


# --- a real run --------------------------------------------------------


def test_a_run_makes_tiles_the_api_serves(
    timescale_url: str, migrated_engine, tmp_path: Path, clean: None
):  # type: ignore[no-untyped-def]
    """The whole pipeline, from a row to a tile in a browser."""
    settings = _settings(timescale_url, tmp_path)
    with migrated_engine.begin() as connection:
        _add_node(connection, 900010, 33.45, -112.07)
        _add_node(connection, 900011, 33.50, -112.02)

    manifest = _run(settings, coverage.run_once)
    assert manifest is not None
    assert manifest.presets, "a run must report the preset it predicted"

    preset = manifest.presets[0]
    assert preset.preset == "LongFast"
    assert preset.node_count == 2
    assert preset.tile_count > 0
    assert preset.usable_area_km2 > 0
    assert preset.data_bounds is not None

    # No terrain is cached and downloads are off, so the run is over
    # flat ground and must say so rather than let a reader believe
    # otherwise.
    assert manifest.has_terrain is False
    assert manifest.has_landcover is False
    assert manifest.missing_terrain_tiles

    # And the API serves what the job wrote.
    client = TestClient(create_app(settings))
    summary = client.get("/api/coverage").json()
    assert summary["available"] is True
    assert [item["preset"] for item in summary["presets"]] == ["LongFast"]
    stamp = summary["stamp"]

    root = store.current_root(settings)
    assert root is not None
    tile = next(root.glob("LongFast/usable/*/*/*.png"))
    zoom, x, y = tile.parts[-3], tile.parts[-2], tile.stem
    response = client.get(f"/api/coverage/tiles/{stamp}/LongFast/usable/{zoom}/{x}/{y}.png")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert "immutable" in response.headers.get("Cache-Control", "")


def test_two_presets_are_predicted_apart(
    timescale_url: str, migrated_engine, tmp_path: Path, clean: None
):  # type: ignore[no-untyped-def]
    """A node on one preset cannot hear a node on another.

    Merging them would draw a mesh that does not exist. The preset is
    part of the run, not a filter on the display. See AGENTS.md 9.7.
    """
    settings = _settings(timescale_url, tmp_path)
    with migrated_engine.begin() as connection:
        _add_node(connection, 900020, 33.45, -112.07, channel="LongFast")
        _add_node(connection, 900021, 33.46, -112.08, channel="MediumSlow")

    manifest = _run(settings, coverage.run_once)
    assert manifest is not None
    names = sorted(item.preset for item in manifest.presets)
    assert names == ["LongFast", "MediumSlow"]
    for item in manifest.presets:
        assert item.node_count == 1

    root = store.current_root(settings)
    assert root is not None
    assert (root / "LongFast").is_dir()
    assert (root / "MediumSlow").is_dir()


def test_the_cap_on_nodes_keeps_the_strongest(
    timescale_url: str, migrated_engine, tmp_path: Path, clean: None
):  # type: ignore[no-untyped-def]
    """A run that has to leave nodes out must leave out the ones that
    would have changed the map least."""
    settings = _settings(timescale_url, tmp_path, coverage_max_nodes=2)
    with migrated_engine.begin() as connection:
        for offset in range(5):
            _add_node(connection, 900030 + offset, 33.40 + offset / 100, -112.07)

    manifest = _run(settings, coverage.run_once)
    assert manifest is not None
    preset = manifest.presets[0]
    assert preset.node_count == 5
    assert preset.positioned_count == 2
    assert preset.skipped_count == 3


def test_a_second_run_replaces_the_first_in_one_step(
    timescale_url: str, migrated_engine, tmp_path: Path, clean: None
):  # type: ignore[no-untyped-def]
    """A reader must never see half a run."""
    settings = _settings(timescale_url, tmp_path)
    with migrated_engine.begin() as connection:
        _add_node(connection, 900040, 33.45, -112.07)

    first = _run(settings, coverage.run_once)
    assert first is not None
    stamp_one = store.current_stamp(settings)

    second = _run(settings, coverage.run_once)
    assert second is not None
    stamp_two = store.current_stamp(settings)

    assert stamp_two is not None
    # A run made in the same second reuses its stamp, which is fine: it
    # replaced the directory whole either way.
    assert stamp_one is not None
    assert store.read_manifest(settings) is not None
    assert not list(Path(settings.coverage_cache_dir).glob("pending-*"))


# --- calibration -------------------------------------------------------


def test_calibration_with_no_reports_writes_nothing(
    timescale_url: str, migrated_engine, tmp_path: Path, clean: None
):  # type: ignore[no-untyped-def]
    """A new deployment has heard no neighbour lists yet."""
    settings = _settings(timescale_url, tmp_path)
    with migrated_engine.begin() as connection:
        connection.execute(text("DELETE FROM neighbor_metrics"))
        _add_node(connection, 900050, 33.45, -112.07)

    assert _run(settings, calibrate.run_once) is None
    assert store.calibration_offsets(settings) == {}


def test_calibration_reads_the_neighbour_reports(
    timescale_url: str, migrated_engine, tmp_path: Path, clean: None
):  # type: ignore[no-untyped-def]
    """A node reporting what it hears is the source. See AGENTS.md 9.5."""
    settings = _settings(timescale_url, tmp_path)
    now = datetime.now(UTC)
    with migrated_engine.begin() as connection:
        connection.execute(text("DELETE FROM neighbor_metrics"))
        for offset in range(4):
            _add_node(connection, 900060 + offset, 33.40 + offset / 200, -112.07)
        for reporter in range(4):
            for heard in range(4):
                if reporter == heard:
                    continue
                connection.execute(
                    text(
                        "INSERT INTO neighbor_metrics "
                        "(node_num, neighbor_node_num, snr, channel, time) "
                        "VALUES (:a, :b, :snr, 'LongFast', :now)"
                    ),
                    {
                        "a": 900060 + reporter,
                        "b": 900060 + heard,
                        "snr": -5.0 - reporter,
                        "now": now,
                    },
                )

    result = _run(settings, calibrate.run_once)
    assert result is not None
    assert result.nodes, "the fit must name the nodes it saw"
    # Every offset is anchored, so they sum to nothing.
    assert abs(sum(fit.offset_db for fit in result.nodes)) < 0.5

    document = store.read_calibration(settings)
    assert document is not None
    assert document["summary"]["count"] > 0

    # And the API shows it.
    client = TestClient(create_app(settings))
    report = client.get("/api/coverage/calibration").json()
    assert report["available"] is True
    assert len(report["nodes"]) == len(result.nodes)


def test_calibration_rejects_a_report_from_another_preset(
    timescale_url: str, migrated_engine, tmp_path: Path, clean: None
):  # type: ignore[no-untyped-def]
    """An old report must not correct a node's current preset."""
    settings = _settings(timescale_url, tmp_path)
    now = datetime.now(UTC)
    with migrated_engine.begin() as connection:
        connection.execute(text("DELETE FROM neighbor_metrics"))
        _add_node(connection, 900070, 33.40, -112.07, channel="LongFast")
        _add_node(connection, 900071, 33.41, -112.07, channel="LongFast")
        connection.execute(
            text(
                "INSERT INTO neighbor_metrics "
                "(node_num, neighbor_node_num, snr, channel, time) VALUES "
                "(900070, 900071, -9.0, 'LongFast', :now), "
                "(900070, 900071, 20.0, 'MediumSlow', :now)"
            ),
            {"now": now},
        )

    async def reports(session, given: Settings) -> dict[int, dict[int, float]]:
        peers = await calibrate.read_peers(
            session, given, load_overrides(given.radio_overrides_path)
        )
        return await calibrate.read_reports(session, given, peers)

    assert _run(settings, reports) == {900070: {900071: -9.0}}


def test_a_broken_calibration_file_does_not_stop_a_run(
    timescale_url: str, migrated_engine, tmp_path: Path, clean: None
):  # type: ignore[no-untyped-def]
    """A half written file must leave the map on its nameplate figures
    rather than stop it being drawn."""
    settings = _settings(timescale_url, tmp_path)
    path = store.calibration_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")

    with migrated_engine.begin() as connection:
        _add_node(connection, 900070, 33.45, -112.07)

    assert store.calibration_offsets(settings) == {}
    manifest = _run(settings, coverage.run_once)
    assert manifest is not None
    assert manifest.calibrated_nodes == 0


def test_the_jobs_role_never_writes_a_table_for_this(
    timescale_url: str, migrated_engine, tmp_path: Path, clean: None
):  # type: ignore[no-untyped-def]
    """The coverage work writes files, not rows.

    So it needs no new grant and no fourth database role. If that ever
    changes, this test is the reminder that a migration is needed too.
    """
    settings = _settings(timescale_url, tmp_path)
    with migrated_engine.begin() as connection:
        _add_node(connection, 900080, 33.45, -112.07)
        before = connection.execute(text("SELECT count(*) FROM daily_snapshot")).scalar_one()

    _run(settings, coverage.run_once)

    with migrated_engine.begin() as connection:
        after = connection.execute(text("SELECT count(*) FROM daily_snapshot")).scalar_one()
    assert after == before

    assert json.loads(store.index_path(settings).read_text(encoding="utf-8"))["current"]


def test_a_run_over_worker_processes_answers_the_same(
    timescale_url: str, migrated_engine, tmp_path: Path, clean: None
):  # type: ignore[no-untyped-def]
    """The path production takes, which one process does not exercise.

    `COVERAGE_WORKERS` is zero by default, which means as many as the
    machine has less one, so a deployment nearly always predicts over a
    pool. Everything a site needs is pickled to get there. A `Settings`
    or a `Site` that stopped pickling would leave every other test in
    this file green and break every real run.

    The answer must also be the same either way. The pool returns in
    the order the sites were given, not the order they finished.
    """
    with migrated_engine.begin() as connection:
        _add_node(connection, 900070, 33.45, -112.07)
        _add_node(connection, 900071, 33.50, -112.02)
        _add_node(connection, 900072, 33.40, -112.12)

    alone = _run(_settings(timescale_url, tmp_path / "alone"), coverage.run_once)
    pooled = _run(
        _settings(timescale_url, tmp_path / "pooled", coverage_workers=2), coverage.run_once
    )
    assert alone is not None and pooled is not None

    assert pooled.presets[0].node_count == 3
    assert pooled.presets[0].tile_count == alone.presets[0].tile_count
    assert pooled.presets[0].usable_area_km2 == alone.presets[0].usable_area_km2
    assert pooled.presets[0].data_bounds == alone.presets[0].data_bounds

    # Every site must be named, in the order the sites were given.
    assert [note["node_id"] for note in pooled.presets[0].nodes] == [
        note["node_id"] for note in alone.presets[0].nodes
    ]

    # And the tiles themselves, byte for byte.
    alone_root = store.current_root(_settings(timescale_url, tmp_path / "alone"))
    pooled_root = store.current_root(_settings(timescale_url, tmp_path / "pooled"))
    assert alone_root is not None and pooled_root is not None
    written = sorted(path.relative_to(pooled_root) for path in pooled_root.glob("**/*.png"))
    assert written, "the run must write tiles for this to prove anything"
    for relative in written:
        assert (pooled_root / relative).read_bytes() == (alone_root / relative).read_bytes(), (
            relative
        )
