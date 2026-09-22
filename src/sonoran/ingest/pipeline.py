"""The MQTT to database ingest pipeline."""

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from sonoran.config import get_settings
from sonoran.crypto.decrypt import decode_key, decrypt_packet
from sonoran.db.session import make_engine, make_session_factory
from sonoran.decode.envelope import ParsedEnvelope, parse_envelope
from sonoran.decode.payloads import decode_payload, parse_data
from sonoran.decode.stored import stored_payload
from sonoran.ingest.dedup import ObservationInput, PacketInput, StoredPacket, store_packet
from sonoran.ingest.handlers import HandlerContext, store_mesh_packet_metrics, store_payload
from sonoran.ingest.handlers.presence import store_gateway, store_heard
from sonoran.logging import configure_logging, get_logger
from sonoran.mqtt.client import RawMqttMessage, message_stream

logger = get_logger(__name__)

# The broker channel for packets encrypted to one recipient.
PKI_CHANNEL = "PKI"

# The port number sits inside the encrypted part, so it is unknown.
UNKNOWN_PORTNUM = 0


def _node_num(node_id: str) -> int:
    """Convert a Meshtastic node ID to its node number."""
    return int(node_id.removeprefix("!"), 16)


def heard_at(message: RawMqttMessage) -> datetime:
    """Return when this process received a message.

    This is the only acceptable answer to "when did we hear this", and
    the reason is worth keeping in front of whoever reads this next.

    A packet carries `rx_time`, stamped by whichever gateway relayed it,
    from that gateway's own clock. Those clocks are wrong. This function
    used to prefer `rx_time`, and live data ended up holding 349 packet
    rows dated in the future, the furthest more than a day ahead. Every
    windowed query over those rows was wrong, and retention could not
    expire them.

    Nothing is lost by ignoring it here. The gateway's claim is stored
    on its own, in `packet.rx_time`, for anybody who wants to compare
    the two.

    See AGENTS.md 9.3 and 9.4.
    """
    return message.received_at


def _valid_data(payload: bytes) -> bool:
    """Return true when bytes parse as a non-empty Data protobuf."""
    try:
        return bool(parse_data(payload).SerializeToString())
    except ValueError:
        return False


def _is_pki(packet: object, message: RawMqttMessage) -> bool:
    """Return true when a packet is encrypted to one recipient.

    The broker publishes these on a PKI channel. The packet also carries
    a flag, which is the reliable test when the topic does not say.
    """
    return bool(getattr(packet, "pki_encrypted", False)) or message.topic.channel == PKI_CHANNEL


async def _store_opaque(
    session: AsyncSession,
    message: RawMqttMessage,
    envelope: ParsedEnvelope,
    from_node_num: int,
) -> StoredPacket:
    """Store a packet whose payload cannot be read.

    The port number is unknown, because it sits inside the encrypted
    part. The packet still counts as traffic, and both nodes were still
    heard, so presence is recorded.
    """
    packet = envelope.packet
    packet_input = PacketInput(
        from_node_num=from_node_num,
        packet_id=packet.id,
        to_node_num=packet.to or None,
        portnum=UNKNOWN_PORTNUM,
        channel=message.topic.channel,
        hop_start=packet.hop_start or None,
        hop_limit=packet.hop_limit or None,
        want_ack=packet.want_ack,
        priority=packet.priority or None,
        rx_time=packet.rx_time or None,
        first_seen_at=heard_at(message),
        raw_bytes=envelope.raw_packet,
    )
    observation_input = ObservationInput(
        gateway_node_num=_node_num(envelope.gateway_id or message.topic.gateway_id or ""),
        mqtt_topic=message.topic.raw,
        channel=message.topic.channel,
        rx_rssi=packet.rx_rssi or None,
        rx_snr=packet.rx_snr or None,
        hop_limit=packet.hop_limit or None,
        seen_at=message.received_at,
    )
    stored = await store_packet(session, packet_input, observation_input)
    await store_heard(session, from_node_num, observation_input.seen_at, packet_input.channel)
    await store_gateway(
        session,
        observation_input.gateway_node_num,
        observation_input.seen_at,
        observation_input.mqtt_topic,
    )
    return stored


