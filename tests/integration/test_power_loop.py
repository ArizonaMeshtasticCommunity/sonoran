"""Counted restarts decide a power loop, on real rows (#365).

The bug, reproduced: ONCE is a battery node at 10 % that restarted once
in the window and sends NodeInfo at the default rate. The old rule
(battery 5-35 % and longest uptime shorter than the window) flagged it
"maybe power cycling".

Each node also catches one plausible wrong implementation:

- ONCE: every other reading's own clock runs 2 h behind, and one uptime
  repeats. Counting in device-time order, or counting an equal uptime,
  gives more than one restart.
- LOOP: six restarts in the last 6 h, with 6 NodeInfo in that span:
  0.75x of a full day, 3x of the 6 h observed. Expecting a full day's
  NodeInfo from a span cut short by "now" misses the loop.
- QUIET: the same restarts, with 16 NodeInfo all outside the span: 2x
  over the window, none in the span. Judging NodeInfo over the window
  calls it a loop.
- NOTABLE: no restarts, NodeInfo at 3x: it meets the table's heading,
  and the loop must still lead it.
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

ONCE = 0x0EB0_0001
LOOP = 0x0EB0_0002
QUIET = 0x0EB0_0003
NOTABLE = 0x0EB0_0004
NODES = (ONCE, LOOP, QUIET, NOTABLE)
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
    connection: Any,
    node: int,
    packet_id: int,
    at: datetime,
    uptime: int,
    battery: float,
    device_at: datetime | None = None,
) -> None:
    """One device telemetry reading, stored the way ingest stores it.

    Ingest never knows the packet's row id (`ingest/dedup.py` claims the
    packet through the key table and returns `packet_pk=None`), so the
    reading links to its packet by (node, packet ID), AGENTS.md 9.1. The
    first version of this fixture set `packet_pk`, which ingest does not:
    on live data that join found 18 of 521 nodes.
    """
    _insert_packet(connection, node, packet_id, TELEMETRY, at)
    connection.execute(
        text(
            "INSERT INTO device_metrics (node_num, packet_pk, packet_id, battery_level, "
            "uptime_seconds, time) VALUES (:n, NULL, :p, :b, :u, :t)"
        ),
        {"n": node, "p": packet_id, "b": battery, "u": uptime, "t": device_at or at},
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
        # ONCE: booted an hour before the first reading, so its longest
        # uptime is under the 24 h window; one restart 10 hours ago; one
        # uptime repeated (k=10); every other device clock 2 h behind.
        uptime = 3600
        for k in range(46):
            at = now - timedelta(hours=23) + timedelta(minutes=30 * k)
            if k == 26:
                uptime = 60
            elif k != 10:
                uptime += 1800
            behind = timedelta(hours=2) if k % 2 else timedelta(0)
            _reading(connection, ONCE, 970_000 + k, at, uptime, 10.0, at - behind)
        # LOOP and QUIET: seven boots over the last seven hours, two
        # readings a boot, so six restarts, the first 6 h ago.
        for node, base in ((LOOP, 971_000), (QUIET, 972_000)):
            for boot in range(7):
                for step, up in enumerate((120, 900)):
                    at = now - timedelta(hours=7) + timedelta(hours=boot, minutes=20 * step)
                    _reading(connection, node, base + boot * 2 + step, at, up, 80.0)
        # NOTABLE: one steady boot.
        for k in range(10):
            at = now - timedelta(hours=20) + timedelta(hours=2 * k)
            _reading(connection, NOTABLE, 976_000 + k, at, 86400 + 7200 * k, 90.0)
        nodeinfo = {
            ONCE: [now - timedelta(minutes=10 + 172 * k) for k in range(8)],  # 1.0x
            LOOP: [now - timedelta(minutes=5 + 55 * k) for k in range(6)],  # in the span
            QUIET: [now - timedelta(hours=8, minutes=50 * k) for k in range(16)],  # outside it
            NOTABLE: [now - timedelta(minutes=10 + 57 * k) for k in range(24)],  # 3.0x
        }
        for node, times in nodeinfo.items():
            for k, at in enumerate(times):
                _insert_packet(connection, node, 980_000 + node % 16 * 100 + k, NODEINFO, at)
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
    once, loop, quiet, notable = (rows[f"!{node:08x}"] for node in NODES)

    # The bug first, so `main` fails on it and not on a missing field.
    assert not once["health"]["likely_power_loop"], "one restart on 10 % battery is not a loop"
    assert once["health"]["restarts"] == 1, "device-time order or an equal uptime was counted"
    assert "brownout_risk" not in once["health"]

    assert loop["health"]["restarts"] == 6
    assert loop["health"]["restarts_24h"] == 6
    assert loop["health"]["nodeinfo_ratio_24h"] == pytest.approx(3.0, abs=0.05)
    assert loop["health"]["likely_power_loop"], "a loop cut short by now was judged on a full day"

    assert quiet["health"]["restarts_24h"] == 6
    assert quiet["health"]["nodeinfo_ratio_24h"] == 0.0
    assert not quiet["health"]["likely_power_loop"], "NodeInfo outside the span was counted"

    assert notable["health"]["restarts"] == 0
    assert notable["notable"] == ["NODEINFO_APP"]


def test_a_real_loop_leads_the_table(migrated_engine: Any, timescale_url: str, nodes: None) -> None:
    order = list(_health(timescale_url))
    assert order.index(f"!{LOOP:08x}") < order.index(f"!{NOTABLE:08x}"), (
        "a counted loop must lead a row that only meets the heading"
    )
