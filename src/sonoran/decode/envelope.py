"""Meshtastic MQTT ServiceEnvelope parsing."""

from dataclasses import dataclass
from typing import Any

from google.protobuf.message import DecodeError, Message

from sonoran.meshtastic import mqtt_pb2


class EnvelopeDecodeError(ValueError):
    """Raised when MQTT bytes do not contain a valid ServiceEnvelope."""


@dataclass(frozen=True)
class ParsedEnvelope:
    """The packet and MQTT metadata from one ServiceEnvelope."""

    packet: Message
    channel_id: str
    gateway_id: str
    raw_packet: bytes


def parse_envelope(payload: bytes) -> ParsedEnvelope:
    """Parse one MQTT ServiceEnvelope."""
    envelope: Any = mqtt_pb2.ServiceEnvelope()  # type: ignore[attr-defined]
    try:
        envelope.ParseFromString(payload)
    except DecodeError as exc:
        raise EnvelopeDecodeError("invalid ServiceEnvelope protobuf") from exc
    if not envelope.HasField("packet"):
        raise EnvelopeDecodeError("ServiceEnvelope has no MeshPacket")
    return ParsedEnvelope(
        packet=envelope.packet,
        channel_id=envelope.channel_id,
        gateway_id=envelope.gateway_id,
        raw_packet=envelope.packet.SerializeToString(),
    )
