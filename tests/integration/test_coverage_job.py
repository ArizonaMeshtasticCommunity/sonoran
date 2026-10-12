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
from sonoran.radio.resolve import MAX_CALIBRATION_DB
from tests.integration.conftest import role_url, run_store, wipe_job_outputs


def _jobs_url(timescale_url: str) -> str:
    """Make an async URL for the migration-created jobs role."""
    return role_url(timescale_url, "azmsh_jobs")


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
    wipe_job_outputs(migrated_engine)


def _add_node(
    connection,  # type: ignore[no-untyped-def]
    node_num: int,
    latitude: float | None,
    longitude: float | None,
    channel: str | None = "LongFast",
    *,
    role: str | None,
    hours_ago: float = 1.0,
    precision_bits: int | None = None,
) -> None:
    """Insert one node the way ingest would have.

    `role` has no default on purpose. It used to default to `ROUTER`,
    and that is why no test in this file ever caught the coverage job
    predicting from client nodes: every test asserted about routers
    while its author believed it asserted about nodes. Naming the role
    at each call is what keeps that from happening again.

    A default of None would be worse than `ROUTER` was. It would move
    every existing test to the excluded side at once and hide the very
    thing these tests are for.
    """
    heard = datetime.now(UTC) - timedelta(hours=hours_ago)
    connection.execute(
        text(
            "INSERT INTO node (node_num, node_id, short_name, long_name, hw_model, role, "
            "last_lat, last_lon, last_channel, last_heard, first_seen, updated_at, "
            "is_mqtt_gateway, last_position_precision_bits) "
            "VALUES (:num, :ident, :short, :long, 'RAK4631', :role, :lat, :lon, :channel, "
            ":heard, :heard, :heard, false, :bits) "
            "ON CONFLICT (node_num) DO UPDATE SET last_lat = :lat, last_lon = :lon, "
            "last_channel = :channel, last_heard = :heard, "
            "last_position_precision_bits = :bits"
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
            "bits": precision_bits,
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
        _add_node(connection, 900001, None, None, role="ROUTER")
        # And one on Null Island, which is what an unset position looks
        # like. See sonoran/positions.py.
        _add_node(connection, 900002, 0.0, 0.0, role="ROUTER")

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
        _add_node(connection, 900003, 33.45, -112.07, channel="Weather", role="ROUTER")
        _add_node(connection, 900004, 33.46, -112.08, channel="PKI", role="ROUTER")

    assert _run(settings, coverage.run_once) is None


def test_a_node_the_mesh_has_not_heard_in_a_long_time_is_left_out(
    timescale_url: str, migrated_engine, tmp_path: Path, clean: None
):  # type: ignore[no-untyped-def]
    """A node that is gone must not hold coverage open on the map."""
    settings = _settings(timescale_url, tmp_path, coverage_active_hours=24)
    with migrated_engine.begin() as connection:
        _add_node(connection, 900005, 33.45, -112.07, hours_ago=200.0, role="ROUTER")

    assert _run(settings, coverage.run_once) is None


def test_a_position_outside_the_terrain_region_is_left_out(
    timescale_url: str, migrated_engine, tmp_path: Path, clean: None
):  # type: ignore[no-untyped-def]
    """A regional map must not predict from a site outside its terrain."""
    settings = _settings(
        timescale_url,
        tmp_path,
        terrain_lat_min=33,
        terrain_lat_max=33,
        terrain_lon_min=-113,
        terrain_lon_max=-112,
    )
    with migrated_engine.begin() as connection:
        _add_node(connection, 900006, 33.45, -112.07, role="ROUTER")
        _add_node(connection, 900007, 34.45, -112.07, role="ROUTER")

    manifest = _run(settings, coverage.run_once)

    assert manifest is not None
    assert manifest.presets[0].node_count == 1


# --- a real run --------------------------------------------------------


def test_a_run_makes_tiles_the_api_serves(
    timescale_url: str, migrated_engine, tmp_path: Path, clean: None
):  # type: ignore[no-untyped-def]
    """The whole pipeline, from a row to a tile in a browser."""
    settings = _settings(timescale_url, tmp_path)
    with migrated_engine.begin() as connection:
        _add_node(connection, 900010, 33.45, -112.07, role="ROUTER")
        _add_node(connection, 900011, 33.50, -112.02, role="ROUTER")

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
    # A default run publishes the infrastructure site set, so the tiles
    # and the URL both carry that segment now. See the site-sets work.
    tile = next(root.glob("LongFast/infrastructure/usable/*/*/*.png"))
    zoom, x, y = tile.parts[-3], tile.parts[-2], tile.stem
    response = client.get(
        f"/api/coverage/tiles/{stamp}/LongFast/infrastructure/usable/{zoom}/{x}/{y}.png"
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert "immutable" in response.headers.get("Cache-Control", "")

    # And the public embed serves the same pixels from its own route,
    # which is the one an operator opens at the proxy. The site set is
    # not in that URL: the route serves the infrastructure map and has
    # nowhere to be told otherwise. See `docs/API.md` 3B.4.
    public = TestClient(create_app(settings.model_copy(update={"embed_enabled": True})))
    embedded = public.get(f"/api/embed/tiles/{stamp}/LongFast/usable/{zoom}/{x}/{y}.png")
    assert embedded.status_code == 200
    assert embedded.content == response.content
    # With the embed off, as it ships, that path does not exist at all.
    assert (
        client.get(f"/api/embed/tiles/{stamp}/LongFast/usable/{zoom}/{x}/{y}.png").status_code
        == 404
    )


def test_two_presets_are_predicted_apart(
    timescale_url: str, migrated_engine, tmp_path: Path, clean: None
):  # type: ignore[no-untyped-def]
    """A node on one preset cannot hear a node on another.

    Merging them would draw a mesh that does not exist. The preset is
    part of the run, not a filter on the display. See AGENTS.md 9.7.
    """
    settings = _settings(timescale_url, tmp_path)
    with migrated_engine.begin() as connection:
        _add_node(connection, 900020, 33.45, -112.07, channel="LongFast", role="ROUTER")
        _add_node(connection, 900021, 33.46, -112.08, channel="MediumSlow", role="ROUTER")

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
            _add_node(connection, 900030 + offset, 33.40 + offset / 100, -112.07, role="ROUTER")

    manifest = _run(settings, coverage.run_once)
    assert manifest is not None
    preset = manifest.presets[0]
    assert preset.node_count == 5
    assert preset.site_count == 2
    assert preset.skipped_count == 3


def test_a_second_run_replaces_the_first_in_one_step(
    timescale_url: str, migrated_engine, tmp_path: Path, clean: None
):  # type: ignore[no-untyped-def]
    """A reader must never see half a run."""
    settings = _settings(timescale_url, tmp_path)
    with migrated_engine.begin() as connection:
        _add_node(connection, 900040, 33.45, -112.07, role="ROUTER")

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
    stale = {
        "generated_at": "2026-10-01T00:00:00+00:00",
        "model_bias_db": 0.0,
        "residual_spread_db": 1.0,
        "nodes": [
            {"node_id": "!000dbba0", "offset_db": -3.0, "observations": 9, "counterparties": 4}
        ],
    }
    assert run_store(settings, store.write_calibration_document, stale)
    with migrated_engine.begin() as connection:
        connection.execute(text("DELETE FROM neighbor_metrics"))
        _add_node(connection, 900050, 33.45, -112.07, role="ROUTER")

    assert _run(settings, calibrate.run_once) is None
    assert run_store(settings, store.calibration_offsets) == {}
    assert run_store(settings, store.read_calibration) is None, (
        "a stale fit must not survive an empty current window"
    )


def test_calibration_reads_the_neighbour_reports(
    timescale_url: str, migrated_engine, tmp_path: Path, clean: None
):  # type: ignore[no-untyped-def]
    """A node reporting what it hears is the source. See AGENTS.md 9.5."""
    settings = _settings(timescale_url, tmp_path)
    now = datetime.now(UTC)
    with migrated_engine.begin() as connection:
        connection.execute(text("DELETE FROM neighbor_metrics"))
        for offset in range(4):
            _add_node(connection, 900060 + offset, 33.40 + offset / 200, -112.07, role="ROUTER")
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

    document = run_store(settings, store.read_calibration)
    assert document is not None
    assert document["summary"]["count"] > 0

    # And the API shows it.
    client = TestClient(create_app(settings))
    report = client.get("/api/coverage/calibration").json()
    assert report["available"] is True
    assert len(report["nodes"]) == len(result.nodes)
    assert all(
        item["offset_db"] is None or abs(item["offset_db"]) <= MAX_CALIBRATION_DB
        for item in report["nodes"]
    )


def _four_reporting_nodes(migrated_engine, first: int) -> None:  # type: ignore[no-untyped-def]
    """Four nodes in a line, each reporting the other three.

    Every reporter names a different SNR, so the fit has real per-node
    offsets to hand out rather than a flat answer.
    """
    now = datetime.now(UTC)
    with migrated_engine.begin() as connection:
        connection.execute(text("DELETE FROM neighbor_metrics"))
        for offset in range(4):
            _add_node(connection, first + offset, 33.40 + offset / 200, -112.07, role="ROUTER")
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
                        "a": first + reporter,
                        "b": first + heard,
                        "snr": -5.0 - 4.0 * reporter,
                        "now": now,
                    },
                )


def test_a_locked_node_is_held_at_zero_by_the_fit(
    timescale_url: str, migrated_engine, tmp_path: Path, clean: None
):  # type: ignore[no-untyped-def]
    """Issue #3, item 4.

    `lock_calibration` used to keep an offset from being applied and
    leave the node free inside the fit, where it absorbed evidence that
    belonged to the other end of every link it was in. The lock says
    the radio facts are already right, so the fit has to solve around
    the node rather than about it.

    This is checked through the job, not only through `fit_offsets`,
    because the overrides file is how an operator writes the lock and
    the job is what has to read it.
    """
    _four_reporting_nodes(migrated_engine, 900130)
    pinned_id = f"!{900130:08x}"

    plain = _settings(timescale_url, tmp_path / "plain")
    unpinned = _run(plain, calibrate.run_once)
    assert unpinned is not None
    loose = {fit.node_id: fit for fit in unpinned.nodes}
    assert loose[pinned_id].offset_db != 0.0, (
        "the fit must move this node when it is not pinned, or the test proves nothing"
    )

    overrides = tmp_path / "nodes.yaml"
    overrides.write_text(
        f'nodes:\n  "{pinned_id}":\n    lock_calibration: true\n'
        '    note: "Measured on the mast."\n',
        encoding="utf-8",
    )
    held = _settings(timescale_url, tmp_path / "held", radio_overrides_path=str(overrides))
    result = _run(held, calibrate.run_once)
    assert result is not None
    fits = {fit.node_id: fit for fit in result.nodes}

    assert fits[pinned_id].offset_db == 0.0, "a pinned node is held at zero inside the fit"
    assert fits[pinned_id].locked is True
    assert loose[pinned_id].locked is False
    assert pinned_id not in result.usable()
    # The fit still had offsets to hand out, and the other nodes took
    # them. A fit that flattened everything would also pass the test
    # above and would not be the fix.
    assert any(fit.offset_db != 0.0 for fit in result.nodes if fit.node_id != pinned_id)
    # The bias is now measured against the pinned radio, so the anchor
    # moved and the answer is a different one.
    assert result.model_bias_db != unpinned.model_bias_db

    # And what the map reads never carries the pinned node.
    assert pinned_id not in run_store(held, store.calibration_offsets)
    client = TestClient(create_app(held))
    report = client.get("/api/coverage/calibration").json()
    entry = next(item for item in report["nodes"] if item["node_id"] == pinned_id)
    assert entry["locked"] is True
    assert entry["applied"] is False
    assert entry["offset_db"] is None


def test_calibration_rejects_a_report_from_another_preset(
    timescale_url: str, migrated_engine, tmp_path: Path, clean: None
):  # type: ignore[no-untyped-def]
    """An old report must not correct a node's current preset."""
    settings = _settings(timescale_url, tmp_path)
    now = datetime.now(UTC)
    with migrated_engine.begin() as connection:
        connection.execute(text("DELETE FROM neighbor_metrics"))
        _add_node(connection, 900070, 33.40, -112.07, channel="LongFast", role="ROUTER")
        _add_node(connection, 900071, 33.41, -112.07, channel="LongFast", role="ROUTER")
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


def test_calibration_rejects_a_node_outside_the_terrain_region(
    timescale_url: str, migrated_engine, tmp_path: Path, clean: None
):  # type: ignore[no-untyped-def]
    """The fit must not use flat ground for a node outside the region."""
    settings = _settings(
        timescale_url,
        tmp_path,
        terrain_lat_min=33,
        terrain_lat_max=33,
        terrain_lon_min=-113,
        terrain_lon_max=-112,
    )
    with migrated_engine.begin() as connection:
        _add_node(connection, 900072, 33.45, -112.07, role="ROUTER")
        _add_node(connection, 900073, 34.45, -112.07, role="ROUTER")

    async def peers(session, given: Settings):  # type: ignore[no-untyped-def]
        return await calibrate.read_peers(
            session, given, load_overrides(given.radio_overrides_path)
        )

    found = _run(settings, peers)
    assert set(found) == {900072}


def test_calibration_uses_an_operator_position_for_a_coarse_node(
    timescale_url: str, migrated_engine, tmp_path: Path, clean: None
):  # type: ignore[no-untyped-def]
    """Coverage and calibration must reason about the same place."""
    overrides = tmp_path / "nodes.yaml"
    overrides.write_text(
        'nodes:\n  "!000dbc16":\n    latitude: 33.6000\n    longitude: -112.2000\n',
        encoding="utf-8",
    )
    settings = _settings(timescale_url, tmp_path, radio_overrides_path=str(overrides))
    with migrated_engine.begin() as connection:
        _add_node(connection, 900118, 33.45, -112.07, role="ROUTER", precision_bits=13)

    async def peers(session, given: Settings):  # type: ignore[no-untyped-def]
        return await calibrate.read_peers(
            session, given, load_overrides(given.radio_overrides_path)
        )

    found = _run(settings, peers)
    assert found[900118].latitude == 33.6
    assert found[900118].longitude == -112.2


def test_calibration_uses_the_configured_position_precision(
    timescale_url: str, migrated_engine, tmp_path: Path, clean: None
):  # type: ignore[no-untyped-def]
    """A private broker setting applies to both coverage jobs."""
    settings = _settings(timescale_url, tmp_path, coverage_min_precision_bits=0)
    with migrated_engine.begin() as connection:
        _add_node(connection, 900119, 33.45, -112.07, role="ROUTER", precision_bits=13)

    async def peers(session, given: Settings):  # type: ignore[no-untyped-def]
        return await calibrate.read_peers(
            session, given, load_overrides(given.radio_overrides_path)
        )

    assert 900119 in _run(settings, peers)


def test_an_untrusted_fit_does_not_stop_a_run(
    timescale_url: str, migrated_engine, tmp_path: Path, clean: None
):  # type: ignore[no-untyped-def]
    """A fit whose scatter is too wide must leave the map on its nameplate
    figures rather than stop it being drawn."""
    settings = _settings(timescale_url, tmp_path)
    untrusted = {
        "generated_at": "2026-10-01T00:00:00+00:00",
        "model_bias_db": 0.0,
        "residual_spread_db": 99.0,
        "nodes": [
            {
                "node_id": "!000dbba6",
                "offset_db": -5.0,
                "observations": 50,
                "counterparties": 9,
                "reported": 20,
            }
        ],
    }
    assert run_store(settings, store.write_calibration_document, untrusted)

    with migrated_engine.begin() as connection:
        _add_node(connection, 900070, 33.45, -112.07, role="ROUTER")

    assert run_store(settings, store.calibration_offsets) == {}
    manifest = _run(settings, coverage.run_once)
    assert manifest is not None
    assert manifest.calibrated_nodes == 0


def test_the_jobs_role_never_writes_a_table_for_this(
    timescale_url: str, migrated_engine, tmp_path: Path, clean: None
):  # type: ignore[no-untyped-def]
    """The coverage run writes tiles and a manifest, not rows.

    Its calibration and the gaps tables are other jobs' outputs (#351).
    If the coverage run ever writes a table, this test is the reminder
    that a migration and a grant are needed too.
    """
    settings = _settings(timescale_url, tmp_path)
    with migrated_engine.begin() as connection:
        _add_node(connection, 900080, 33.45, -112.07, role="ROUTER")
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
        _add_node(connection, 900070, 33.45, -112.07, role="ROUTER")
        _add_node(connection, 900071, 33.50, -112.02, role="ROUTER")
        _add_node(connection, 900072, 33.40, -112.12, role="ROUTER")

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


# --- who may be a site -------------------------------------------------
#
# Against a live 689-node mesh the job predicted from all of them. Only
# 20 were ROUTER and 30 ROUTER_LATE; the rest were clients, and most of
# those arrived with no role at all. The map that came out covered most
# of Arizona. See `sonoran/roles.py` and `docs/COVERAGE.md` 11.


def test_a_client_node_is_never_a_site(
    timescale_url: str, migrated_engine, tmp_path: Path, clean: None
):  # type: ignore[no-untyped-def]
    """A node with no role must not hold coverage open.

    The assertion is about the ground, not only the count. A bare count
    passes if the client is included and its footprint happens to sit
    inside the router's.
    """
    settings = _settings(timescale_url, tmp_path)
    with migrated_engine.begin() as connection:
        _add_node(connection, 900080, 33.45, -112.07, role="ROUTER")
        # Far enough away that its own footprint cannot overlap.
        _add_node(connection, 900081, 34.20, -111.20, role=None)

    manifest = _run(settings, coverage.run_once)
    assert manifest is not None
    preset = manifest.presets[0]
    assert preset.site_count == 1
    assert preset.candidate_count == 2
    assert preset.excluded_by_role == {"NULL": 1}

    # And the client's own position is not covered.
    bounds = preset.data_bounds
    assert bounds is not None
    assert not (bounds[0] <= 34.20 <= bounds[2] and bounds[1] <= -111.20 <= bounds[3])


@pytest.mark.parametrize(
    "role",
    [
        None,
        "CLIENT",
        "CLIENT_MUTE",
        "CLIENT_BASE",
        "CLIENT_HIDDEN",
        "ROUTER_CLIENT",
        "TRACKER",
        "SENSOR",
    ],
)
def test_every_client_role_is_excluded_by_name(
    timescale_url: str, migrated_engine, tmp_path: Path, clean: None, role: str | None
):  # type: ignore[no-untyped-def]
    """`ROUTER_CLIENT` is in this list on purpose. It reads like
    infrastructure and moves like a person."""
    settings = _settings(timescale_url, tmp_path)
    with migrated_engine.begin() as connection:
        _add_node(connection, 900082, 33.45, -112.07, role=role)

    manifest = _run(settings, coverage.run_once)
    assert manifest is None, f"{role} must not be a coverage site"


def test_the_manifest_says_which_roles_were_left_out(
    timescale_url: str, migrated_engine, tmp_path: Path, clean: None
):  # type: ignore[no-untyped-def]
    """The number the page shows is the number the job computed.

    A run that drops nine nodes in ten and says nothing is how the live
    map came to be trusted.
    """
    settings = _settings(timescale_url, tmp_path)
    with migrated_engine.begin() as connection:
        _add_node(connection, 900083, 33.45, -112.07, role="ROUTER")
        _add_node(connection, 900084, 33.46, -112.08, role="REPEATER")
        _add_node(connection, 900085, 33.47, -112.09, role=None)
        _add_node(connection, 900086, 33.48, -112.10, role=None)
        _add_node(connection, 900087, 33.49, -112.11, role="CLIENT_MUTE")

    manifest = _run(settings, coverage.run_once)
    assert manifest is not None
    preset = manifest.presets[0]
    assert preset.site_count == 2
    assert preset.candidate_count == 5
    assert preset.excluded_by_role == {"NULL": 2, "CLIENT_MUTE": 1}
    assert sum(preset.excluded_by_role.values()) == preset.candidate_count - preset.node_count


def test_an_infrastructure_subset_is_not_a_diagnostic_run(
    timescale_url: str, migrated_engine, tmp_path: Path, clean: None
):  # type: ignore[no-untyped-def]
    """A router-only run is narrower than the public role set."""
    settings = _settings(timescale_url, tmp_path, coverage_site_roles="ROUTER")
    with migrated_engine.begin() as connection:
        _add_node(connection, 900120, 33.45, -112.07, role="ROUTER")

    manifest = _run(settings, coverage.run_once)
    assert manifest is not None
    assert manifest.site_roles == ["ROUTER"]
    assert manifest.is_diagnostic is False


def test_a_diagnostic_run_never_reaches_the_public_tiles(
    timescale_url: str, migrated_engine, tmp_path: Path, clean: None
):  # type: ignore[no-untyped-def]
    """The whole pipeline of the finding, end to end.

    `COVERAGE_SITE_ROLES=ALL` predicts from every node, including the
    clients, and each one draws a footprint centred on somebody's
    house. Two things then have to hold at once:

    - the tiles are written under a directory that says what they are,
      and never under one named `infrastructure`, and
    - the public tile route answers nothing for the run, with the embed
      switched on.

    The dashboard keeps the run, because the dashboard is the audience a
    diagnostic is for.
    """
    settings = _settings(timescale_url, tmp_path, coverage_site_roles="ALL")
    with migrated_engine.begin() as connection:
        _add_node(connection, 900130, 33.45, -112.07, role="CLIENT")

    manifest = _run(settings, coverage.run_once)
    assert manifest is not None
    assert manifest.is_diagnostic is True
    assert [item.key for item in manifest.site_sets] == ["diagnostic"]

    root = store.current_root(settings)
    assert root is not None
    assert (root / "LongFast" / "diagnostic").is_dir()
    # The path said "routers and repeaters" while holding a footprint
    # around a client node. That is the directory that must not exist.
    assert not (root / "LongFast" / "infrastructure").exists()

    tile = next(root.glob("LongFast/diagnostic/usable/*/*/*.png"))
    zoom, x, y = tile.parts[-3], tile.parts[-2], tile.stem
    stamp = manifest.stamp

    public = TestClient(create_app(settings.model_copy(update={"embed_enabled": True})))
    assert (
        public.get(f"/api/embed/tiles/{stamp}/LongFast/usable/{zoom}/{x}/{y}.png").status_code
        == 404
    )
    assert public.get("/api/embed/coverage").json()["reason"] == "diagnostic"

    # And the dashboard has it, by the name the run wrote.
    dashboard = TestClient(create_app(settings))
    served = dashboard.get(
        f"/api/coverage/tiles/{stamp}/LongFast/diagnostic/usable/{zoom}/{x}/{y}.png"
    )
    assert served.status_code == 200
    assert served.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_a_mesh_of_only_clients_makes_no_run(
    timescale_url: str, migrated_engine, tmp_path: Path, clean: None
):  # type: ignore[no-untyped-def]
    """A working state, and it must not be an empty map with no reason.

    A deployment whose routers have not set a role lands here. The log
    line says how many were left out, which is the signal to use the
    overrides file rather than to widen the role set.
    """
    settings = _settings(timescale_url, tmp_path)
    with migrated_engine.begin() as connection:
        _add_node(connection, 900088, 33.45, -112.07, role=None)
        _add_node(connection, 900089, 33.46, -112.08, role="CLIENT")

    assert _run(settings, coverage.run_once) is None


# --- a position the broker fuzzed --------------------------------------


def test_a_fuzzed_position_is_never_a_site(
    timescale_url: str, migrated_engine, tmp_path: Path, clean: None
):  # type: ignore[no-untyped-def]
    """The public broker sends 14 bits by default, about 1459 m.

    The terrain under a prediction is 90 m across, so the node could be
    on the far side of a ridge from where the map draws it.
    """
    settings = _settings(timescale_url, tmp_path)
    with migrated_engine.begin() as connection:
        _add_node(connection, 900090, 33.45, -112.07, role="ROUTER", precision_bits=14)

    assert _run(settings, coverage.run_once) is None


def test_the_same_node_at_full_precision_is_a_site(
    timescale_url: str, migrated_engine, tmp_path: Path, clean: None
):  # type: ignore[no-untyped-def]
    """The other half of the pair, so the test above cannot pass for
    the wrong reason."""
    settings = _settings(timescale_url, tmp_path)
    with migrated_engine.begin() as connection:
        _add_node(connection, 900091, 33.45, -112.07, role="ROUTER", precision_bits=32)

    manifest = _run(settings, coverage.run_once)
    assert manifest is not None
    assert manifest.presets[0].site_count == 1


def test_a_node_that_never_said_its_precision_is_a_site(
    timescale_url: str, migrated_engine, tmp_path: Path, clean: None
):  # type: ignore[no-untyped-def]
    """NULL is the common case for a node heard over the radio.

    Ingest writes `precision_bits or None`, so "did not say" and "said
    zero" are the same row. Treating that as coarse would empty the map.
    """
    settings = _settings(timescale_url, tmp_path)
    with migrated_engine.begin() as connection:
        _add_node(connection, 900092, 33.45, -112.07, role="ROUTER", precision_bits=None)

    manifest = _run(settings, coverage.run_once)
    assert manifest is not None
    assert manifest.presets[0].site_count == 1


def test_the_manifest_counts_a_fuzzed_position_apart_from_a_role(
    timescale_url: str, migrated_engine, tmp_path: Path, clean: None
):  # type: ignore[no-untyped-def]
    """Two different reasons to leave a node out, counted separately.

    A deployment has to be able to tell "our routers have no role set"
    from "our routers come through the public broker".
    """
    settings = _settings(timescale_url, tmp_path)
    with migrated_engine.begin() as connection:
        _add_node(connection, 900093, 33.45, -112.07, role="ROUTER")
        _add_node(connection, 900094, 33.46, -112.08, role="ROUTER", precision_bits=12)
        _add_node(connection, 900095, 33.47, -112.09, role=None)

    manifest = _run(settings, coverage.run_once)
    assert manifest is not None
    excluded = manifest.presets[0].excluded_by_role
    assert excluded == {"NULL": 1, "coarse-position": 1}


def test_an_operator_position_brings_a_coarse_router_back(
    timescale_url: str, migrated_engine, tmp_path: Path, clean: None
):  # type: ignore[no-untyped-def]
    """The escape hatch, end to end.

    On the live Arizona mesh 34 of 50 routers report a position the
    broker rounded to between 2.9 and 23 km. Without this they are not
    sites at all, and the map shows a third of the mesh.
    """
    overrides = tmp_path / "nodes.yaml"
    overrides.write_text(
        'nodes:\n  "!000dbba1":\n    latitude: 33.4500\n    longitude: -112.0700\n',
        encoding="utf-8",
    )
    settings = _settings(timescale_url, tmp_path, radio_overrides_path=str(overrides))
    with migrated_engine.begin() as connection:
        _add_node(connection, 900001, 33.45, -112.07, role="ROUTER", precision_bits=13)

    manifest = _run(settings, coverage.run_once)
    assert manifest is not None
    preset = manifest.presets[0]
    assert preset.site_count == 1
    assert "coarse-position" not in preset.excluded_by_role


def test_the_precision_test_can_be_turned_off_for_a_private_broker(
    timescale_url: str, migrated_engine, tmp_path: Path, clean: None
):  # type: ignore[no-untyped-def]
    """A deployment reading its own broker sees full precision."""
    settings = _settings(timescale_url, tmp_path, coverage_min_precision_bits=0)
    with migrated_engine.begin() as connection:
        _add_node(connection, 900002, 33.45, -112.07, role="ROUTER", precision_bits=13)

    manifest = _run(settings, coverage.run_once)
    assert manifest is not None
    assert manifest.presets[0].site_count == 1


# --- precise positions only, with operator positions (#315) -------------
#
# #318 let s.azmsh.dev set COVERAGE_MIN_PRECISION_BITS=13, so routers that
# share a rounded position were predicted from. Logan and Tyler asked for
# that to stop, and Will decided on 2026-10-08 to follow them: every
# published map predicts from precise positions, and an operator places a
# known router in the overrides file.

# Where the broker says the router is, and where it really is: a rounded
# point and the true one, about 1.7 km apart.
_ROUNDED = (33.45, -112.07)
_TRUE = (33.4612, -112.0833)


def _position_file(tmp_path: Path, node_num: int, height: float | None = None) -> Path:
    """Write an overrides file that places one node at `_TRUE`."""
    path = tmp_path / "positions.yaml"
    lines = [
        "nodes:",
        f'  "!{node_num:08x}":',
        f"    latitude: {_TRUE[0]}",
        f"    longitude: {_TRUE[1]}",
    ]
    if height is not None:
        lines.append(f"    antenna_height_m: {height}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_a_rounded_router_is_not_a_site_on_the_setting_318_documented(
    timescale_url: str, migrated_engine, tmp_path: Path, clean: None
):  # type: ignore[no-untyped-def]
    """s.azmsh.dev runs with 13. That no longer reaches the main map."""
    settings = _settings(timescale_url, tmp_path, coverage_min_precision_bits=13)
    with migrated_engine.begin() as connection:
        _add_node(connection, 900301, *_ROUNDED, role="ROUTER", precision_bits=13)
        _add_node(connection, 900302, 33.50, -112.02, role="ROUTER", precision_bits=None)

    manifest = _run(settings, coverage.run_once)
    assert manifest is not None
    preset = manifest.presets[0]
    assert preset.site_count == 1
    assert preset.excluded_by_role == {"coarse-position": 1}
    assert [item["node_id"] for item in manifest.coarse_sites] == [f"!{900301:08x}"]
    assert [item.key for item in manifest.site_sets] == ["infrastructure"]


def test_the_same_router_with_an_operator_position_is_a_site_there(
    timescale_url: str, migrated_engine, tmp_path: Path, clean: None
):  # type: ignore[no-untyped-def]
    """The fix for Towers 2: the operator says where it stands."""
    positions = _position_file(tmp_path, 900303, height=20.0)
    settings = _settings(
        timescale_url,
        tmp_path,
        coverage_min_precision_bits=13,
        radio_overrides_path=str(positions),
    )
    with migrated_engine.begin() as connection:
        _add_node(connection, 900303, *_ROUNDED, role="ROUTER", precision_bits=13)

    manifest = _run(settings, coverage.run_once)
    assert manifest is not None
    preset = manifest.presets[0]
    assert preset.site_count == 1
    assert "coarse-position" not in preset.excluded_by_role
    (site,) = [node for node in preset.nodes if node.get("used")]
    assert site["position_source"] == "operator"
    assert site["position_deviation_m"] is None
    assert site["antenna_height_m"] == 20.0

    # Predicted from the operator's point, not the broker's: the
    # footprint is centred where the file says.
    assert preset.data_bounds is not None
    south, _west, north, _east = preset.data_bounds
    middle = (south + north) / 2.0
    assert abs(middle - _TRUE[0]) < abs(middle - _ROUNDED[0])

    # The position itself is not written into the manifest, which the
    # dashboard serves. Only the fact that an operator gave one.
    root = store.current_root(settings)
    assert root is not None
    written = (root / "manifest.json").read_text(encoding="utf-8")
    assert str(_TRUE[0]) not in written
    assert str(_TRUE[1]) not in written


def test_an_operator_position_does_not_make_a_client_a_site(
    timescale_url: str, migrated_engine, tmp_path: Path, clean: None
):  # type: ignore[no-untyped-def]
    """An override places a node. It does not say what the node is."""
    positions = _position_file(tmp_path, 900304)
    settings = _settings(timescale_url, tmp_path, radio_overrides_path=str(positions))
    with migrated_engine.begin() as connection:
        _add_node(connection, 900304, *_ROUNDED, role="CLIENT", precision_bits=13)

    manifest = _run(settings, coverage.run_once)
    # Nothing to predict from is a working state, and no run is made.
    assert manifest is None or manifest.presets[0].site_count == 0


def test_the_approximate_map_is_its_own_site_set_and_never_public(
    timescale_url: str, migrated_engine, tmp_path: Path, clean: None
):  # type: ignore[no-untyped-def]
    """COVERAGE_INCLUDE_APPROXIMATE adds a map. It replaces nothing."""
    settings = _settings(timescale_url, tmp_path, coverage_include_approximate=True)
    with migrated_engine.begin() as connection:
        _add_node(connection, 900305, *_ROUNDED, role="ROUTER", precision_bits=13)
        _add_node(connection, 900306, 33.50, -112.02, role="ROUTER", precision_bits=None)

    manifest = _run(settings, coverage.run_once)
    assert manifest is not None
    # The top level, which the embed reads, is the precise map.
    assert manifest.presets[0].site_count == 1
    assert manifest.is_diagnostic is False
    by_key = {item.key: item for item in manifest.site_sets}
    assert list(by_key) == ["infrastructure", "infrastructure_approximate"]
    assert by_key["infrastructure"].approximate is False
    assert by_key["infrastructure"].site_precision == "precise"
    approximate = by_key["infrastructure_approximate"]
    assert approximate.approximate is True
    assert approximate.site_precision == "approximate"
    assert approximate.presets[0].site_count == 2
    rounded = [node for node in approximate.presets[0].nodes if node["node_id"] == f"!{900305:08x}"]
    assert rounded[0]["position_deviation_m"] == 2900.0

    root = store.current_root(settings)
    assert root is not None
    tile = next(root.glob("LongFast/infrastructure_approximate/usable/*/*/*.png"))
    zoom, x, y = tile.parts[-3], tile.parts[-2], tile.stem

    # The dashboard has it, by the name the run wrote.
    dashboard = TestClient(create_app(settings))
    served = dashboard.get(
        f"/api/coverage/tiles/{manifest.stamp}/LongFast/infrastructure_approximate/usable/"
        f"{zoom}/{x}/{y}.png"
    )
    assert served.status_code == 200
    assert served.content == tile.read_bytes()

    # The public page has the precise map and nothing else.
    public = TestClient(create_app(settings.model_copy(update={"embed_enabled": True})))
    summary = public.get("/api/embed/coverage").json()
    assert summary["available"] is True
    assert [item["node_count"] for item in summary["presets"]] == [1]
    assert "site_sets" not in summary


def test_the_calibration_fit_leaves_out_a_rounded_peer_on_the_setting_318_documented(
    timescale_url: str, migrated_engine, tmp_path: Path, clean: None
):  # type: ignore[no-untyped-def]
    """A fuzzed peer turns silence into false evidence. 13 is read as 16."""
    settings = _settings(timescale_url, tmp_path, coverage_min_precision_bits=13)
    with migrated_engine.begin() as connection:
        _add_node(connection, 900307, 33.45, -112.07, role="ROUTER", precision_bits=13)
        _add_node(connection, 900308, 33.50, -112.02, role="ROUTER", precision_bits=None)

    async def peers(session, given: Settings):  # type: ignore[no-untyped-def]
        return await calibrate.read_peers(
            session, given, load_overrides(given.radio_overrides_path)
        )

    found = _run(settings, peers)
    assert 900307 not in found
    assert 900308 in found
