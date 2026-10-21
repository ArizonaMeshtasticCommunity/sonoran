"""The heard positions heatmap scores each packet in the database.

On the dev box on 2026-10-21 the query returned 1.5 million rows, one
for each gateway that heard each of 156 000 positions in 30 days. Read
into Python, they took the job to 834 MB, over its 800 MB ceiling, and
the supervisor stopped it. The database now scores each packet, so the
job reads one row for each position.

The rules are the ones the Python scoring had (#344): a packet is a node
and a packet ID; each gateway counts once, at its fewest hops; a gateway
with no hop count is left out; a manual position is left out.
"""

import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import text

from sonoran.config import Settings
from sonoran.db.session import make_engine, make_session_factory
from sonoran.jobs.activity_heatmap import _fetch_position_metrics
from tests.integration.conftest import role_url

# Every node these tests add is in this range, so they can be taken out again.
OWN_NODES = (344000, 344999)


@pytest.fixture(autouse=True)
def _remove_own_rows(migrated_engine) -> Iterator[None]:  # type: ignore[no-untyped-def]
    yield
    with migrated_engine.begin() as connection:
        for table, column in (
            ("packet_seen", "from_node_num"),
            ("position_metrics", "node_num"),
        ):
            connection.execute(
                text(f"DELETE FROM {table} WHERE {column} BETWEEN :low AND :high"),
                {"low": OWN_NODES[0], "high": OWN_NODES[1]},
            )


def _position(connection, node: int, packet: int, *, lat: float, source: str | None = None) -> None:  # type: ignore[no-untyped-def]
    connection.execute(
        text(
            "INSERT INTO position_metrics (node_num, packet_id, latitude, longitude, "
            "precision_bits, location_source, time) VALUES (:n, :p, :lat, -111.5, 32, :s, :t)"
        ),
        {
            "n": node,
            "p": packet,
            "lat": lat,
            "s": source,
            "t": datetime.now(UTC) - timedelta(hours=1),
        },
    )


def _seen(connection, node: int, packet: int, gateway: int, hops: int | None) -> None:  # type: ignore[no-untyped-def]
    connection.execute(
        text(
            "INSERT INTO packet_seen (from_node_num, packet_id, gateway_node_num, mqtt_topic, "
            "hop_start, hop_limit, seen_at) VALUES (:n, :p, :g, 'msh/US/AZ/test', :hs, :hl, :t)"
        ),
        {
            "n": node,
            "p": packet,
            "g": gateway,
            "hs": None if hops is None else 3,
            "hl": None if hops is None else 3 - hops,
            "t": datetime.now(UTC) - timedelta(hours=1),
        },
    )


class _CountingSession:
    """Passes queries to a real session and counts the rows that come back."""

    def __init__(self, session: Any) -> None:
        self.session = session
        self.rows = 0

    async def execute(self, query: Any) -> Any:
        result = await self.session.execute(query)
        if not getattr(query, "is_select", False):
            return result
        rows = list(result)
        self.rows += len(rows)
        return rows


def _fetch(timescale_url: str) -> tuple[list[tuple[float, float, float]], int]:
    settings = Settings(
        _env_file=None,
        database_url_jobs=role_url(timescale_url, "azmsh_jobs"),
        coverage_min_precision_bits=16,
    )

    async def go() -> tuple[list[tuple[float, float, float]], int]:
        engine = make_engine(settings.database_url_jobs)
        try:
            async with make_session_factory(engine)() as session:
                counting = _CountingSession(session)
                points = await _fetch_position_metrics(counting, settings)
                return points, counting.rows
        finally:
            await engine.dispose()

    return asyncio.run(go())


def _ours(points: list[tuple[float, float, float]]) -> dict[float, float]:
    """This test's points, by latitude (each position has its own)."""
    return {lat: score for lat, _lon, score in points if 10.0 <= lat < 11.0}


def test_one_row_per_position_however_many_gateways_heard_it(  # type: ignore[no-untyped-def]
    migrated_engine, timescale_url: str
) -> None:
    node = 344001
    _, before = _fetch(timescale_url)
    with migrated_engine.begin() as connection:
        _position(connection, node, 1, lat=10.1)
        for gateway in range(5):
            _seen(connection, node, 1, gateway=900 + gateway, hops=0)
    points, rows = _fetch(timescale_url)
    assert rows - before == 1, f"{rows - before} rows for one position heard by 5 gateways"
    assert _ours(points) == {10.1: 50.0}


def test_the_scoring_rules_of_the_heatmap(  # type: ignore[no-untyped-def]
    migrated_engine, timescale_url: str
) -> None:
    with migrated_engine.begin() as connection:
        # Two nodes, the same packet ID: two points (AGENTS.md 9.1).
        _position(connection, 344010, 42, lat=10.2)
        _seen(connection, 344010, 42, gateway=900, hops=0)
        _position(connection, 344011, 42, lat=10.3)
        _seen(connection, 344011, 42, gateway=900, hops=0)
        # One gateway twice counts once, at its fewest hops; another at 3 hops.
        _position(connection, 344012, 7, lat=10.4)
        _seen(connection, 344012, 7, gateway=900, hops=3)
        _seen(connection, 344012, 7, gateway=900, hops=0)
        _seen(connection, 344012, 7, gateway=901, hops=3)
        # 1 or 2 hops score 5; 5 or more score 1.
        _position(connection, 344013, 8, lat=10.5)
        _seen(connection, 344013, 8, gateway=900, hops=2)
        _seen(connection, 344013, 8, gateway=901, hops=6)
        # No hop count: that gateway is left out, and a packet with none is not a point.
        _position(connection, 344014, 9, lat=10.6)
        _seen(connection, 344014, 9, gateway=900, hops=None)
        # A position the owner typed in is not where the radio was heard.
        _position(connection, 344015, 10, lat=10.7, source="LOC_MANUAL")
        _seen(connection, 344015, 10, gateway=900, hops=0)
    points, _ = _fetch(timescale_url)
    assert _ours(points) == {10.2: 10.0, 10.3: 10.0, 10.4: 12.0, 10.5: 6.0}
