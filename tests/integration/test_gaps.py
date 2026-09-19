"""The coverage gaps job, against a real database.

The unit tests pin the rules with rows built by hand. This runs the
queries the way the jobs container does: real schema, real roles, real
hypertables, and the API that serves what the job wrote.

Every test here asserts **behaviour**, not a row count that a change of
seed would move.
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
from sonoran.coverage import store as coverage_store
from sonoran.db.session import make_engine, make_session_factory
from sonoran.gaps import store
from sonoran.jobs import coverage, gaps

# A node number range of this file's own, so two test files cannot
# collide in a shared database.
BASE = 930000


def _jobs_url(timescale_url: str) -> str:
    """Make an async URL for the migration-created jobs role."""
    _, address = timescale_url.split("@", maxsplit=1)
    return f"postgresql+asyncpg://azmsh_jobs:change_me@{address}"


def _settings(timescale_url: str, tmp_path: Path, **extra: object) -> Settings:
    extra.setdefault("gaps_min_packets", 5)
    extra.setdefault("gaps_min_active_hours", 3)
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


@pytest.fixture
def clean(migrated_engine) -> Iterator[None]:  # type: ignore[no-untyped-def]
    """Leave the tables as they were found.

    Both before and after. A previous file's rows in this range would
    otherwise decide what these tests measure.
    """
    _wipe(migrated_engine)
    yield
    _wipe(migrated_engine)


def _wipe(migrated_engine) -> None:  # type: ignore[no-untyped-def]
    with migrated_engine.begin() as connection:
        for table, column in (
            ("packet_seen", "from_node_num"),
            ("packet", "from_node_num"),
            ("packet_key", "from_node_num"),
            ("mesh_packet_metrics", "from_node_num"),
            ("neighbor_metrics", "node_num"),
            ("position_metrics", "node_num"),
            ("traceroute", "from_node_num"),
            ("node", "node_num"),
        ):
            connection.execute(text(f"DELETE FROM {table} WHERE {column} >= {BASE}"))


def _add_node(
    connection,  # type: ignore[no-untyped-def]
    node_num: int,
    latitude: float | None = 33.45,
    longitude: float | None = -112.07,
    channel: str | None = "LongFast",
    *,
    role: str | None,
    precision_bits: int | None = None,
) -> None:
    """Insert one node the way ingest would have.

    `role` has no default, for the reason `test_coverage_job.py` gives:
    a default once hid every test asserting about routers while its
    author believed it asserted about nodes. See `AGENTS.md` 9.22.
    """
    heard = datetime.now(UTC) - timedelta(hours=1)
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


def _packet(
    connection,  # type: ignore[no-untyped-def]
    sender: int,
    packet_id: int,
    gateways: list[tuple[int, int | None, float | None]],
    *,
    channel: str = "LongFast",
    hop_start: int = 3,
    seen_at: datetime | None = None,
    rx_time: int | None = None,
    via_mqtt: bool | None = None,
) -> None:
    """Insert one packet and the uploads that carried it.

    `gateways` is a list of (gateway, hop_limit, rx_snr). A hop_limit
    equal to `hop_start` is a direct observation; anything lower was
    relayed. A gateway equal to the sender is a self upload.
    """
    when = seen_at or datetime.now(UTC)
    connection.execute(
        text(
            "INSERT INTO packet (from_node_num, packet_id, portnum, channel, hop_start, "
            "rx_time, first_seen_at) VALUES (:f, :p, 1, :ch, :hs, :rx, :t) "
            "ON CONFLICT DO NOTHING"
        ),
        {"f": sender, "p": packet_id, "ch": channel, "hs": hop_start, "rx": rx_time, "t": when},
    )
    for gateway, hop_limit, snr in gateways:
        connection.execute(
            text(
                "INSERT INTO packet_seen (from_node_num, packet_id, gateway_node_num, "
                "mqtt_topic, channel, hop_limit, rx_snr, seen_at) "
                "VALUES (:f, :p, :g, 'msh/US/AZ/t', :ch, :hl, :snr, :t) "
                "ON CONFLICT DO NOTHING"
            ),
            {
                "f": sender,
                "p": packet_id,
                "g": gateway,
                "ch": channel,
                "hl": hop_start if hop_limit is None else hop_limit,
                "snr": snr,
                "t": when,
            },
        )
    if via_mqtt is not None:
        connection.execute(
            text(
                "INSERT INTO mesh_packet_metrics (from_node_num, to_node_num, packet_id, "
                "via_mqtt, time) VALUES (:f, 0, :p, :v, :t)"
            ),
            {"f": sender, "p": packet_id, "v": via_mqtt, "t": when},
        )


def _busy(
    connection,  # type: ignore[no-untyped-def]
    sender: int,
    first_id: int,
    gateways_for,  # type: ignore[no-untyped-def]
    *,
    channel: str = "LongFast",
    hours: int = 8,
    via_mqtt: bool | None = None,
) -> None:
    """Insert one packet an hour, so a node clears the evidence floors."""
    now = datetime.now(UTC)
    for hour in range(hours):
        _packet(
            connection,
            sender,
            first_id + hour,
            gateways_for(hour),
            channel=channel,
            seen_at=now - timedelta(hours=hour, minutes=5),
            via_mqtt=via_mqtt,
        )


def _run(settings: Settings, job):  # type: ignore[no-untyped-def]
    """Run one job against the database and return what it made."""

    async def go():  # type: ignore[no-untyped-def]
        engine = make_engine(settings.database_url_jobs)
        factory = make_session_factory(engine)
        try:
            async with factory() as session:
                return await job(session, settings)
        finally:
            await engine.dispose()

    return asyncio.run(go())


def _rows(settings: Settings, preset: str = "LongFast") -> dict[str, dict]:
    """Return the written assessment, keyed by node ID."""
    document = store.read_preset(settings, preset)
    assert document is not None, "the job wrote no assessment"
    listed = document["nodes"]
    assert isinstance(listed, list)
    return {row["node_id"]: row for row in listed}


def _ident(node_num: int) -> str:
    return f"!{node_num:08x}"


# --- the two routes a packet takes into the database -------------------


def test_the_two_routes_a_packet_takes_are_told_apart(
    timescale_url: str, migrated_engine, tmp_path: Path, clean: None
):  # type: ignore[no-untyped-def]
    """The load-bearing fact, both ways round.

    Node A is an MQTT gateway and every upload of its traffic is its
    own. Nothing on the air heard it.

    Node B's packets arrive from a different gateway. Some radio heard
    it, which is positive evidence that costs nothing and claims no
    link.
    """
    a, b, gateway = BASE + 1, BASE + 2, BASE + 9
    settings = _settings(timescale_url, tmp_path)
    with migrated_engine.begin() as connection:
        _add_node(connection, a, role="CLIENT")
        _add_node(connection, b, role="CLIENT")
        _add_node(connection, gateway, role="ROUTER")
        # A uploads its own traffic and nothing else ever carries it.
        _busy(connection, a, 1000, lambda hour: [(a, 3, 6.0)])
        # B is carried by a different gateway, with a hop used.
        _busy(connection, b, 2000, lambda hour: [(gateway, 2, 4.0)])

    _run(settings, gaps.run_once)
    rows = _rows(settings)

    first = rows[_ident(a)]
    assert first["signals"]["radio_isolated"]["state"] == "bad"
    assert first["signals"]["radio_isolated"]["reason"] == "no_gateway_heard_it"
    assert first["rf_packets"] == 0
    assert first["is_mqtt_gateway"] is True

    second = rows[_ident(b)]
    assert second["signals"]["radio_isolated"]["state"] == "ok"
    assert second["rf_packets"] > 0


def test_a_relayed_observation_is_evidence_and_carries_no_signal_reading(
    timescale_url: str, migrated_engine, tmp_path: Path, clean: None
):  # type: ignore[no-untyped-def]
    """Rung 4 proves a radio heard it. It proves nothing else.

    The reading on a relayed observation belongs to the last hop into
    the gateway, not to the link from the sender. It must never become a
    margin, and no link may appear anywhere in the assessment. See
    `AGENTS.md` 9.5 and 9.20.
    """
    node, gateway = BASE + 11, BASE + 19
    settings = _settings(timescale_url, tmp_path)
    with migrated_engine.begin() as connection:
        _add_node(connection, node, role="CLIENT")
        _add_node(connection, gateway, role="ROUTER")
        # Every upload used a hop, and each carries a strong reading.
        _busy(connection, node, 3000, lambda hour: [(gateway, 1, 11.5)])

    _run(settings, gaps.run_once)
    row = _rows(settings)[_ident(node)]

    assert row["signals"]["radio_isolated"]["state"] == "ok"
    # No direct observer, so no measured SNR and no margin.
    assert row["direct_gateways"] == 0
    assert row["signals"]["weak_best_link"]["state"] == "unknown"
    assert row["signals"]["weak_best_link"]["reason"] == "no_measured_snr"
    assert row["signals"]["sole_observer"]["state"] == "unknown"
    # And that strong reading never reached the evidence.
    assert "11.5" not in json.dumps(row)


def test_a_self_upload_is_never_a_direct_observation(
    timescale_url: str, migrated_engine, tmp_path: Path, clean: None
):  # type: ignore[no-untyped-def]
    """A node does not hear itself over the radio.

    A self upload always has the hop limits equal, so the hop rule alone
    calls it direct and then offers the node's own voice as a link to
    itself. `AGENTS.md` 9.5.1 is this exact trap.
    """
    node = BASE + 21
    settings = _settings(timescale_url, tmp_path)
    with migrated_engine.begin() as connection:
        _add_node(connection, node, role="CLIENT")
        _busy(connection, node, 4000, lambda hour: [(node, 3, 9.0)])

    _run(settings, gaps.run_once)
    row = _rows(settings)[_ident(node)]

    assert row["direct_gateways"] == 0, "a self upload is not a direct observation"
    assert row["signals"]["weak_best_link"]["state"] == "unknown"
    assert "9.0" not in json.dumps(row["signals"]["weak_best_link"])


def test_one_packet_from_many_gateways_counts_once(
    timescale_url: str, migrated_engine, tmp_path: Path, clean: None
):  # type: ignore[no-untyped-def]
    """Distinct packets, never rows, and gateways, never uploads.

    The duplicate `packet` row is what the pre-0009 history holds:
    about 8,200 of them survive. See `docs/ISSUES.md` 1.1.
    """
    node = BASE + 31
    settings = _settings(timescale_url, tmp_path, gaps_min_packets=1, gaps_min_active_hours=1)
    now = datetime.now(UTC)
    with migrated_engine.begin() as connection:
        _add_node(connection, node, role="CLIENT")
        gateways = [(BASE + 100 + index, 3, 5.0) for index in range(15)]
        _packet(connection, node, 5000, gateways, seen_at=now - timedelta(minutes=5))
        # The same packet, stored a second time, as the old ingest did.
        connection.execute(
            text(
                "INSERT INTO packet (from_node_num, packet_id, portnum, channel, hop_start, "
                "first_seen_at) VALUES (:f, 5000, 1, 'LongFast', 3, :t)"
            ),
            {"f": node, "t": now - timedelta(minutes=4)},
        )
        # And one gateway uploads it again a moment later.
        connection.execute(
            text(
                "INSERT INTO packet_seen (from_node_num, packet_id, gateway_node_num, "
                "mqtt_topic, channel, hop_limit, rx_snr, seen_at) "
                "VALUES (:f, 5000, :g, 'msh/US/AZ/t', 'LongFast', 3, 5.0, :t)"
            ),
            {"f": node, "g": BASE + 100, "t": now - timedelta(minutes=3)},
        )

    _run(settings, gaps.run_once)
    row = _rows(settings)[_ident(node)]

    assert row["packets"] == 1, "one packet, however many rows carry it"
    assert row["direct_gateways"] == 15, "fifteen gateways, however many uploads"


# --- the asymmetry -----------------------------------------------------


def test_a_node_that_hears_the_mesh_and_is_not_heard_back(
    timescale_url: str, migrated_engine, tmp_path: Path, clean: None
):  # type: ignore[no-untyped-def]
    """The strongest single finding this feature can produce.

    Its receiver demonstrably works and no gateway hears it. The API
    must name both halves of that claim, because either half alone is a
    different and weaker statement.
    """
    node = BASE + 41
    settings = _settings(timescale_url, tmp_path)
    now = datetime.now(UTC)
    with migrated_engine.begin() as connection:
        _add_node(connection, node, role="CLIENT")
        _busy(connection, node, 6000, lambda hour: [(node, 3, 6.0)])
        # It publishes neighbour reports with a real reading, which
        # proves its own receiver works.
        for index in range(3):
            connection.execute(
                text(
                    "INSERT INTO neighbor_metrics (node_num, neighbor_node_num, channel, "
                    "snr, time) VALUES (:n, :o, 'LongFast', :snr, :t)"
                ),
                {
                    "n": node,
                    "o": BASE + 200 + index,
                    "snr": -3.5,
                    "t": now - timedelta(hours=index),
                },
            )

    _run(settings, gaps.run_once)
    row = _rows(settings)[_ident(node)]

    found = row["signals"]["hears_but_is_not_heard"]
    assert found["state"] == "bad"
    assert "receiver works" in found["sentence"]
    assert "transmit side" in found["sentence"]
    # It is the top of the list, because the ranking puts it there.
    listed = store.read_preset(settings, "LongFast")
    assert listed is not None
    assert listed["nodes"][0]["node_id"] == _ident(node)


def test_a_neighbour_report_naming_a_node_proves_a_radio_heard_it(
    timescale_url: str, migrated_engine, tmp_path: Path, clean: None
):  # type: ignore[no-untyped-def]
    """Being named as somebody's neighbour is rung 1 evidence."""
    node, reporter = BASE + 51, BASE + 59
    settings = _settings(timescale_url, tmp_path)
    now = datetime.now(UTC)
    with migrated_engine.begin() as connection:
        _add_node(connection, node, role="CLIENT")
        _add_node(connection, reporter, role="ROUTER")
        _busy(connection, node, 7000, lambda hour: [(node, 3, 6.0)])
        connection.execute(
            text(
                "INSERT INTO neighbor_metrics (node_num, neighbor_node_num, channel, snr, time) "
                "VALUES (:r, :n, 'LongFast', -8.0, :t)"
            ),
            {"r": reporter, "n": node, "t": now - timedelta(hours=1)},
        )

    _run(settings, gaps.run_once)
    row = _rows(settings)[_ident(node)]

    # Its uploads were all its own, but a radio demonstrably heard it.
    assert row["signals"]["radio_isolated"]["state"] == "ok"
    # And that measured reading is a real margin.
    assert row["signals"]["weak_best_link"]["state"] in {"bad", "ok"}
    assert row["signals"]["weak_best_link"]["value"] is not None


