"""Counted restarts decide a power loop, on real rows (#365).

The bug, reproduced: a battery node at 10 % that restarted once and sends
NodeInfo at the default rate was flagged "maybe power cycling". A node
that restarts again and again and re-announces itself is the real case.
"""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from sonoran.api import cache
from sonoran.api.app import create_app
from sonoran.config import Settings
from tests.integration.conftest import role_url

ONCE = 0x0EB0_0001  # restarted once, 10 % battery, NodeInfo at the default
LOOP = 0x0EB0_0002  # six restarts in six hours, NodeInfo at 4x
QUIET = 0x0EB0_0003  # six restarts in six hours, NodeInfo at the default
NODES = (ONCE, LOOP, QUIET)
NODEINFO, TELEMETRY = 4, 67


def _insert_packet(connection: Any, node: int, packet_id: int, port: int, at: datetime) -> int:
    return int(
        connection.execute(
            text(
                "INSERT INTO packet (from_node_num, packet_id, portnum, channel, hop_start, "
                "first_seen_at) VALUES (:n, :p, :port, 'LongFast', 3, :t) RETURNING id"
            ),
            {"n": node, "p": packet_id, "port": port, "t": at},
        ).scalar_one()
    )


def _reading(
    connection: Any, node: int, packet_id: int, at: datetime, uptime: int, battery: float
) -> None:
    pk = _insert_packet(connection, node, packet_id, TELEMETRY, at)
    connection.execute(
        text(
            "INSERT INTO device_metrics (node_num, packet_pk, packet_id, battery_level, "
            "uptime_seconds, time) VALUES (:n, :pk, :p, :b, :u, :t)"
        ),
        {"n": node, "pk": pk, "p": packet_id, "b": battery, "u": uptime, "t": at},
    )


@pytest.fixture
def nodes(migrated_engine: Any) -> Iterator[None]:
    now = datetime.now(UTC)

    def wipe() -> None:
        with migrated_engine.begin() as connection:
            for table in ("device_metrics", "packet"):
                column = "node_num" if table == "device_metrics" else "from_node_num"
                connection.execute(
                    text(f"DELETE FROM {table} WHERE {column} = ANY(:n)"), {"n": list(NODES)}
                )

    wipe()
    with migrated_engine.begin() as connection:
        # ONCE: up 20 days, one restart 10 hours ago, readings every 30 min.
        uptime = 20 * 86400
        for k in range(46):
            at = now - timedelta(hours=23) + timedelta(minutes=30 * k)
            uptime = 60 if k == 26 else uptime + 1800
            _reading(connection, ONCE, 970_000 + k, at, uptime, 10.0)
        # LOOP and QUIET: seven boots over the last seven hours, two
        # readings a boot, so six restarts.
        for node, base in ((LOOP, 971_000), (QUIET, 972_000)):
            for boot in range(7):
                for step, up in enumerate((120, 900)):
                    at = now - timedelta(hours=7) + timedelta(hours=boot, minutes=20 * step)
                    _reading(connection, node, base + boot * 2 + step, at, up, 80.0)
        # NodeInfo: 8 in 24 h is the default (once per 3 h); 32 is 4x.
        for node, sent, base in ((ONCE, 8, 973_000), (LOOP, 32, 974_000), (QUIET, 8, 975_000)):
            for k in range(sent):
                at = now - timedelta(minutes=10 + k * (1380 // sent))
                _insert_packet(connection, node, base + k, NODEINFO, at)
    yield
    wipe()


def _health(timescale_url: str) -> dict[str, Any]:
    cache.clear_all()
    app = create_app(
        Settings(_env_file=None, database_url_api=role_url(timescale_url, "azmsh_api"))
    )
    with TestClient(app) as client:
        body = client.get("/api/stats/broadcast?hours=24&limit=200").json()
    return {row["node_id"]: row for row in body["nodes"] if int(row["node_id"][1:], 16) in NODES}


def test_restarts_are_counted_and_only_a_real_loop_is_flagged(
    migrated_engine: Any, timescale_url: str, nodes: None
) -> None:
    rows = _health(timescale_url)
    once, loop, quiet = (rows[f"!{node:08x}"] for node in NODES)

    assert once["health"]["restarts"] == 1
    assert not once["health"]["likely_power_loop"], "one restart on 10 % battery is not a loop"
    assert "brownout_risk" not in once["health"]

    assert loop["health"]["restarts"] == 6
    assert loop["health"]["restarts_24h"] == 6
    assert loop["health"]["likely_power_loop"]

    assert quiet["health"]["restarts_24h"] == 6
    assert not quiet["health"]["likely_power_loop"], "NodeInfo at the default is not a loop"


def test_a_real_loop_leads_the_table(migrated_engine: Any, timescale_url: str, nodes: None) -> None:
    order = list(_health(timescale_url))
    assert order[0] == f"!{LOOP:08x}"
