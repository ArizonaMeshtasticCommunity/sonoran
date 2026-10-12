"""How to read one stored traceroute row.

A row is not a path on its own. Three rules turn it into one, and each
rule was learned from live data:

- A reply travels back, so its packet endpoints are the wrong way round.
- SNR is in quarter dB, and INT8_MIN means "not measured", not -32 dB.
- The reading list can stop part way along the path. The hops past the
  last reading did not happen yet.

The graph, the map, and the traceroute pages all need these rules. The
rules live here so that the pages cannot disagree about what one row
proves. See AGENTS.md 9.6.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from itertools import pairwise
from typing import NamedTuple, Protocol


class TraceEnds(Protocol):
    """The columns that say which way a `traceroute` row travels."""

    @property
    def from_node_num(self) -> int: ...
    @property
    def to_node_num(self) -> int: ...
    @property
    def request_id(self) -> int | None: ...


class TraceRow(Protocol):
    """The columns of a `traceroute` row that the rules here read.

    A mapped `Traceroute` has them, and so does a lean row that selects
    only these columns. The node page reads tens of thousands of rows in
    one answer (#290), and building a whole ORM object for each one cost
    more than the rules themselves. The rules stay here either way.
    """

    @property
    def from_node_num(self) -> int: ...
    @property
    def to_node_num(self) -> int: ...
    @property
    def request_id(self) -> int | None: ...
    @property
    def route(self) -> list | None: ...
    @property
    def route_back(self) -> list | None: ...
    @property
    def snr_towards(self) -> list | None: ...
    @property
    def snr_back(self) -> list | None: ...


# Traceroute reports store SNR in quarter dB.
SNR_SCALE = 4

# Firmware writes INT8_MIN into a hop whose SNR it could not measure.
# Scaled that is -32 dB, which would read as a real but terrible link.
UNKNOWN_SNR = -128

# One hop of an evidenced path: the two ends and the reading, if any.
Hop = tuple[int, int, float | None]


def is_reply(trace: TraceEnds) -> bool:
    """Return true when this row is a traceroute reply.

    A reply answers a request, so it carries the request ID.
    """
    return trace.request_id is not None


def trace_endpoints(trace: TraceEnds) -> tuple[int, int]:
    """Return the request direction of one traceroute.

    A reply travels back from the node that answered, so the packet
    fields are the wrong way round for describing the route: `from` is
    the node the request was sent to. Swap them, which is what
    mesh-graph does when it stores a trace.
    """
    if is_reply(trace):
        return trace.to_node_num, trace.from_node_num
    return trace.from_node_num, trace.to_node_num


def hop_snr(readings: list[object], index: int) -> float | None:
    """Return the SNR of one hop in dB, if the report has it.

    A report can be shorter than the hop list. Firmware fills a hop it
    could not measure with INT8_MIN, and firmware older than the SNR
    field sends no list at all. All three cases mean "not measured", so
    they return None instead of a wrong number.
    """
    if index >= len(readings):
        return None
    value = readings[index]
    if not isinstance(value, int | float) or isinstance(value, bool):
        return None
    if value <= UNKNOWN_SNR:
        return None
    return value / SNR_SCALE


def forward_path(trace: TraceRow) -> list[int]:
    """Return the nodes of the request path, from the asker to the answerer."""
    origin, destination = trace_endpoints(trace)
    hops = [origin, *(trace.route or []), destination]
    return [hop for hop in hops if isinstance(hop, int)]


def return_path(trace: TraceRow) -> list[int]:
    """Return the nodes of the reply path, or nothing when there is no reply."""
    if not is_reply(trace) or not trace.route_back:
        return []
    origin, destination = trace_endpoints(trace)
    hops = [destination, *(trace.route_back or []), origin]
    return [hop for hop in hops if isinstance(hop, int)]


def evidenced_hops(path: list[int], readings: list[object]) -> tuple[list[Hop], bool]:
    """Return the hops one report proves, and whether it reached the end.

    A hop counts as evidence only when the report carries a reading slot
    for it. The broker sees a packet while it travels, so a report can
    stop part way along its intended path. Hops past the last slot did
    not happen yet, and must not be drawn as though they did.

    An unanswered request is the worst case. It has an empty route, so
    its intended path is one long hop from end to end. Drawing that
    claims the two nodes hear each other directly, which is exactly what
    the trace failed to show.

    A slot that holds INT8_MIN still counts: the hop happened, and only
    its reading is missing.
    """
    hops: list[Hop] = [
        (source, target, hop_snr(readings, index))
        for index, (source, target) in enumerate(pairwise(path))
    ]
    measured = len(readings)
    if measured >= len(hops):
        return hops, True
    return hops[:measured], False


# The destination of a broadcast. A traceroute to it names no target.
BROADCAST = 0xFFFFFFFF


class TraceKey(NamedTuple):
    """The four columns that match a request to its answer (#293).

    A request has `request_id` None and its own `packet_id`. A reply has
    `request_id` set to the `packet_id` of the request it answers
    (AGENTS.md 9.8).
    """

    from_node_num: int
    to_node_num: int
    request_id: int | None
    packet_id: int | None


@dataclass(frozen=True)
class Answers:
    """How often one node was traced, and how often it answered."""

    requests: int
    answered: int
    senders: int


def answer_counts(rows: Iterable[TraceKey]) -> dict[int, Answers]:
    """Return, for each node asked, its traceroutes and its answers.

    A request is answered when a reply carries its packet ID as the
    request ID, comes from the node that was asked, and goes to the node
    that asked. Packet IDs belong to their sender, so the asker is part
    of the match. `trace_endpoints` turns a reply back into the request
    direction, so a request and its answer give the same key.

    - A request or a reply seen more than once counts once.
    - A reply whose request was never seen counts in neither.
    - A node that traces itself proves nothing about reaching it, so a
      self-trace is ignored. The asker must be another node.
    - A traceroute to the broadcast address names no target.

    "Unanswered" means that no gateway uploaded an answer. The node may
    have answered and no gateway heard it. See AGENTS.md 9.5.1.
    """
    asked: set[tuple[int, int, int]] = set()
    answered: set[tuple[int, int, int]] = set()
    for row in rows:
        asker, target = trace_endpoints(row)
        if asker == target or BROADCAST in (asker, target):
            continue
        if is_reply(row):
            if row.request_id is not None:  # always true for a reply; said for mypy
                answered.add((asker, target, row.request_id))
        elif row.packet_id is not None:
            asked.add((asker, target, row.packet_id))

    requests: dict[int, int] = {}
    replies: dict[int, int] = {}
    senders: dict[int, set[int]] = {}
    for key in asked:
        asker, target, _ = key
        requests[target] = requests.get(target, 0) + 1
        senders.setdefault(target, set()).add(asker)
        if key in answered:
            replies[target] = replies.get(target, 0) + 1
    return {
        target: Answers(
            requests=count, answered=replies.get(target, 0), senders=len(senders[target])
        )
        for target, count in requests.items()
    }
