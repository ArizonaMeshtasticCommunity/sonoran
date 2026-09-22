"""The decoded payload that is kept on the packet row.

Only ingest holds the channel keys, so only ingest can ever read what a
packet carried. The public API holds no key by design (see
`docker-compose.yml`, `x-no-credentials`). A packet whose family has no
typed table of its own was therefore unreadable after the fact: a node
info packet showed its envelope and "137 bytes" and nothing else.

This module decides what ingest writes to `packet.payload_json` so the
packet page can show it. It is a pure function. It has no database and
no network dependency, like the rest of `sonoran.decode`.

**It is an allowlist.** A family is kept only when what it carries is
already public on the mesh and says nothing a person typed:

- Node info: the names, hardware, role and public key a node announces
  to everybody. The MAC address is dropped.
- Routing: an acknowledgement, or the reason a packet was refused.
- Traceroute: the route and its readings, as the traceroute table holds.
- Map report: what a node publishes to the public map.
- Pax counter: two counts.

Everything else is left out. Text never goes here, whatever
`STORE_TEXT_MESSAGES` says: that switch is the only thing that decides
whether a message body is kept. Store and forward can replay chat
history, a waypoint and a range test carry text somebody wrote, and an
admin packet can carry configuration. Position, telemetry and neighbour
info already have typed tables, which the packet page reads.
"""

from typing import Any

from google.protobuf.json_format import MessageToDict
from google.protobuf.message import DecodeError, Message

from sonoran.decode.payloads import DecodedPayload, ProtobufPayload, UnknownPayload
from sonoran.meshtastic import mesh_pb2, mqtt_pb2, portnums_pb2

# Families decoded by `decode_payload`, kept as they are.
_KEPT = frozenset(
    {
        portnums_pb2.NODEINFO_APP,  # type: ignore[attr-defined]
        portnums_pb2.TRACEROUTE_APP,  # type: ignore[attr-defined]
        portnums_pb2.PAXCOUNTER_APP,  # type: ignore[attr-defined]
    }
)

# Families `decode_payload` leaves as raw bytes, decoded here. They are
# not added to its table, because that table also decides which ingest
# handler runs, and neither of these has one.
_PARSED_HERE: dict[int, type[Message]] = {
    portnums_pb2.ROUTING_APP: mesh_pb2.Routing,  # type: ignore[attr-defined]
    portnums_pb2.MAP_REPORT_APP: mqtt_pb2.MapReport,  # type: ignore[attr-defined]
}

# Fields that are dropped from what is kept, by family.
_DROPPED: dict[int, frozenset[str]] = {
    # A hardware address says nothing the page needs and follows the
    # device wherever it goes.
    portnums_pb2.NODEINFO_APP: frozenset({"macaddr"}),  # type: ignore[attr-defined]
}

# A payload larger than this is not kept. The families above are all far
# smaller; this only guards the row against a malformed one.
MAX_JSON_FIELDS = 64


def stored_payload(decoded: DecodedPayload) -> dict[str, Any] | None:
    """Return what to keep of one decoded payload, or None to keep nothing."""
    message: Message | None = None
    if isinstance(decoded, ProtobufPayload) and decoded.portnum in _KEPT:
        message = decoded.message
    elif isinstance(decoded, UnknownPayload) and decoded.portnum in _PARSED_HERE:
        parsed: Any = _PARSED_HERE[decoded.portnum]()
        try:
            parsed.ParseFromString(decoded.raw)
        except DecodeError:
            return None
        message = parsed
    if message is None:
        return None

    values = MessageToDict(message, preserving_proto_field_name=True)
    for name in _DROPPED.get(decoded.portnum, frozenset()):
        values.pop(name, None)
    if len(values) > MAX_JSON_FIELDS:
        return None
    return values
