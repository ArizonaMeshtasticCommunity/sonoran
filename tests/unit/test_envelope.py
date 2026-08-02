"""Tests for MQTT ServiceEnvelope parsing."""

import pytest

from sonoran.decode.envelope import EnvelopeDecodeError, parse_envelope
from sonoran.meshtastic import mesh_pb2, mqtt_pb2


def test_parse_envelope() -> None:
    """A ServiceEnvelope gives its packet and MQTT metadata."""
    packet = mesh_pb2.MeshPacket(**{"from": 1, "to": 2, "id": 3})
    envelope = mqtt_pb2.ServiceEnvelope(
        packet=packet,
        channel_id="LongFast",
        gateway_id="!12345678",
    )

    parsed = parse_envelope(envelope.SerializeToString())

    assert getattr(parsed.packet, "from") == 1
    assert parsed.packet.to == 2
    assert parsed.packet.id == 3
    assert parsed.channel_id == "LongFast"
    assert parsed.gateway_id == "!12345678"
    assert parsed.raw_packet == packet.SerializeToString()


def test_parse_envelope_rejects_missing_packet() -> None:
    """An envelope without a MeshPacket is not valid for ingest."""
    with pytest.raises(EnvelopeDecodeError, match="no MeshPacket"):
        parse_envelope(mqtt_pb2.ServiceEnvelope(channel_id="LongFast").SerializeToString())


def test_parse_envelope_rejects_bad_protobuf() -> None:
    """Malformed protobuf bytes produce a clear error."""
    with pytest.raises(EnvelopeDecodeError, match="invalid"):
        parse_envelope(bytes([0xFF]))