# --- the open hole -----------------------------------------------------


def test_a_packet_whose_first_upload_came_from_mqtt_is_neither(
    timescale_url: str, migrated_engine, tmp_path: Path, clean: None
):  # type: ignore[no-untyped-def]
    """An MQTT rebroadcast is no evidence either way.

    A gateway can put MQTT traffic back on the air. If another gateway
    then heard that copy, the upload would evidence a radio path the
    node never used. Until the firmware's own words can be quoted and
    the hole measured, such a packet counts for nothing and is reported
    as ambiguous.
    """
    node, gateway = BASE + 61, BASE + 69
    settings = _settings(timescale_url, tmp_path)
    with migrated_engine.begin() as connection:
        _add_node(connection, node, role="CLIENT")
        _add_node(connection, gateway, role="ROUTER")
        # It is a gateway of its own, and every packet that another
        # gateway carried had been taken from MQTT first.
        _busy(
            connection, node, 8000, lambda hour: [(node, 3, 6.0), (gateway, 2, 4.0)], via_mqtt=True
        )

    _run(settings, gaps.run_once)
    row = _rows(settings)[_ident(node)]

    assert row["rf_packets"] == 0, "an MQTT copy is not radio evidence"
    assert row["ambiguous_packets"] > 0
    found = row["signals"]["radio_isolated"]
    assert found["state"] == "unknown", "ambiguous is not a fault"
    assert found["reason"] == "every_packet_ambiguous"


