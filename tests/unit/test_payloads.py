"""Tests for Meshtastic Data payload decoders."""

import pytest

from sonoran.decode.payloads import (
    PayloadDecodeError,
    ProtobufPayload,
    TextPayload,
    UnknownPayload,
    decode_data,
    decode_payload,
    parse_data,
)
from sonoran.meshtastic import mesh_pb2, paxcount_pb2, portnums_pb2, telemetry_pb2


@pytest.mark.parametrize(
    ("portnum", "message"),
    [
        (portnums_pb2.NODEINFO_APP, mesh_pb2.User(long_name="Example Node")),
        (portnums_pb2.POSITION_APP, mesh_pb2.Position(latitude_i=330000000)),
        (portnums_pb2.TELEMETRY_APP, telemetry_pb2.Telemetry(time=1)),
        (portnums_pb2.NEIGHBORINFO_APP, mesh_pb2.NeighborInfo(node_id=1)),
        (portnums_pb2.TRACEROUTE_APP, mesh_pb2.RouteDiscovery(route=[1, 2])),
        (portnums_pb2.PAXCOUNTER_APP, paxcount_pb2.Paxcount(wifi=1)),
    ],
)
def test_decode_protobuf_payload(portnum: int, message: object) -> None:
    """Supported protobuf port numbers produce typed payloads."""
    result = decode_payload(portnum, message.SerializeToString())  # type: ignore[attr-defined]

    assert isinstance(result, ProtobufPayload)
    assert result.portnum == portnum
    assert result.message.SerializeToString() == message.SerializeToString()  # type: ignore[attr-defined]


def test_decode_text_payload() -> None:
    """Text messages decode as UTF-8."""
    result = decode_payload(portnums_pb2.TEXT_MESSAGE_APP, b"hello")

    assert result == TextPayload(portnums_pb2.TEXT_MESSAGE_APP, "TEXT_MESSAGE_APP", "hello")


def test_parse_and_decode_data() -> None:
    """Decrypted Data bytes select the matching payload decoder."""
    data = mesh_pb2.Data(portnum=portnums_pb2.TEXT_MESSAGE_APP, payload=b"hello")

    parsed = parse_data(data.SerializeToString())

    assert parsed.SerializeToString() == data.SerializeToString()
    assert decode_data(data.SerializeToString()) == TextPayload(
        portnums_pb2.TEXT_MESSAGE_APP,
        "TEXT_MESSAGE_APP",
        "hello",
    )


def test_parse_data_rejects_bad_protobuf() -> None:
    """Malformed decrypted bytes are a decode error."""
    with pytest.raises(PayloadDecodeError, match="invalid Data"):
        parse_data(bytes([0xFF]))


def test_decode_unknown_payload() -> None:
    """Unknown port numbers preserve their raw bytes."""
    result = decode_payload(999, b"unknown")

    assert result == UnknownPayload(999, "UNKNOWN_999", b"unknown")


def test_decode_text_rejects_invalid_utf8() -> None:
    """Text packets with invalid UTF-8 are decode errors."""
    with pytest.raises(PayloadDecodeError, match="not UTF-8"):
        decode_payload(portnums_pb2.TEXT_MESSAGE_APP, bytes([0xFF]))
