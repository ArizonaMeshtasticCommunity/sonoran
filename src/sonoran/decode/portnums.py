"""What to call a group of packets (#157).

Three route modules held a byte-identical `_portnum_name`, and all
three answered `UNKNOWN_APP` for a `portnum` of 0. That value is both
the real Meshtastic port `UNKNOWN_APP` and the sentinel ingest writes
when it could not read a packet, and a census against production
measured the mix at 91.7% PKI direct messages, 8.2% no-key, and 0.1%
genuine `UNKNOWN_APP`. So that label was right about roughly one packet
in a thousand.

`traffic_label` is the fix: for every port but 0 it is exactly what
`_portnum_name` was, and for 0 it reads `payload_state` and says which
of the four things the row is.

A fourth copy lives in `decode/payloads.py` and is **deliberately left
alone**. It answers `UNKNOWN_{portnum}` where these answer `str(portnum)`,
because it names a decoded payload rather than a chart band, and
folding two different contracts into one function to make a count of
copies go down would be a change nobody asked for.
"""

from __future__ import annotations

from sonoran.decode.payload_state import PayloadState
from sonoran.meshtastic import portnums_pb2

#: The port number that is both a real port and the "cannot read it"
#: sentinel. Imported rather than written as 0 in four places.
UNKNOWN_PORTNUM = 0

#: Names for the states that are not port numbers at all.
#:
#: Shaped like the protobuf names because the browser already turns
#: `TELEMETRY_APP` into "Telemetry" through one table, and an identifier
#: goes through that path unchanged. They cannot collide with a real
#: port name: no Meshtastic port is called `UNREADABLE_*`.
PKI_LABEL = "UNREADABLE_PKI"
NO_KEY_LABEL = "UNREADABLE_NO_KEY"
UNRECORDED_LABEL = "UNREADABLE_UNRECORDED"

_BY_STATE = {
    PayloadState.PKI: PKI_LABEL,
    PayloadState.NO_KEY: NO_KEY_LABEL,
}


def portnum_name(value: int) -> str:
    """Return the protobuf name of a port number, or the number itself."""
    try:
        return str(portnums_pb2.PortNum.Name(value))  # type: ignore[attr-defined]
    except ValueError:
        return str(value)


def traffic_label(portnum: int, payload_state: str | None) -> str:
    """Return what to call one group of packets.

    `payload_state` is only consulted for port 0, because that is the
    only port where the stored number is ambiguous. A readable packet
    on port 0 really is `UNKNOWN_APP` and keeps that name.

    A row with no recorded state gets its own label rather than being
    folded into the commonest one. Every packet stored before revision
    0015 is in that group, and the honest thing for a chart to say
    about them is that nobody asked at the time -- guessing PKI because
    91.7% of a later window was PKI would be inventing evidence, which
    is the same move that put `WEAK` on 90% of the links in #149.
    """
    if portnum != UNKNOWN_PORTNUM:
        return portnum_name(portnum)
    if payload_state is None:
        return UNRECORDED_LABEL
    return _BY_STATE.get(PayloadState(payload_state), portnum_name(portnum))