# --- the clock ---------------------------------------------------------


def test_a_gateway_clock_that_is_a_day_ahead_moves_nothing(
    timescale_url: str, migrated_engine, tmp_path: Path, clean: None
):  # type: ignore[no-untyped-def]
    """Every bucket lands on our clock, never on the node's.

    A node clock has been seen nearly 28 hours ahead. A window that read
    `packet.rx_time` would report hours that have not happened and grow
    `active_hours` out of nothing. See `AGENTS.md` 9.3 and 9.4, and
    `docs/ISSUES.md` 1.5.
    """
    node, gateway = BASE + 71, BASE + 79
    settings = _settings(timescale_url, tmp_path, gaps_min_active_hours=3)
    now = datetime.now(UTC)
    ahead = int((now + timedelta(hours=28)).timestamp())
    with migrated_engine.begin() as connection:
        _add_node(connection, node, role="CLIENT")
        _add_node(connection, gateway, role="ROUTER")
        for hour in range(6):
            _packet(
                connection,
                node,
                9000 + hour,
                [(gateway, 2, 3.0)],
                seen_at=now - timedelta(hours=hour, minutes=5),
                rx_time=ahead,
            )

    _run(settings, gaps.run_once)
    row = _rows(settings)[_ident(node)]

    # Six packets, one an hour, over six of our hours. Not thirty-four.
    assert row["packets"] == 6
    assert row["active_hours"] == 6

    document = store.read_preset(settings, "LongFast")
    assert document is not None
    assert row["active_hours"] <= document["window_hours"]


