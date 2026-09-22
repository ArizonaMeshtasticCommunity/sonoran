"""Tests for how the graph grades the evidence behind a link (#73).

A neighbor report and a traceroute hop are the same evidence: one packet
heard across the link. What decides the line is how many packets crossed
it, and in which directions.
"""

from datetime import UTC, datetime

from sonoran.api.routes.graph import (
    ONE_WAY,
    TWO_WAY,
    TWO_WAY_MIN_SAMPLES,
    WEAK,
    WEAK_LINK_SAMPLES,
    Edge,
    _add,
    _merge,
    _trace_links,
)
from sonoran.db.models import Traceroute

NOW = datetime(2026, 8, 1, tzinfo=UTC)
A, B, C = 0x11111111, 0x22222222, 0x33333333


def hops(edges: dict[tuple[int, int], Edge], source: int, target: int, n: int, kind: str) -> None:
    """Add `n` packets heard crossing from `source` to `target`."""
    for _ in range(n):
        _add(edges, Edge(source=source, target=target, kind=kind, snr=5.0, time=NOW))


def only(edges: dict[tuple[int, int], Edge]) -> Edge:
    assert len(edges) == 1
    return next(iter(edges.values()))


def test_a_rarely_seen_link_is_weak_whatever_its_direction() -> None:
    edges: dict[tuple[int, int], Edge] = {}
    hops(edges, A, B, WEAK_LINK_SAMPLES // 2, "traceroute")
    hops(edges, B, A, WEAK_LINK_SAMPLES // 2 - 1, "traceroute")
    assert only(edges).strength == WEAK


def test_a_link_seen_mostly_one_way_is_one_way() -> None:
    edges: dict[tuple[int, int], Edge] = {}
    hops(edges, A, B, WEAK_LINK_SAMPLES, "traceroute")
    hops(edges, B, A, TWO_WAY_MIN_SAMPLES - 1, "traceroute")
    edge = only(edges)
    assert edge.as_json()["each_way"] == [WEAK_LINK_SAMPLES, TWO_WAY_MIN_SAMPLES - 1]
    assert edge.strength == ONE_WAY


def test_a_link_seen_both_ways_is_two_way() -> None:
    edges: dict[tuple[int, int], Edge] = {}
    hops(edges, A, B, WEAK_LINK_SAMPLES, "traceroute")
    hops(edges, B, A, TWO_WAY_MIN_SAMPLES, "traceroute")
    assert only(edges).strength == TWO_WAY


def test_neighbor_reports_count_the_same_as_traceroute_hops() -> None:
    """A neighbor report is not a higher class of evidence than a hop."""
    traces: dict[tuple[int, int], Edge] = {}
    hops(traces, A, B, WEAK_LINK_SAMPLES, "traceroute")
    neighbours: dict[tuple[int, int], Edge] = {}
    hops(neighbours, B, A, TWO_WAY_MIN_SAMPLES, "neighbor")

    _merge(traces, only(neighbours))
    edge = only(traces)
    assert edge.count == WEAK_LINK_SAMPLES + TWO_WAY_MIN_SAMPLES
    assert (edge.forward, edge.backward) == (WEAK_LINK_SAMPLES, TWO_WAY_MIN_SAMPLES)
    assert edge.as_json()["kinds"] == ["neighbor", "traceroute"]
    assert edge.strength == TWO_WAY


def test_a_reply_evidences_its_way_back_too() -> None:
    """The return path of a reply is a packet heard the other way."""
    row = Traceroute(
        from_node_num=C,  # a reply comes back from the node that answered
        to_node_num=A,
        route=[B],
        route_back=[B],
        snr_towards=[12, 20],
        snr_back=[8, 4],
        request_id=99,
        packet_id=1,
        channel="LongFast",
        seen_at=NOW,
    )
    assert _trace_links(row) == [
        (A, B, 3.0, 1, 2),
        (B, C, 5.0, 2, 2),
        (C, B, 2.0, 1, 2),
        (B, A, 1.0, 2, 2),
    ]
