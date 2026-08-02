"""Meshtastic Data payload decoders.

Each decoder is pure. It has no database or network dependency.
"""

from dataclasses import dataclass
from typing import Any

from google.protobuf.message import DecodeError, Message

from sonoran.meshtastic import mesh_pb2, paxcount_pb2, portnums_pb2, telemetry_pb2


class PayloadDecodeError(ValueError):
    """Raised when bytes do not match their declared payload type."""


@dataclass(frozen=True)
class ProtobufPayload:
    """A decoded protobuf payload."""

    portnum: int
    portnum_name: str
    message: Message


@dataclass(frozen=True)
class TextPayload:
    """A decoded text message payload."""

    portnum: int
    portnum_name: str
    body: str


@dataclass(frozen=True)
class UnknownPayload:
    """Payload bytes for a port number with no decoder."""

    portnum: int
    portnum_name: str
    raw: bytes


DecodedPayload = ProtobufPayload | TextPayload | UnknownPayload

_PROTOBUF_TYPES: dict[int, type[Message]] = {
    portnums_pb2.NODEINFO_APP: mesh_pb2.User,  # type: ignore[attr-defined]
    portnums_pb2.POSITION_APP: mesh_pb2.Position,  # type: ignore[attr-defined]
    portnums_pb2.TELEMETRY_APP: telemetry_pb2.Telemetry,  # type: ignore[attr-defined]
    portnums_pb2.NEIGHBORINFO_APP: mesh_pb2.NeighborInfo,  # type: ignore[attr-defined]
    portnums_pb2.TRACEROUTE_APP: mesh_pb2.RouteDiscovery,  # type: ignore[attr-defined]
    portnums_pb2.PAXCOUNTER_APP: paxcount_pb2.Paxcount,  # type: ignore[attr-defined]
}


def _portnum_name(portnum: int) -> str:
    try:
        return portnums_pb2.PortNum.Name(portnum)  # type: ignore[attr-defined]
    except ValueError:
        return f"UNKNOWN_{portnum}"


def _parse_message(message_type: type[Message], payload: bytes) -> Message:
    message: Any = message_type()
    try:
        message.ParseFromString(payload)
    except DecodeError as exc:
        raise PayloadDecodeError("invalid payload protobuf") from exc
    return message


def parse_data(payload: bytes) -> Message:
    """Parse decrypted bytes as a Meshtastic Data message."""
    data: Any = mesh_pb2.Data()  # type: ignore[attr-defined]
    try:
        data.ParseFromString(payload)
    except DecodeError as exc:
        raise PayloadDecodeError("invalid Data protobuf") from exc
    return data


def decode_data(payload: bytes) -> DecodedPayload:
    """Parse a decrypted Data message and decode its selected payload."""
    data: Any = parse_data(payload)
    return decode_payload(data.portnum, data.payload)


def decode_payload(portnum: int, payload: bytes) -> DecodedPayload:
    """Decode payload bytes selected by a Meshtastic port number."""
    portnum_name = _portnum_name(portnum)
    if portnum == portnums_pb2.TEXT_MESSAGE_APP:  # type: ignore[attr-defined]
        try:
            return TextPayload(portnum, portnum_name, payload.decode("utf-8"))
        except UnicodeDecodeError as exc:
            raise PayloadDecodeError("text payload is not UTF-8") from exc

    message_type = _PROTOBUF_TYPES.get(portnum)
    if message_type is None:
        return UnknownPayload(portnum, portnum_name, payload)
    return ProtobufPayload(portnum, portnum_name, _parse_message(message_type, payload))