# --- one preset at a time ----------------------------------------------


def test_two_presets_get_two_assessments_that_borrow_nothing(
    timescale_url: str, migrated_engine, tmp_path: Path, clean: None
):  # type: ignore[no-untyped-def]
    """A node on Long fast cannot hear a node on Medium fast.

    The same node, active on both, gets two independent answers. There
    is no merged row anywhere, and neither answer borrows a count from
    the other. See `AGENTS.md` 9.7.
    """
    node, gateway = BASE + 81, BASE + 89
    settings = _settings(timescale_url, tmp_path)
    with migrated_engine.begin() as connection:
        _add_node(connection, node, role="CLIENT")
        _add_node(connection, gateway, role="ROUTER")
        # On Long fast a radio hears it. On Medium slow nothing does.
        _busy(connection, node, 10000, lambda hour: [(gateway, 2, 4.0)], channel="LongFast")
        _busy(connection, node, 11000, lambda hour: [(node, 3, 6.0)], channel="MediumSlow")

    written = _run(settings, gaps.run_once)
    assert sorted(written) == ["LongFast", "MediumSlow"]

    good = _rows(settings, "LongFast")[_ident(node)]
    bad = _rows(settings, "MediumSlow")[_ident(node)]

    assert good["signals"]["radio_isolated"]["state"] == "ok"
    assert bad["signals"]["radio_isolated"]["state"] == "bad"
    # Neither borrowed the other's evidence.
    assert good["rf_packets"] > 0
    assert bad["rf_packets"] == 0
    assert good["preset"] == "LongFast"
    assert bad["preset"] == "MediumSlow"

    # And there is no file that merges them.
    assert store.read_preset(settings, "All") is None
    index = store.read_index(settings)
    assert index is not None
    assert sorted(item["preset"] for item in index["presets"]) == ["LongFast", "MediumSlow"]


