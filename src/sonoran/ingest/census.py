"""What a stored portnum of 0 actually means (#157).

`UNKNOWN_PORTNUM = 0` is the sentinel this pipeline writes when it
cannot read a packet — and **0 is also a real Meshtastic port number**,
`UNKNOWN_APP`. Nothing else is stored to tell them apart, so one row
with `portnum = 0` is any one of four different events:

1. a genuine `UNKNOWN_APP` packet, decrypted and understood;
2. a packet some key opened by accident — AES-CTR does not
   authenticate, so roughly 1 in 800 foreign packets decrypts to
   something that parses as a `Data` (#157);
3. a packet encrypted on a channel whose key this instance does not
   hold, stored as traffic by `_store_opaque`;
4. a PKI packet — a direct message encrypted to one recipient, which
   nobody here could ever read.

The node page's traffic chart calls all four "UNKNOWN_APP", which is
true of exactly the first one.

This module tells them apart the only way they can be told apart:
by decrypting `Packet.raw_bytes` again. That field already holds the
MeshPacket as it arrived, so this is a query over data on disk and not
a logging period — a correction to my own earlier advice on #157, which
asked for a day of instrumenting the ingest for something already
stored.

It answers #157 directly. The proposed mitigation is to reject a
decrypt whose `Data` is portnum 0 **with an empty payload**; the
measured false accepts are 96% of that shape. The cost of that rule is
the number of *real* packets it would discard, which is the
`decoded_with_payload` count below. Rejecting portnum 0 outright was
already measured here as costing 8,841 real packets a week, so the
empty-payload qualifier is the whole question.

`_valid_data` is imported from the ingest rather than reimplemented. A
census that validated differently from the pipeline would be measuring
a population the pipeline never produced, which is the specific way
this measurement could look right and be worthless.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from google.protobuf.message import DecodeError

from sonoran.crypto.decrypt import DecryptionError, decrypt_packet
from sonoran.decode.payloads import parse_data
from sonoran.ingest.pipeline import UNKNOWN_PORTNUM, _valid_data
from sonoran.meshtastic import mesh_pb2

# What one stored row turned out to be.
#
# `decoded_*` are the two that a key opened. The split between them is
# the answer #157 needs: an empty payload is the false-accept
# signature, a payload with bytes in it is a real UNKNOWN_APP packet
# that the proposed rule would keep.
DECODED_EMPTY = "decoded_empty_payload"
DECODED_WITH_PAYLOAD = "decoded_with_payload"
PLAINTEXT = "plaintext"
OPAQUE = "opaque_no_key_opened"
PKI = "pki_to_one_recipient"
NO_RAW_BYTES = "no_raw_bytes_stored"
UNPARSEABLE = "raw_bytes_not_a_meshpacket"

KINDS = (
    DECODED_EMPTY,
    DECODED_WITH_PAYLOAD,
    PLAINTEXT,
    OPAQUE,
    PKI,
    NO_RAW_BYTES,
    UNPARSEABLE,
)


@dataclass(frozen=True)
class Verdict:
    """What one row was, and what its payload looked like if it was read."""

    kind: str
    # The `Data.portnum` that came out. None where nothing was read.
    # Usually 0, since that is how the row was selected, but a key
    # rotation between ingest and census can move it, and a census that
    # silently assumed 0 would hide that.
    portnum: int | None = None
    payload_bytes: int | None = None


def _packet_from(raw: bytes) -> Any:
    packet: Any = mesh_pb2.MeshPacket()  # type: ignore[attr-defined]
    packet.ParseFromString(raw)
    return packet


def classify(raw: bytes | None, keys: list[bytes]) -> Verdict:
    """Decide what one stored packet really was.

    Takes the same key list, in the same order, that the ingest was
    configured with. Reads only; nothing here writes.
    """
    if not raw:
        return Verdict(NO_RAW_BYTES)
    try:
        packet = _packet_from(raw)
    except DecodeError:
        return Verdict(UNPARSEABLE)

    if getattr(packet, "pki_encrypted", False):
        return Verdict(PKI)

    if not packet.encrypted:
        # It arrived in the clear, so the Data is already parsed and
        # the stored portnum came straight off it.
        data = packet.decoded
        return Verdict(PLAINTEXT, portnum=data.portnum, payload_bytes=len(data.payload))

    try:
        plaintext, _ = decrypt_packet(
            packet.encrypted,
            packet.id,
            getattr(packet, "from"),
            keys,
            validator=_valid_data,
        )
    except DecryptionError:
        return Verdict(OPAQUE)

    data = parse_data(plaintext)
    kind = DECODED_EMPTY if not data.payload else DECODED_WITH_PAYLOAD
    return Verdict(kind, portnum=data.portnum, payload_bytes=len(data.payload))


@dataclass
class Census:
    """Counts over many rows, plus what the payloads looked like."""

    kinds: Counter[str] = field(default_factory=Counter)
    # Exact payload lengths of everything a key opened. Exact rather
    # than bucketed: the question is whether the population sits at
    # zero, and a bucket of "0-8" would answer a different one.
    payload_lengths: Counter[int] = field(default_factory=Counter)
    # Port numbers that came out, which should all be 0.
    portnums: Counter[int] = field(default_factory=Counter)

    def add(self, verdict: Verdict) -> None:
        self.kinds[verdict.kind] += 1
        if verdict.portnum is not None:
            self.portnums[verdict.portnum] += 1
        if verdict.payload_bytes is not None:
            self.payload_lengths[verdict.payload_bytes] += 1

    @property
    def total(self) -> int:
        return sum(self.kinds.values())

    @property
    def readable(self) -> int:
        """Rows a key opened, which are the only ones #157 is about."""
        return self.kinds[DECODED_EMPTY] + self.kinds[DECODED_WITH_PAYLOAD]

    def cost_of_the_empty_payload_rule(self) -> int:
        """Real packets a "reject portnum 0 with no payload" rule loses.

        Zero would mean the rule is free. Anything else is the price,
        in packets, of closing #157 that way -- and it is the number to
        compare against the 8,841 a week that rejecting portnum 0
        outright was measured to cost.
        """
        return self.kinds[DECODED_WITH_PAYLOAD]


