"""A stored portnum of 0 is four different events (#157).

`UNKNOWN_PORTNUM = 0` is the sentinel the ingest writes for a packet it
could not read, and 0 is also the real port number `UNKNOWN_APP`. The
node page's traffic chart labels both "UNKNOWN_APP".

`sonoran.ingest.census` tells them apart by decrypting
`Packet.raw_bytes` again, which is the correction to my own earlier
advice on #157: the bytes needed to answer it have been on disk since
ingest, so it is a query and not a day of logging.

Every test here builds real MeshPackets and encrypts them with real
keys. The false-accept case is not simulated at all -- it is found by
handing the classifier packets encrypted under a key it was not given,
until one of them decrypts into something that parses.
"""

import base64
from dataclasses import fields

from sonoran.crypto.decrypt import decrypt_with_key
from sonoran.decode.payloads import mesh_pb2
from sonoran.ingest import census as census_module
from sonoran.ingest.census import (
    DECODED_EMPTY,
    DECODED_WITH_PAYLOAD,
    OPAQUE,
    PKI,
    PLAINTEXT,
    UNPARSEABLE,
    Census,
    Verdict,
    classify,
    report,
)
from sonoran.ingest.pipeline import _valid_data

# OURS is the public default channel key of Meshtastic (PSK `AQ==`).
# THEIRS is a key the classifier is not given. It only encrypts packets
# built in this file, so any key that is not OURS does the job. It is
# bytes 0 to 15, so nobody can take it for the key of a real channel.
OURS = base64.b64decode("1PG7OiApB1nwvP+rz05pAQ==")
THEIRS = bytes(range(16))

SENDER = 0x0000ABCD


def _data(portnum: int = 0, payload: bytes = b"", **extra: object) -> object:
    data = mesh_pb2.Data()
    data.portnum = portnum
    data.payload = payload
    for name, value in extra.items():
        setattr(data, name, value)
    return data


def _packet(plaintext: bytes, key: bytes, packet_id: int = 0x11223344) -> bytes:
    """One MeshPacket, encrypted, serialised exactly as ingest stores it."""
    packet = mesh_pb2.MeshPacket()
    setattr(packet, "from", SENDER)
    packet.id = packet_id
    packet.encrypted = decrypt_with_key(plaintext, packet_id, SENDER, key)
    return bytes(packet.SerializeToString())


# ------------------------------------------------- the four populations


def test_a_real_unknown_app_packet_reads_back_as_one() -> None:
    """The positive control everything else here is measured against.

    Without it, a classifier that returned `opaque` for everything would
    satisfy every other assertion in this file.
    """
    raw = _packet(bytes(_data(payload=b"\x01\x02\x03").SerializeToString()), OURS)
    verdict = classify(raw, [OURS])
    assert verdict.kind == DECODED_WITH_PAYLOAD
    assert verdict.portnum == 0
    assert verdict.payload_bytes == 3


def test_a_channel_we_hold_no_key_for_is_opaque_and_not_unknown_app() -> None:
    """Both arms asserted, because one of them silent proves nothing.

    The same packet is classified twice: once without its key, where it
    must be opaque, and once with it, where it must read back. A
    classifier that failed to decrypt anything at all would pass the
    first assertion on its own.
    """
    raw = _packet(bytes(_data(payload=b"\x01\x02\x03").SerializeToString()), THEIRS)
    assert classify(raw, [OURS]).kind == OPAQUE
    assert classify(raw, [THEIRS]).kind == DECODED_WITH_PAYLOAD


def test_a_direct_message_is_not_counted_as_a_missing_key() -> None:
    """PKI packets are encrypted to one recipient and never readable.

    Counting them as "no key opened it" would make a healthy mesh look
    like one with a key problem.
    """
    packet = mesh_pb2.MeshPacket()
    setattr(packet, "from", SENDER)
    packet.id = 7
    packet.pki_encrypted = True
    packet.encrypted = b"\x00" * 32
    assert classify(bytes(packet.SerializeToString()), [OURS]).kind == PKI


