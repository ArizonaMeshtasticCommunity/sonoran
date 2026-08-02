"""MQTT message stream with reconnect."""

import asyncio
import ssl
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

import aiomqtt

from sonoran.config import Settings
from sonoran.logging import get_logger
from sonoran.mqtt.topics import ParsedTopic, TopicParseError, parse_topic

logger = get_logger(__name__)


@dataclass(frozen=True)
class RawMqttMessage:
    """One MQTT message and its parsed topic."""

    topic: ParsedTopic
    payload: bytes
    received_at: datetime


def create_client(settings: Settings) -> aiomqtt.Client:
    """Create a broker client with the Meshtastic broker protocol settings."""
    tls_context = ssl.create_default_context() if settings.mqtt_use_tls else None
    return aiomqtt.Client(
        hostname=settings.mqtt_host,
        port=settings.mqtt_port,
        username=settings.mqtt_username or None,
        password=settings.mqtt_password or None,
        identifier=f"sonoran-{uuid4().hex}",
        protocol=aiomqtt.ProtocolVersion.V311,
        clean_session=True,
        keepalive=settings.mqtt_keepalive,
        tls_context=tls_context,
    )


async def message_stream(settings: Settings) -> AsyncIterator[RawMqttMessage]:
    """Yield MQTT messages and reconnect after a connection error."""
    delay = 1
    while True:
        try:
            async with create_client(settings) as client:
                for topic in settings.mqtt_topics:
                    await client.subscribe(topic)
                delay = 1
                async for message in client.messages:
                    try:
                        parsed_topic = parse_topic(str(message.topic))
                    except TopicParseError:
                        logger.debug("ignore non-packet MQTT topic: %s", message.topic)
                        continue
                    yield RawMqttMessage(
                        topic=parsed_topic,
                        payload=bytes(message.payload),
                        received_at=datetime.now(UTC),
                    )
        except aiomqtt.MqttError as exc:
            logger.warning("MQTT connection failed: %s; retry in %s seconds", exc, delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 60)