async def process_message(
    session: AsyncSession,
    message: RawMqttMessage,
    keys: list[bytes],
    store_text_messages: bool = False,
) -> StoredPacket | None:
    """Decrypt, decode, and store one encrypted MQTT message."""
    if message.topic.payload_format != "e":
        return None
    envelope = parse_envelope(message.payload)
    packet = envelope.packet
    from_node_num = getattr(packet, "from")

    # A PKI packet is encrypted to one recipient with its public key. No
    # channel key can open it, and only the recipient ever could. Store
    # the packet as traffic and stop there. Trying to decrypt it would
    # raise on every message and lose the packet.
    if _is_pki(packet, message):
        return await _store_opaque(session, message, envelope, from_node_num)

    if packet.encrypted:
        plaintext, _ = decrypt_packet(
            packet.encrypted,
            packet.id,
            from_node_num,
            keys,
            validator=_valid_data,
        )
        data = parse_data(plaintext)
        decoded = decode_payload(data.portnum, data.payload)
    else:
        data = packet.decoded
        decoded = decode_payload(data.portnum, data.payload)

    packet_input = PacketInput(
        from_node_num=from_node_num,
        packet_id=packet.id,
        to_node_num=packet.to or None,
        portnum=decoded.portnum,
        channel=message.topic.channel,
        hop_start=packet.hop_start or None,
        hop_limit=packet.hop_limit or None,
        want_ack=packet.want_ack,
        priority=packet.priority or None,
        rx_time=packet.rx_time or None,
        first_seen_at=heard_at(message),
        raw_bytes=envelope.raw_packet,
        # The public API cannot decrypt, so what the packet carried is
        # kept here for the families that have no table of their own.
        payload_json=stored_payload(decoded),
    )
    observation_input = ObservationInput(
        gateway_node_num=_node_num(envelope.gateway_id or message.topic.gateway_id or ""),
        mqtt_topic=message.topic.raw,
        channel=message.topic.channel,
        rx_rssi=packet.rx_rssi or None,
        rx_snr=packet.rx_snr or None,
        hop_limit=packet.hop_limit or None,
        seen_at=message.received_at,
    )
    stored = await store_packet(session, packet_input, observation_input)

    # Presence comes from every message, not only from a new packet. A
    # repeat of a packet still proves the mesh heard both nodes.
    await store_heard(session, from_node_num, observation_input.seen_at, packet_input.channel)
    await store_gateway(
        session,
        observation_input.gateway_node_num,
        observation_input.seen_at,
        observation_input.mqtt_topic,
    )

    if stored.is_new:
        await store_mesh_packet_metrics(
            session,
            packet,
            stored.packet_pk,
            observation_input.gateway_node_num,
            packet_input.first_seen_at,
            len(message.payload),
        )
        await store_payload(
            session,
            decoded,
            HandlerContext(
                packet_pk=stored.packet_pk,
                packet_id=packet_input.packet_id,
                request_id=data.request_id or None,
                from_node_num=from_node_num,
                to_node_num=packet.to or None,
                channel=message.topic.channel,
                reply_id=data.reply_id or None,
                emoji=bool(data.emoji),
                store_text_messages=store_text_messages,
                seen_at=packet_input.first_seen_at,
            ),
        )
    return stored


async def main() -> None:
    """Run the ingest loop and isolate failures to one MQTT message."""
    settings = get_settings()
    keys = [decode_key(key) for key in settings.channel_keys]
    engine = make_engine(settings.database_url)
    session_factory = make_session_factory(engine)
    try:
        async for message in message_stream(settings):
            async with session_factory() as session:
                try:
                    stored = await process_message(
                        session,
                        message,
                        keys,
                        settings.store_text_messages,
                    )
                    await session.commit()
                    if stored is not None:
                        logger.info("stored packet=%s new=%s", stored.packet_pk, stored.is_new)
                except Exception:
                    await session.rollback()
                    logger.exception("failed to process MQTT message: %s", message.topic.raw)
    finally:
        await engine.dispose()


def run() -> None:
    """Console script entry point."""
    import asyncio

    configure_logging(get_settings().log_level)
    asyncio.run(main())