def test_a_packet_that_arrived_in_the_clear_is_read_directly() -> None:
    packet = mesh_pb2.MeshPacket()
    setattr(packet, "from", SENDER)
    packet.id = 9
    packet.decoded.portnum = 0
    packet.decoded.payload = b"\xde\xad"
    verdict = classify(bytes(packet.SerializeToString()), [OURS])
    assert verdict.kind == PLAINTEXT
    assert verdict.payload_bytes == 2


def test_rows_with_nothing_stored_are_their_own_answer() -> None:
    """An older row with no `raw_bytes` is unmeasurable, not opaque.

    Folding it into any other bucket would put a gap in the data into a
    number somebody reads as a finding.
    """
    assert classify(None, [OURS]).kind == "no_raw_bytes_stored"
    assert classify(b"", [OURS]).kind == "no_raw_bytes_stored"
    assert classify(b"\xff\xff\xff\xff", [OURS]).kind == UNPARSEABLE


# --------------------------------------------------- the false accepts


def _false_accepts(limit: int) -> list[Verdict]:
    """Real false accepts, found rather than simulated.

    Packets are encrypted under a key the classifier is not given, with
    a different packet ID each time, which is a different keystream and
    so a different random plaintext. Roughly 1 in 800 of those parses
    as a `Data` -- that is the defect #157 is about. Deterministic:
    fixed keys, fixed sender, consecutive IDs.
    """
    plaintext = bytes(_data(portnum=1, payload=b"hello mesh").SerializeToString())
    found: list[Verdict] = []
    for packet_id in range(1, 60_000):
        verdict = classify(_packet(plaintext, THEIRS, packet_id), [OURS])
        if verdict.kind in (DECODED_EMPTY, DECODED_WITH_PAYLOAD):
            found.append(verdict)
            if len(found) == limit:
                break
    return found


def test_false_accepts_are_now_rare_enough_that_the_census_cannot_find_them() -> None:
    """#157 is FIXED, and this test is the evidence.

    It used to demand 25 false accepts out of 60,000 wrong-key packets
    and assert that 96% of them had an empty payload -- the signature
    the proposed mitigation keyed on.

    The mitigation shipped is a different and better one: the validator
    now requires that the known fields alone reproduce the input, so
    random bytes decoding into unknown field numbers no longer pass.
    Measured over 40,000 random plaintexts per length, 12 to 64 bytes,
    the rate went from 2.025% at its worst to 0.0025%.

    So the census can no longer find false accepts to classify, and
    that is the point. The assertion is inverted: finding a crowd of
    them again means the validator has been loosened.
    """
    found = _false_accepts(limit=25)
    assert len(found) <= 2, (
        f"{len(found)} false accepts turned up in 60,000 wrong-key packets. "
        f"After #157 the expected number is 0 to 1. The "
        f"discard-unknown-fields round trip has been weakened or removed"
    )


def test_the_census_still_reads_a_real_packet(**_: object) -> None:
    """The positive control the test above needs.

    "We found no false accepts" and "the classifier is broken" look
    identical from the outside. This asserts the same classifier still
    reads a genuine packet, in the same run.
    """
    raw = _packet(bytes(_data(payload=b"\x01\x02\x03").SerializeToString()), OURS)
    assert classify(raw, [OURS]).kind == DECODED_WITH_PAYLOAD


def test_a_genuinely_empty_data_can_never_have_been_ingested() -> None:
    """Which is why an empty payload is a usable signature at all.

    `Data(portnum=0, payload=b"")` serialises to zero bytes, and
    `_valid_data` requires a non-empty serialisation. So a real
    UNKNOWN_APP packet carrying nothing is already dropped by the
    ingest, and every empty-payload row a key opens got there through
    unknown fields -- the fingerprint of random bytes.
    """
    assert bytes(_data().SerializeToString()) == b""
    assert not _valid_data(b"")


# -------------------------------------------------------- the counting


