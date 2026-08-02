"""MQTT topic parsing.

Meshtastic MQTT topics have this shape:
    msh/{region}/.../{format}/{channel}/{gateway_id}

Example:
    msh/US/AZ/2/e/LongFast/!abcd1234

The format marker is `e` (encrypted protobuf) or `json`.
Some brokers do not include the gateway ID in the topic. The envelope then
contains the gateway ID.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ParsedTopic:
    """The parsed fields of one Meshtastic MQTT topic."""

    raw: str
    region_path: str
    payload_format: str
    channel: str
    gateway_id: str | None


class TopicParseError(ValueError):
    """Raised when a topic does not match the Meshtastic pattern."""


def parse_topic(topic: str) -> ParsedTopic:
    """Parse a Meshtastic MQTT topic into its fields.

    Raises TopicParseError when the topic does not match the pattern.
    """
    parts = topic.split("/")
    if len(parts) < 5 or parts[0] != "msh":
        raise TopicParseError(f"not a Meshtastic topic: {topic!r}")

    if parts[-3] in ("e", "json"):
        gateway_id = parts[-1]
        channel = parts[-2]
        payload_format = parts[-3]
        region_path = "/".join(parts[1:-3])
    else:
        gateway_id = None
        channel = parts[-1]
        payload_format = parts[-2]
        region_path = "/".join(parts[1:-2])

    if payload_format not in ("e", "json"):
        raise TopicParseError(f"unknown payload format in topic: {topic!r}")
    if not channel:
        raise TopicParseError(f"missing channel in topic: {topic!r}")

    return ParsedTopic(
        raw=topic,
        region_path=region_path,
        payload_format=payload_format,
        channel=channel,
        gateway_id=gateway_id,
    )
