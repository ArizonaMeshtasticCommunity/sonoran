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

from itertools import pairwise

from sonoran.db.models import Traceroute

# Traceroute reports store SNR in quarter dB.
SNR_SCALE = 4

# Firmware writes INT8_MIN into a hop whose SNR it could not measure.
# Scaled that is -32 dB, which would read as a real but terrible link.
UNKNOWN_SNR = -128

# One hop of an evidenced path: the two ends and the reading, if any.
Hop = tuple[int, int, float | None]


def is_reply(trace: Traceroute) -> bool:
    """Return true when this row is a traceroute reply.

    A reply answers a request, so it carries the request ID.
    """
    return trace.request_id is not None


def trace_endpoints(trace: Traceroute) -> tuple[int, int]:
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


def forward_path(trace: Traceroute) -> list[int]:
    """Return the nodes of the request path, from the asker to the answerer."""
    origin, destination = trace_endpoints(trace)
    hops = [origin, *(trace.route or []), destination]
    return [hop for hop in hops if isinstance(hop, int)]


def return_path(trace: Traceroute) -> list[int]:
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