def test_the_cost_of_the_rule_is_only_the_real_packets() -> None:
    """The number #157 needs: what the fix would throw away.

    Rejecting portnum 0 outright was measured at 8,841 real packets a
    week. This counts what the narrower rule costs, and it must count
    only packets with a payload -- counting the empty ones would report
    the false accepts as a cost of removing them.
    """
    counts = Census()
    for _ in range(9):
        counts.add(Verdict(DECODED_EMPTY, portnum=0, payload_bytes=0))
    for _ in range(2):
        counts.add(Verdict(DECODED_WITH_PAYLOAD, portnum=0, payload_bytes=12))
    counts.add(Verdict(OPAQUE))
    counts.add(Verdict(PKI))
    assert counts.total == 13
    assert counts.readable == 11
    assert counts.cost_of_the_empty_payload_rule() == 2


def test_an_empty_window_says_so_instead_of_reporting_zero_percent() -> None:
    """Nothing measured is not the same answer as nothing found."""
    text = report(Census(), window_hours=168, keys_tried=1)
    assert "Nothing measured" in text
    assert "%" not in text


def test_the_report_can_go_into_a_public_issue() -> None:
    """It is written to be pasted into #157, which is public.

    A verdict carries a kind, a port number and a length. No node ID,
    no packet ID and no payload bytes, so there is nothing in a census
    that could identify a person even if the report changed.
    """
    kinds = {field.name: field.type for field in fields(Verdict)}
    assert set(kinds) == {"kind", "portnum", "payload_bytes"}
    assert "bytes" not in " ".join(str(value) for value in kinds.values())


def test_the_census_validates_exactly_as_the_ingest_does() -> None:
    """A second validator would measure a population ingest never made.

    The census must import the pipeline's own `_valid_data`, not carry
    a copy that can drift away from it.
    """
    source = census_module.__doc__ or ""
    assert "_valid_data" in source, "the docstring no longer explains the coupling"
    import inspect

    code = inspect.getsource(census_module)
    assert "from sonoran.ingest.pipeline import" in code
    assert "def _valid_data" not in code, "the census grew its own validator"


def test_the_report_states_the_cost_the_issue_needs() -> None:
    """The report is what a human pastes into #157, so its wording counts.

    Three things have to survive: the four populations with their
    shares, the empty-payload share of what a key opened, and the cost
    of the proposed rule in packets. A report that dropped the last one
    would look complete and answer a different question.
    """
    counts = Census()
    for _ in range(96):
        counts.add(Verdict(DECODED_EMPTY, portnum=0, payload_bytes=0))
    for _ in range(4):
        counts.add(Verdict(DECODED_WITH_PAYLOAD, portnum=0, payload_bytes=12))
    for _ in range(10):
        counts.add(Verdict(OPAQUE))
    counts.add(Verdict(PKI))

    text = report(counts, window_hours=168, keys_tried=2)
    assert "2 channel key(s) tried in ingest order" in text
    assert "last 168 h" in text
    assert DECODED_EMPTY in text and OPAQUE in text and PKI in text
    assert "96.0%" in text, "the empty-payload share of what a key opened is missing"
    assert "Cost of rejecting portnum 0 with an empty payload: 4 real packets" in text
    assert "payload   12 bytes" in text, "the length histogram lost its non-empty rows"


def test_a_window_where_no_key_opened_anything_says_so() -> None:
    """Zero readable rows is a real state, and it is not zero percent.

    Dividing by `readable` would raise here. Reporting 0% would say the
    false-accept rate was measured and found to be nothing.
    """
    counts = Census()
    for _ in range(5):
        counts.add(Verdict(OPAQUE))
    text = report(counts, window_hours=24, keys_tried=1)
    assert "none, so this window says nothing about the false-accept rate" in text
    assert "Cost of rejecting" not in text


def test_a_key_change_mid_window_is_reported_and_bounded() -> None:
    """Every row was selected on portnum 0, so the same keys reproduce it.

    A different answer means the key list moved between ingest and now,
    which makes the window span two configurations — worth saying, and
    worth bounding, since an unbounded dump of a long tail is output
    nobody reads.
    """
    counts = Census()
    for port in range(1, 26):
        counts.add(Verdict(DECODED_WITH_PAYLOAD, portnum=port, payload_bytes=3))
    text = report(counts, window_hours=24, keys_tried=1)
    assert "25 rows no longer decrypt to portnum 0" in text
    assert "(+15 more distinct)" in text, "the long tail is dumped in full"