def report(census: Census, *, window_hours: int, keys_tried: int) -> str:
    """A plain-text answer to #157, safe to paste into the issue.

    Carries no node IDs, no packet IDs and no payload bytes -- only
    counts and lengths -- so it can go in a public thread.
    """
    lines = [
        f"portnum {UNKNOWN_PORTNUM} census over the last {window_hours} h",
        f"{census.total} rows, {keys_tried} channel key(s) tried in ingest order",
        "",
    ]
    if not census.total:
        lines.append("No rows in the window. Nothing measured.")
        return "\n".join(lines)

    for kind in KINDS:
        count = census.kinds[kind]
        if not count:
            continue
        lines.append(f"  {kind:<28} {count:>8}  {100 * count / census.total:5.1f}%")

    lines += ["", f"Of the {census.readable} rows a key opened:"]
    if census.readable:
        empty = census.kinds[DECODED_EMPTY]
        lines.append(f"  empty payload      {empty:>8}  {100 * empty / census.readable:5.1f}%")
        for length, count in sorted(census.payload_lengths.items()):
            if length:
                lines.append(f"  payload {length:>4} bytes {count:>8}")
        lines += [
            "",
            "Cost of rejecting portnum 0 with an empty payload: "
            f"{census.cost_of_the_empty_payload_rule()} real packets in this window.",
        ]
    else:
        lines.append("  none, so this window says nothing about the false-accept rate")

    other_ports = Counter(
        {port: n for port, n in census.portnums.items() if port != UNKNOWN_PORTNUM}
    )
    if other_ports:
        # Every row here was SELECTed on portnum 0, so the same keys
        # should reproduce it. A different answer means the key list
        # moved between ingest and now, and the window is mixing two
        # configurations. Bounded to the commonest few: an unbounded
        # dump of a long tail is output nobody reads.
        top = ", ".join(f"{port}: {n}" for port, n in other_ports.most_common(10))
        tail = len(other_ports) - min(len(other_ports), 10)
        lines += [
            "",
            f"{sum(other_ports.values())} rows no longer decrypt to portnum 0, "
            "so a channel key changed between ingest and now and this window "
            "spans two configurations.",
            f"  commonest: {top}" + (f" (+{tail} more distinct)" if tail else ""),
        ]
    return "\n".join(lines)
