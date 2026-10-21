"""The stored views answer exactly what the live computation answers (#371).

Each view is read twice through the API: once before the jobs service has
built anything, when the API computes it live, and once after a real run
of `sonoran.jobs.read_models` as the `azmsh_jobs` role, when the API reads
the stored build. The two answers must be the same, apart from when they
were measured. Running the job as its own role also proves its grants.
"""

import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from sonoran.api import cache
from sonoran.api.app import create_app
from sonoran.config import Settings
from sonoran.db.session import make_engine, make_session_factory
from sonoran.jobs import read_models as job
from tests.integration.conftest import role_url
from tests.integration.test_gaps import _packet

# Four nodes on ShortSlow, about 10 km apart, with exact positions. A
# preset few tests use: `test_api.py` leaves some ShortSlow links, but
# stamped "now", well inside every window, so both reads see them alike.
# A busy preset could hold another test's row near a window's edge.
NODES = {
    0x0EA0_0001: (33.40, -112.00),
    0x0EA0_0002: (33.49, -112.00),
    0x0EA0_0003: (33.58, -112.00),
    0x0EA0_0004: (33.67, -112.00),
}
CHANNEL = "ShortSlow"
READ_MODEL_TABLES = ("link_evidence_run", "broadcast_run", "channel_nodes_run")


def _wipe_read_models(engine: Any) -> None:
    with engine.begin() as connection:
        for table in READ_MODEL_TABLES:
            connection.execute(text(f"DELETE FROM {table}"))


@pytest.fixture
def mesh(migrated_engine: Any) -> Iterator[None]:
    """Links measured both ways on ShortSlow, traceroutes, and broadcasts."""
    now = datetime.now(UTC)
    nums = list(NODES)

    def wipe() -> None:
        with migrated_engine.begin() as connection:
            for table, column in (
                ("neighbor_metrics", "node_num"),
                ("traceroute", "from_node_num"),
                ("packet_seen", "from_node_num"),
                ("packet", "from_node_num"),
                ("node", "node_num"),
            ):
                connection.execute(
                    text(f"DELETE FROM {table} WHERE {column} = ANY(:n)"), {"n": nums}
                )
        _wipe_read_models(migrated_engine)

    wipe()
    with migrated_engine.begin() as connection:
        for node, (lat, lon) in NODES.items():
            connection.execute(
                text(
                    "INSERT INTO node (node_num, node_id, short_name, first_seen, updated_at, "
                    "last_heard, last_lat, last_lon, last_position_precision_bits) "
                    "VALUES (:n, :nid, :sn, :now, :now, :now, :lat, :lon, 32)"
                ),
                {
                    "n": node,
                    "nid": f"!{node:08x}",
                    "sn": f"R{node & 0xF}",
                    "now": now,
                    "lat": lat,
                    "lon": lon,
                },
            )
        # Each neighbouring pair hears the other 6 times each way, SNR 9.5 and 6.
        for first, second in pairwise(nums):
            for k in range(6):
                for reporter, heard, snr in ((first, second, 9.5), (second, first, 6.0)):
                    connection.execute(
                        text(
                            "INSERT INTO neighbor_metrics (node_num, neighbor_node_num, channel, "
                            "snr, time) VALUES (:n, :o, :c, :s, :t)"
                        ),
                        {
                            "n": reporter,
                            "o": heard,
                            "c": CHANNEL,
                            "s": snr + k / 4,
                            "t": now - timedelta(hours=2, minutes=k),
                        },
                    )
        # One answered traceroute across the whole line.
        connection.execute(
            text(
                "INSERT INTO traceroute (from_node_num, to_node_num, channel, packet_id, "
                "request_id, route, snr_towards, seen_at) VALUES (:a, :z, :c, 950001, 950000, "
                "CAST(:route AS jsonb), CAST('[30, 24, 18]' AS jsonb), :t)"
            ),
            {
                "a": nums[-1],
                "z": nums[0],
                "c": CHANNEL,
                "route": f"[{nums[1]}, {nums[2]}]",
                "t": now - timedelta(hours=3),
            },
        )
        # Broadcasts: positions, node info and telemetry, uploaded on ShortSlow.
        for k in range(90):
            sender = nums[k % len(nums)]
            _packet(
                connection,
                sender,
                960_000 + k,
                [(nums[(k + 1) % len(nums)], 3, 5.0)],
                channel=CHANNEL,
                seen_at=now - timedelta(minutes=7 * k + 3),
            )
        connection.execute(
            text(
                "UPDATE packet SET portnum = CASE packet_id % 3 WHEN 0 THEN 3 WHEN 1 THEN 4 "
                "ELSE 67 END WHERE from_node_num = ANY(:n)"
            ),
            {"n": nums},
        )
    yield
    wipe()


def _answers(timescale_url: str) -> dict[str, Any]:
    cache.clear_all()
    app = create_app(
        Settings(_env_file=None, database_url_api=role_url(timescale_url, "azmsh_api"))
    )
    with TestClient(app) as client:
        return {
            "graph_channel": client.get(f"/api/graph?hours=24&channel={CHANNEL}").json(),
            "graph_all": client.get("/api/graph?hours=24").json(),
            "graph_week": client.get(f"/api/graph?hours=168&channel={CHANNEL}").json(),
            "board": client.get(f"/api/stats/leaderboards?channel={CHANNEL}").json(),
            "broadcast": client.get("/api/stats/broadcast?hours=24").json(),
            "coverage_nodes": client.get(f"/api/map/nodes?channel={CHANNEL}&hours=168").json(),
        }


