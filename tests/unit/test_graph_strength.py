"""Tests for how the graph grades the evidence behind a link (#73).

A neighbor report and a traceroute hop are the same evidence: one packet
heard across the link. What decides the line is how many packets crossed
it, and in which directions.
"""

from datetime import UTC, datetime

from sonoran.api.routes.graph import (
    MIN_SAMPLES_TO_JUDGE,
    ONE_WAY,
    TWO_WAY,
    TWO_WAY_MIN_SAMPLES,
    UNKNOWN,
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


def test_a_rarely_seen_link_is_unknown_and_not_weak() -> None:
    """#149. The name of this state is the defect it had.

    It was `weak`, rendered as "Weak link: few packets crossed it" --
    a claim about the LINK, justified by a fact about our EVIDENCE.
    90% of links at 24 h were in it on the deployed instance, so the
    graph told every reader the mesh was worse than anybody knows.

    #87 was the same confusion facing the other way: there `unknown`
    was treated as a shade of `ok` and a node nothing had heard read
    Good. Here `unknown` was treated as a shade of bad.
    """
    edges: dict[tuple[int, int], Edge] = {}
    hops(edges, A, B, MIN_SAMPLES_TO_JUDGE // 2, "traceroute")
    hops(edges, B, A, MIN_SAMPLES_TO_JUDGE // 2 - 1, "traceroute")
    assert only(edges).strength == UNKNOWN


def test_a_link_seen_mostly_one_way_is_one_way() -> None:
    edges: dict[tuple[int, int], Edge] = {}
    hops(edges, A, B, MIN_SAMPLES_TO_JUDGE, "traceroute")
    hops(edges, B, A, TWO_WAY_MIN_SAMPLES - 1, "traceroute")
    edge = only(edges)
    assert edge.as_json()["each_way"] == [MIN_SAMPLES_TO_JUDGE, TWO_WAY_MIN_SAMPLES - 1]
    assert edge.strength == ONE_WAY


def test_a_link_seen_both_ways_is_two_way() -> None:
    edges: dict[tuple[int, int], Edge] = {}
    hops(edges, A, B, MIN_SAMPLES_TO_JUDGE, "traceroute")
    hops(edges, B, A, TWO_WAY_MIN_SAMPLES, "traceroute")
    assert only(edges).strength == TWO_WAY


def test_neighbor_reports_count_the_same_as_traceroute_hops() -> None:
    """A neighbor report is not a higher class of evidence than a hop."""
    traces: dict[tuple[int, int], Edge] = {}
    hops(traces, A, B, MIN_SAMPLES_TO_JUDGE, "traceroute")
    neighbours: dict[tuple[int, int], Edge] = {}
    hops(neighbours, B, A, TWO_WAY_MIN_SAMPLES, "neighbor")

    _merge(traces, only(neighbours))
    edge = only(traces)
    assert edge.count == MIN_SAMPLES_TO_JUDGE + TWO_WAY_MIN_SAMPLES
    assert (edge.forward, edge.backward) == (MIN_SAMPLES_TO_JUDGE, TWO_WAY_MIN_SAMPLES)
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


# ------------------------------------------------- the name of the state


def _strip_comments(source: str) -> str:
    """Only the code counts.

    The comments here explain what the old name was and why it was
    wrong, so a plain search finds the banned word inside its own
    explanation. Third time in this repo.
    """
    import re

    source = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    return re.sub(r"^\s*//.*$", "", source, flags=re.M)


def _static(name: str) -> str:
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "src" / "sonoran" / "web" / "static"
    return (root / name).read_text(encoding="utf-8")


def test_the_api_no_longer_calls_an_unmeasured_link_weak() -> None:
    """#149. The word was the bug, so the word is what this holds."""
    from sonoran.api.routes import graph

    assert graph.UNKNOWN == "unknown"
    assert not hasattr(graph, "WEAK"), (
        "the graph exports WEAK again; an unmeasured link is not a weak one"
    )


def test_the_graph_page_does_not_render_it_as_weak_either() -> None:
    """A rename that stops at the API changes nothing a reader sees.

    Both maps are keyed by the strength the endpoint sends, so a stale
    `weak:` key would leave the tooltip and the line style falling back
    to a default on every unmeasured link -- which is how this would
    break quietly rather than loudly.
    """
    body = _strip_comments(_static("app.js"))
    start = body.index("const LINK_LINE = {")
    maps = body[start : body.index("const GRAPH_SPAN")]
    assert "weak:" not in maps, "the graph page still styles or labels a 'weak' link"
    assert "unknown:" in maps
    assert "Too few packets crossed it" in maps, (
        "the tooltip no longer says what the state means in terms of evidence"
    )


def test_the_legend_describes_the_evidence_and_not_the_link() -> None:
    markup = _static("index.html")
    assert "Too little evidence: under 10 packets seen" in markup
    assert "Weak: under 10 packets seen" not in markup
    assert "Show unjudged links" in markup


def test_the_threshold_is_not_scaled_by_the_window() -> None:
    """Measured, scaling is worse. This holds the decision, not a taste.

    #149 asks whether a fixed count is right when the window spans
    1 h to 168 h. It is not obviously right -- with the threshold fixed
    at 10 the share of links with too little evidence falls as the
    window widens, 97.0% / 90.0% / 69.5% at 6 / 24 / 168 h on the
    deployed instance, so the label partly reports the reader's choice.

    The obvious fix is a rate: ten per 24 hours, scaled. Measured on
    the same links it gives 79.4% / 90.0% / 96.4% -- the dependence is
    inverted, not removed, because the link POPULATION grows with the
    window too (1,219 links at 6 h against 4,964 at 168 h, mostly links
    seen once in a week).

    So `strength` takes no window argument, deliberately. If somebody
    adds one, they are re-opening a question that has been measured,
    and this says so before they spend the afternoon.
    """
    import inspect

    from sonoran.api.routes.graph import Edge

    parameters = inspect.signature(Edge.strength.fget).parameters  # type: ignore[attr-defined]
    assert list(parameters) == ["self"], (
        "strength now takes a window; scaling the threshold by it was "
        "measured and made the window dependence worse, not better"
    )
