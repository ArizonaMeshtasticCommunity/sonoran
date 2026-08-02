"""Tests for recorded MQTT fixtures."""

import base64
import json
from pathlib import Path

import pytest

from sonoran.config import DEFAULT_CHANNEL_KEY
from sonoran.crypto.decrypt import decode_key, decrypt_packet
from sonoran.decode.envelope import parse_envelope
from sonoran.decode.payloads import decode_data, decode_payload, parse_data

FIXTURES_DIR = Path(__file__).parents[1] / "fixtures"


@pytest.mark.parametrize(
    ("filename", "portnum_name"),
    [
        ("recorded_nodeinfo.json", "NODEINFO_APP"),
        ("recorded_position.json", "POSITION_APP"),
        ("recorded_telemetry.json", "TELEMETRY_APP"),
        ("recorded_text.json", "TEXT_MESSAGE_APP"),
        ("recorded_traceroute.json", "TRACEROUTE_APP"),
        ("recorded_azmsh_nodeinfo.json", "NODEINFO_APP"),
        ("recorded_azmsh_position.json", "POSITION_APP"),
        ("recorded_azmsh_telemetry.json", "TELEMETRY_APP"),
        ("recorded_azmsh_neighbor.json", "NEIGHBORINFO_APP"),
        ("recorded_azmsh_traceroute.json", "TRACEROUTE_APP"),
    ],
)
def test_recorded_fixture_decodes(filename: str, portnum_name: str) -> None:
    """Each recorded default-channel fixture decodes to its selected family."""
    fixture = json.loads((FIXTURES_DIR / filename).read_text(encoding="utf-8"))
    envelope = parse_envelope(base64.b64decode(fixture["payload_base64"]))
    packet = envelope.packet
    if packet.encrypted:
        plaintext, _ = decrypt_packet(
            packet.encrypted,
            packet.id,
            getattr(packet, "from"),
            [decode_key(DEFAULT_CHANNEL_KEY)],
            validator=lambda value: bool(parse_data(value).SerializeToString()),
        )
        decoded = decode_data(plaintext)
    else:
        decoded = decode_payload(packet.decoded.portnum, packet.decoded.payload)
    assert decoded.portnum_name == portnum_name