def _build(timescale_url: str) -> None:
    async def run() -> None:
        engine = make_engine(role_url(timescale_url, "azmsh_jobs"))
        try:
            async with make_session_factory(engine)() as session:
                await job.run_once(session, Settings(_env_file=None))
        finally:
            await engine.dispose()

    asyncio.run(run())


def _link_board(body: dict[str, Any]) -> dict[str, Any]:
    return next(board for board in body["boards"] if board["key"] == "longest_link")


def _without(body: dict[str, Any], *keys: str) -> dict[str, Any]:
    return {key: value for key, value in body.items() if key not in keys}


OUR_IDS = {f"!{node:08x}" for node in NODES}


def _ours(graph: dict[str, Any]) -> tuple[list[Any], list[Any]]:
    """The seed's nodes and links in a graph, in the graph's own order."""
    nodes = [node for node in graph["nodes"] if node["node_id"] in OUR_IDS]
    links = [
        link for link in graph["links"] if link["source"] in OUR_IDS and link["target"] in OUR_IDS
    ]
    return nodes, links


def _our_broadcasts(body: dict[str, Any]) -> dict[str, Any]:
    return {node["node_id"]: node for node in body["nodes"] if node["node_id"] in OUR_IDS}


def test_every_stored_view_equals_the_live_one(
    migrated_engine: Any, timescale_url: str, mesh: None
) -> None:
    live = _answers(timescale_url)
    assert live["graph_channel"]["links"], "the seed drew no link, so nothing is compared"
    assert _link_board(live["board"])["rows"], "the seed put no link on the board"
    assert _our_broadcasts(live["broadcast"]), "the seed's broadcasts are not ranked"

    _build(timescale_url)
    with migrated_engine.connect() as connection:
        built = dict(
            connection.execute(
                text("SELECT hours, built_at FROM link_evidence_run WHERE channel = :c"),
                {"c": CHANNEL},
            ).all()
        )
    assert {6, 24, 72, 168} <= set(built), f"the graph windows were not built: {built}"

    stored = _answers(timescale_url)

    # Read from the build, not computed again: it carries the build's time.
    assert datetime.fromisoformat(stored["graph_channel"]["built_at"]) == built[24]
    assert datetime.fromisoformat(_link_board(stored["board"])["built_at"]) == built[72]

    for name in ("graph_channel", "graph_week"):
        assert _without(stored[name], "built_at") == _without(live[name], "built_at"), name
    # Every channel together holds other tests' rows too: compare ours.
    assert _ours(stored["graph_all"]) == _ours(live["graph_all"])
    assert _ours(stored["graph_all"])[1], "the seed's links are missing from the All graph"
    assert _without(_link_board(stored["board"]), "built_at") == _without(
        _link_board(live["board"]), "built_at"
    )
    assert _our_broadcasts(stored["broadcast"]) == _our_broadcasts(live["broadcast"])
    assert len(_our_broadcasts(live["broadcast"])) == len(NODES)
    assert stored["broadcast"]["window_hours"] == live["broadcast"]["window_hours"]
    assert sorted(node["node_id"] for node in stored["coverage_nodes"]) == sorted(
        node["node_id"] for node in live["coverage_nodes"]
    )


def test_a_renamed_node_reads_its_new_name_from_a_stored_build(
    migrated_engine: Any, timescale_url: str, mesh: None
) -> None:
    """The build holds numbers; names are read when the API answers (#351)."""
    _build(timescale_url)
    first = f"!{0x0EA0_0001:08x}"
    with migrated_engine.begin() as connection:
        connection.execute(
            text("UPDATE node SET long_name = 'Renamed After Build' WHERE node_num = :n"),
            {"n": 0x0EA0_0001},
        )
    body = _answers(timescale_url)["graph_channel"]
    names = {node["node_id"]: node["display_name"] for node in body["nodes"]}
    assert names[first] == "Renamed After Build"


def test_a_stale_build_is_not_served(migrated_engine: Any, timescale_url: str, mesh: None) -> None:
    """A build older than three intervals is ignored: the API computes live."""
    _build(timescale_url)
    with migrated_engine.begin() as connection:
        connection.execute(
            text("UPDATE link_evidence_run SET built_at = built_at - INTERVAL '2 hours'")
        )
    body = _answers(timescale_url)["graph_channel"]
    built = datetime.fromisoformat(body["built_at"])
    assert datetime.now(UTC) - built < timedelta(minutes=5), "a stale build was served"


def test_the_api_role_reads_the_read_models_and_cannot_write_them(
    migrated_engine: Any, timescale_url: str
) -> None:
    from sqlalchemy import create_engine

    engine = create_engine(role_url(timescale_url, "azmsh_api").replace("+asyncpg", "+psycopg"))
    try:
        with engine.connect() as connection:
            for table in (*READ_MODEL_TABLES, "link_evidence_link", "broadcast_node"):
                connection.execute(text(f"SELECT count(*) FROM {table}"))
            with pytest.raises(Exception, match="permission denied"):
                connection.execute(text("DELETE FROM link_evidence_run"))
    finally:
        engine.dispose()
