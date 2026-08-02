"""Record one Meshtastic MQTT protobuf fixture.

Set MQTT settings in .env before running this tool.
The tool writes no channel key to the fixture.
"""

import argparse
import asyncio
import base64
import json
from datetime import UTC, datetime
from pathlib import Path

from sonoran.config import get_settings
from sonoran.crypto.decrypt import decode_key, decrypt_packet
from sonoran.decode.envelope import parse_envelope
from sonoran.decode.payloads import decode_data, decode_payload, parse_data
from sonoran.mqtt.client import message_stream


async def record(output: Path, topic_filter: str, portnum_name: str | None) -> None:
    """Record the first matching encrypted protobuf MQTT message."""
    settings = get_settings()
    settings = settings.model_copy(update={"mqtt_topics": [topic_filter]})
    keys = [decode_key(key) for key in settings.channel_keys]
    async for message in message_stream(settings):
        if message.topic.payload_format != "e":
            continue
        try:
            envelope = parse_envelope(message.payload)
            packet = envelope.packet
            if packet.encrypted:
                plaintext, _ = decrypt_packet(
                    packet.encrypted,
                    packet.id,
                    getattr(packet, "from"),
                    keys,
                    validator=lambda value: bool(parse_data(value).SerializeToString()),
                )
                decoded = decode_data(plaintext)
            else:
                decoded = decode_payload(packet.decoded.portnum, packet.decoded.payload)
        except (AttributeError, ValueError):
            continue
        if portnum_name is not None and decoded.portnum_name != portnum_name:
            continue
        fixture = {
            "recorded_at": datetime.now(UTC).isoformat(),
            "topic": message.topic.raw,
            "payload_base64": base64.b64encode(message.payload).decode("ascii"),
        }
        await asyncio.to_thread(
            output.write_text,
            json.dumps(fixture, indent=2) + "\n",
            encoding="utf-8",
        )
        return


def main() -> None:
    """Parse command arguments and record one fixture."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--topic", default="msh/US/AZ/#")
    parser.add_argument("--portnum", help="Record only this port number name.")
    args = parser.parse_args()
    asyncio.run(record(args.output, args.topic, args.portnum))


if __name__ == "__main__":
    main()
