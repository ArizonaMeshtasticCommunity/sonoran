"""Read the firmware version out of a map report envelope (#406).

Firmware builds the packet in `MQTT::perhapsReportToMap`
(meshtastic/firmware v2.7.26.54e0d8d src/mqtt/MQTT.cpp): `from` is the
node itself, the payload is decoded (never encrypted), the port is
`MAP_REPORT_APP`, and the envelope's `gateway_id` is the same node.

A packet that breaks any of those is not a map report from firmware,
so it gives nothing. This module does no I/O.
"""

from dataclasses import dataclass
from typing import Any

from google.protobuf.message import DecodeError

from sonoran.decode.envelope import EnvelopeDecodeError, parse_envelope
from sonoran.meshtastic import mqtt_pb2, portnums_pb2


@dataclass(frozen=True)
class MapReportVersion:
    """The node a map report is about, and the version it gave."""

    node_num: int
    firmware_version: str


def map_report_version(payload: bytes) -> MapReportVersion | None:
    """Return the node and version of one map report, or None."""
    try:
        envelope = parse_envelope(payload)
    except EnvelopeDecodeError:
        return None
    packet: Any = envelope.packet
    if packet.WhichOneof("payload_variant") != "decoded":
        return None
    if packet.decoded.portnum != portnums_pb2.MAP_REPORT_APP:  # type: ignore[attr-defined]
        return None
    node_num = getattr(packet, "from")
    # Firmware reports only its own node. A report that names another
    # gateway is not one firmware sent.
    if envelope.gateway_id.lower() != f"!{node_num:08x}":
        return None
    report: Any = mqtt_pb2.MapReport()  # type: ignore[attr-defined]
    try:
        report.ParseFromString(packet.decoded.payload)
    except DecodeError:
        return None
    return MapReportVersion(node_num=node_num, firmware_version=report.firmware_version)
