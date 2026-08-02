"""Tests for how one stored traceroute row becomes a path.

Each test here pins a rule that the graph page once broke. The graph
drew links that no report evidenced, so clicking one opened an empty
page. See AGENTS.md 9.6 and 9.18.
"""

from datetime import UTC, datetime

from sonoran.api.routes.graph import _trace_links
from sonoran.api.traces import evidenced_hops, forward_path, is_reply, return_path
from sonoran.db.models import Traceroute

NOW = datetime(2026, 8, 1, tzinfo=UTC)

# Four nodes, named for readability.
ASKER = 0x11111111
MIDDLE = 0x22222222
FAR = 0x33333333
ANSWERER = 0x44444444


def trace(**fields: object) -> Traceroute:
    """Return a traceroute row with the given fields."""
    defaults: dict[str, object] = {
        "from_node_num": ASKER,
        "to_node_num": ANSWERER,
        "route": [],
        "route_back": None,
        "snr_towards": [],
        "snr_back": None,
        "request_id": None,
        "packet_id": 1234,
        "channel": "LongFast",
        "seen_at": NOW,
    }
    return Traceroute(**(defaults | fields))


def test_a_request_reads_in_the_order_it_is_stored() -> None:
    row = trace(route=[MIDDLE])
    assert not is_reply(row)
    assert forward_path(row) == [ASKER, MIDDLE, ANSWERER]


def test_a_reply_swaps_its_endpoints() -> None:
    """A reply travels back, so its packet fields are the wrong way round.

    Reading a reply as stored invents a first hop and a last hop that
    never existed. That is how the graph drew a link between the node
    that answered and the first hop of the outward path.
    """
    row = trace(from_node_num=ANSWERER, to_node_num=ASKER, route=[MIDDLE], request_id=99)
    assert is_reply(row)
    assert forward_path(row) == [ASKER, MIDDLE, ANSWERER]


def test_the_reply_path_runs_back_from_the_answerer() -> None:
    row = trace(
        from_node_num=ANSWERER,
        to_node_num=ASKER,
        route=[MIDDLE],
        route_back=[FAR],
        request_id=99,
    )
    assert return_path(row) == [ANSWERER, FAR, ASKER]


def test_a_request_with_no_route_evidences_nothing() -> None:
    """An unanswered request must not draw a direct link.

    Its intended path is one hop from end to end. Drawing that claims
    the two nodes hear each other directly, which is the one thing the
    trace failed to show.
    """
    row = trace(route=[], snr_towards=None)
    hops, complete = evidenced_hops(forward_path(row), [])
    assert hops == []
    assert not complete
    assert _trace_links(row) == []


def test_hops_past_the_last_reading_are_not_drawn() -> None:
    """A report can stop part way along its intended path."""
    row = trace(route=[MIDDLE, FAR], snr_towards=[12])
    hops, complete = evidenced_hops(forward_path(row), [12])
    assert hops == [(ASKER, MIDDLE, 3.0)]
    assert not complete


def test_a_full_report_draws_every_hop() -> None:
    row = trace(route=[MIDDLE], snr_towards=[12, -20])
    hops, complete = evidenced_hops(forward_path(row), [12, -20])
    assert hops == [(ASKER, MIDDLE, 3.0), (MIDDLE, ANSWERER, -5.0)]
    assert complete


def test_an_unmeasured_hop_still_happened() -> None:
    """INT8_MIN means the reading is missing, not that the hop is."""
    row = trace(route=[MIDDLE], snr_towards=[-128, 12])
    hops, _ = evidenced_hops(forward_path(row), [-128, 12])
    assert hops == [(ASKER, MIDDLE, None), (MIDDLE, ANSWERER, 3.0)]


def test_trace_links_carry_the_position_and_the_claimed_length() -> None:
    row = trace(route=[MIDDLE, FAR], snr_towards=[12, 20])
    assert _trace_links(row) == [
        (ASKER, MIDDLE, 3.0, 1, 3),
        (MIDDLE, FAR, 5.0, 2, 3),
    ]


def test_a_reply_does_not_invent_its_end_links() -> None:
    """Reading a reply as stored fabricates the first hop and the last.

    Two hops in the route are needed to show it. With one hop the two
    readings give the same pair of links either way round, which is why
    the fault hid for so long.
    """
    row = trace(
        from_node_num=ANSWERER,
        to_node_num=ASKER,
        route=[MIDDLE, FAR],
        request_id=99,
        snr_towards=[12, 20, 8],
    )
    pairs = {frozenset((source, target)) for source, target, _, _, _ in _trace_links(row)}
    assert pairs == {
        frozenset((ASKER, MIDDLE)),
        frozenset((MIDDLE, FAR)),
        frozenset((FAR, ANSWERER)),
    }
    # The two links the old reading invented.
    assert frozenset((ANSWERER, MIDDLE)) not in pairs
    assert frozenset((FAR, ASKER)) not in pairs
