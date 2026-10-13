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


# ------------------------------------------------- what a link's SNR is


def test_a_links_snr_is_the_median_and_not_the_newest_reading(**_: object) -> None:
    """#71. It was the newest, and every other sample was discarded.

    Measured on one real link: the graph reported **-6.75 dB** while
    the fifty samples behind it ran -16.0 to -0.25, with the next four
    at -12.75, -13.0, -8.75 and -5.0. The figure a reader saw was
    whichever hop happened to be measured last, which moves for
    reasons that have nothing to do with the link.
    """
    edges: dict[tuple[int, int], Edge] = {}
    for snr, minute in ((-16.0, 0), (-5.0, 1), (-12.0, 2), (-0.25, 3), (-13.0, 4)):
        _add(
            edges,
            Edge(
                source=A,
                target=B,
                kind="traceroute",
                snr=snr,
                time=NOW.replace(minute=minute),
            ),
        )
    edge = only(edges)
    assert edge.samples == sorted([-16.0, -5.0, -12.0, -0.25, -13.0]), "samples were not all kept"
    # Newest is -13.0 and the maximum is -0.25. Neither is the answer.
    assert edge.snr_summary == -12.0
    assert edge.as_json()["snr"] == -12.0


def test_an_even_number_of_samples_averages_the_middle_two() -> None:
    edges: dict[tuple[int, int], Edge] = {}
    for snr in (-10.0, -2.0, -8.0, -4.0):
        _add(edges, Edge(source=A, target=B, kind="traceroute", snr=snr, time=NOW))
    assert only(edges).snr_summary == -6.0


def test_a_link_nothing_measured_still_has_no_snr() -> None:
    """None is not zero, and it must survive to the page.

    The graph draws a link with no SNR in a stale colour rather than
    as a bad one, so a 0.0 here would repaint every unmeasured link as
    a poor one.
    """
    edges: dict[tuple[int, int], Edge] = {}
    _add(edges, Edge(source=A, target=B, kind="neighbor", snr=None, time=NOW))
    edge = only(edges)
    assert edge.samples == []
    assert edge.snr_summary is None
    assert edge.as_json()["snr"] is None


def test_merging_two_maps_keeps_both_sides_samples() -> None:
    """`_merge` folds a whole counted link in, not one report.

    Dropping the incoming samples here would make the median depend on
    which source was read first -- traceroutes or neighbour reports.
    """
    left: dict[tuple[int, int], Edge] = {}
    right: dict[tuple[int, int], Edge] = {}
    for snr in (-2.0, -4.0):
        _add(left, Edge(source=A, target=B, kind="traceroute", snr=snr, time=NOW))
    for snr in (-20.0, -22.0):
        _add(right, Edge(source=A, target=B, kind="neighbor", snr=snr, time=NOW))
    _merge(left, only(right))
    assert sorted(only(left).samples) == [-22.0, -20.0, -4.0, -2.0]
    assert only(left).snr_summary == -12.0