def test_a_channel_that_names_no_preset_is_left_out(
    timescale_url: str, migrated_engine, tmp_path: Path, clean: None
):  # type: ignore[no-untyped-def]
    """Weather rides on top of a preset and does not name one.

    Asserted on this node and not on the whole database. Other files in
    this suite leave traffic of their own behind, so "no preset was
    written at all" is not a claim this test can make. What it can claim
    is that a node whose only traffic is on a channel naming no preset
    appears in no assessment: not under a guessed preset, and not under
    a merged one.
    """
    node = BASE + 91
    settings = _settings(timescale_url, tmp_path)
    with migrated_engine.begin() as connection:
        _add_node(connection, node, channel="AZ-Weather", role="CLIENT")
        _busy(connection, node, 12000, lambda hour: [(node, 3, 6.0)], channel="AZ-Weather")

    written = _run(settings, gaps.run_once)
    assert "AZWeather" not in written
    for preset in written:
        assert _ident(node) not in _rows(settings, preset), (
            f"a channel that names no preset was assessed as {preset}"
        )


# --- the artefact and the API -----------------------------------------


def test_the_api_reads_the_artefact_and_computes_nothing(
    timescale_url: str, migrated_engine, tmp_path: Path, clean: None
):  # type: ignore[no-untyped-def]
    """Delete the file and the endpoint says so, rather than recomputing.

    This is the whole point of the artefact. A request that ran these
    queries would be heavier than the endpoint `docs/ISSUES.md` 2.9 is
    already an open warning about.
    """
    node, gateway = BASE + 101, BASE + 109
    settings = _settings(timescale_url, tmp_path)
    with migrated_engine.begin() as connection:
        _add_node(connection, node, role="CLIENT")
        _add_node(connection, gateway, role="ROUTER")
        _busy(connection, node, 13000, lambda hour: [(node, 3, 6.0)])

    _run(settings, gaps.run_once)

    with TestClient(create_app(settings)) as client:
        body = client.get("/api/gaps?channel=LongFast").json()
        assert body["available"] is True
        assert body["preset"] == "LongFast"
        assert body["gateways_active"] >= 1
        # The three counts are all present for every signal.
        for name, counts in body["signals"].items():
            assert set(counts) == {"bad", "ok", "unknown"}, name
        assert "nodes" not in body, "the summary carries no node rows"

        listing = client.get("/api/gaps/nodes?channel=LongFast").json()
        assert listing["available"] is True
        assert any(row["node_id"] == _ident(node) for row in listing["nodes"])

    # Now take the artefact away.
    store.clear(settings)
    with TestClient(create_app(settings)) as client:
        body = client.get("/api/gaps?channel=LongFast").json()
        assert body["available"] is False
        assert body["reason"] == "no_assessment"
        assert body["nodes"] == []


def test_the_filters_select_and_never_recompute(
    timescale_url: str, migrated_engine, tmp_path: Path, clean: None
):  # type: ignore[no-untyped-def]
    """`signal` and `state` narrow the written list, and nothing else."""
    node, gateway = BASE + 111, BASE + 119
    settings = _settings(timescale_url, tmp_path)
    with migrated_engine.begin() as connection:
        _add_node(connection, node, role="CLIENT")
        _add_node(connection, gateway, role="ROUTER")
        _busy(connection, node, 14000, lambda hour: [(node, 3, 6.0)])

    _run(settings, gaps.run_once)

    with TestClient(create_app(settings)) as client:
        base = "/api/gaps/nodes?channel=LongFast"
        every = client.get(base).json()["nodes"]
        bad = client.get(f"{base}&signal=radio_isolated&state=bad").json()["nodes"]
        assert bad, "the isolated node must be selectable"
        assert len(bad) <= len(every)
        for row in bad:
            assert row["signals"]["radio_isolated"]["state"] == "bad"

        # An unknown signal name is refused, not silently ignored.
        refused = client.get(f"{base}&signal=made_up").json()
        assert refused["available"] is False
        assert refused["reason"] == "not_a_signal"
        refused = client.get(f"{base}&state=sideways").json()
        assert refused["available"] is False
        assert refused["reason"] == "not_a_state"


def test_the_unknown_bucket_is_counted_and_not_folded_into_healthy(
    timescale_url: str, migrated_engine, tmp_path: Path, clean: None
):  # type: ignore[no-untyped-def]
    """A node we cannot measure is not a node that is fine.

    This node sent three packets. Every floor rejects it, so every
    signal reads `unknown` and it lands in its own count.
    """
    node, gateway = BASE + 121, BASE + 129
    settings = _settings(timescale_url, tmp_path, gaps_min_packets=20, gaps_min_active_hours=12)
    now = datetime.now(UTC)
    with migrated_engine.begin() as connection:
        _add_node(connection, node, role="CLIENT")
        _add_node(connection, gateway, role="ROUTER")
        for index in range(3):
            _packet(
                connection,
                node,
                15000 + index,
                [(gateway, 2, 4.0)],
                seen_at=now - timedelta(hours=index, minutes=10),
            )

    _run(settings, gaps.run_once)
    document = store.read_preset(settings, "LongFast")
    assert document is not None
    row = _rows(settings)[_ident(node)]

    assert row["bad_count"] == 0
    assert row["unknown_count"] > 0
    assert row["worst_state"] == "unknown", "unmeasured is not ok"
    assert document["not_enough_evidence_count"] >= 1
    # And the three counts are reported for every signal, always.
    for name, counts in document["signals"].items():
        assert set(counts) == {"bad", "ok", "unknown"}, name


def test_a_coarse_position_is_listed_and_never_placed(
    timescale_url: str, migrated_engine, tmp_path: Path, clean: None
):  # type: ignore[no-untyped-def]
    """Thirteen bits is 2.9 km. It is named, not guessed at."""
    node, gateway = BASE + 131, BASE + 139
    settings = _settings(timescale_url, tmp_path)
    with migrated_engine.begin() as connection:
        _add_node(connection, node, role="CLIENT", precision_bits=13)
        _add_node(connection, gateway, role="ROUTER")
        _busy(connection, node, 16000, lambda hour: [(gateway, 2, 4.0)])

    _run(settings, gaps.run_once)
    row = _rows(settings)[_ident(node)]

    assert row["position_confidence"] == "coarse"
    assert row["position_deviation_m"] == 2900.0
    found = row["signals"]["outside_predicted_usable"]
    assert found["state"] == "unknown"
    assert found["reason"] in {"position_too_coarse", "no_coverage_run"}


# --- the coverage artefact ---------------------------------------------


def test_the_coverage_run_writes_the_level_at_each_node(
    timescale_url: str, migrated_engine, tmp_path: Path, clean: None
):  # type: ignore[no-untyped-def]
    """A run keeps no level grid, so it must write the numbers out.

    The sample is taken while the grids are still in memory, after the
    receiver is charged, so each number is the number the map draws.
    """
    site, near, far = BASE + 141, BASE + 142, BASE + 143
    settings = _settings(timescale_url, tmp_path)
    with migrated_engine.begin() as connection:
        _add_node(connection, site, 33.45, -112.07, role="ROUTER")
        # A client beside the site, well inside the region.
        _add_node(connection, near, 33.46, -112.08, role="CLIENT")
        # And one outside the terrain region entirely.
        _add_node(connection, far, 45.00, -100.00, role="CLIENT")

    manifest = _run(settings, coverage.run_once)
    assert manifest is not None

    document = coverage_store.read_node_levels(settings)
    assert document is not None
    assert document["stamp"] == manifest.stamp

    for_preset = document["presets"]["LongFast"]
    levels = for_preset["site_sets"]["infrastructure"]

    # `threshold_level` travels with it, so a reader needs no preset
    # table to decide what counts as usable.
    from sonoran.coverage.grid import to_level

    assert for_preset["threshold_level"] == to_level(-139.0)

    assert str(near) in levels, "a node inside the region must be sampled"
    assert set(levels[str(near)]) == {"usable", "downlink", "uplink"}
    assert 0 <= levels[str(near)]["usable"] <= 255

    # A node outside the region grid is ABSENT, not zero. Zero would
    # say the run looked there and found nothing.
    assert str(far) not in levels

    # And it published with the run, in one step.
    root = coverage_store.current_root(settings)
    assert root is not None
    assert (root / coverage_store.NODE_LEVELS_NAME).is_file()


def test_the_prediction_signal_lights_up_once_a_run_is_published(
    timescale_url: str, migrated_engine, tmp_path: Path, clean: None
):  # type: ignore[no-untyped-def]
    """Without a run it is `unknown`. With one it is an answer.

    `unknown` before the first coverage run is the honest state, and it
    is not the same as "outside".
    """
    site, node = BASE + 151, BASE + 152
    settings = _settings(timescale_url, tmp_path)
    with migrated_engine.begin() as connection:
        _add_node(connection, site, 33.45, -112.07, role="ROUTER")
        _add_node(connection, node, 33.46, -112.08, role="CLIENT")
        _busy(connection, node, 17000, lambda hour: [(site, 2, 4.0)])

    _run(settings, gaps.run_once)
    before = _rows(settings)[_ident(node)]["signals"]["outside_predicted_usable"]
    assert before["state"] == "unknown"
    assert before["reason"] == "no_coverage_run"

    _run(settings, coverage.run_once)
    _run(settings, gaps.run_once)
    after = _rows(settings)[_ident(node)]["signals"]["outside_predicted_usable"]
    assert after["state"] in {"bad", "ok"}
    assert after["reason"] in {"outside_usable", "inside_usable"}
    assert after["evidence"]["stamp"] is not None


def test_a_diagnostic_run_never_answers_the_prediction_signal(
    timescale_url: str, migrated_engine, tmp_path: Path, clean: None
):  # type: ignore[no-untyped-def]
    """A diagnostic predicts from nodes that move.

    `COVERAGE_SITE_ROLES=ALL` is what it is for, and it must not become
    a claim about where the mesh reaches. See `AGENTS.md` 9.25.
    """
    site, node = BASE + 161, BASE + 162
    settings = _settings(timescale_url, tmp_path, coverage_site_roles="ALL")
    with migrated_engine.begin() as connection:
        _add_node(connection, site, 33.45, -112.07, role="ROUTER")
        _add_node(connection, node, 33.46, -112.08, role="CLIENT")
        _busy(connection, node, 18000, lambda hour: [(site, 2, 4.0)])

    manifest = _run(settings, coverage.run_once)
    assert manifest is not None
    assert manifest.is_diagnostic is True

    _run(settings, gaps.run_once)
    found = _rows(settings)[_ident(node)]["signals"]["outside_predicted_usable"]
    assert found["state"] == "unknown"
    assert found["reason"] == "diagnostic_run"


# --- states a new deployment starts in ---------------------------------


def test_a_deployment_with_no_traffic_of_its_own_is_a_working_state(
    timescale_url: str, migrated_engine, tmp_path: Path, clean: None
):  # type: ignore[no-untyped-def]
    """No traffic is a working state and must not raise.

    This file's own rows are gone, so nothing here can be assessed. The
    job must still finish, still write an index, and still leave the
    endpoint with a working answer rather than an error. Other files in
    this suite may have left traffic behind, so the assertion is that
    none of THIS file's nodes appear anywhere.
    """
    settings = _settings(timescale_url, tmp_path)
    written = _run(settings, gaps.run_once)

    index = store.read_index(settings)
    assert index is not None
    assert [item["preset"] for item in index["presets"]] == written

    for preset in written:
        for node_id in _rows(settings, preset):
            assert int(node_id.lstrip("!"), 16) < BASE

    # And the endpoint answers, whatever it found.
    with TestClient(create_app(settings)) as client:
        body = client.get("/api/gaps").json()
        assert body["available"] is (len(written) > 0)


def test_an_empty_cache_serves_a_working_answer(
    timescale_url: str, migrated_engine, tmp_path: Path
):  # type: ignore[no-untyped-def]
    """A deployment where the job has never run says so, and does not fail."""
    settings = _settings(timescale_url, tmp_path)
    with TestClient(create_app(settings)) as client:
        body = client.get("/api/gaps").json()
        assert body["available"] is False
        assert body["reason"] == "no_assessment"
        assert body["presets"] == []


def test_the_job_is_safe_to_run_twice(
    timescale_url: str, migrated_engine, tmp_path: Path, clean: None
):  # type: ignore[no-untyped-def]
    """It rewrites its files and never appends to them."""
    node, gateway = BASE + 171, BASE + 179
    settings = _settings(timescale_url, tmp_path)
    with migrated_engine.begin() as connection:
        _add_node(connection, node, role="CLIENT")
        _add_node(connection, gateway, role="ROUTER")
        _busy(connection, node, 19000, lambda hour: [(gateway, 2, 4.0)])

    _run(settings, gaps.run_once)
    first = _rows(settings)
    _run(settings, gaps.run_once)
    second = _rows(settings)
    assert set(first) == set(second)
    assert len(second) == len(first)
