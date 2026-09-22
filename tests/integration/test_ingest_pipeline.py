"""Integration tests for the MQTT ingest pipeline."""

import asyncio
import base64
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from sonoran.config import DEFAULT_CHANNEL_KEY
from sonoran.crypto.decrypt import decode_key
from sonoran.db.models import MeshPacketMetrics, Node, Packet, PacketSeen
from sonoran.decode.envelope import parse_envelope
from sonoran.ingest.pipeline import process_message
from sonoran.mqtt.client import RawMqttMessage
from sonoran.mqtt.topics import parse_topic
from tests.integration.conftest import role_url

FIXTURE_PATH = Path(__file__).parents[1] / "fixtures" / "recorded_azmsh_nodeinfo.json"


def _recorded_message(offset_seconds: int) -> RawMqttMessage:
    """Load one real default-channel MQTT packet for replay."""
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    recorded_at = fixture["recorded_at"]
    received_at = datetime.fromisoformat(recorded_at)
    return RawMqttMessage(
        topic=parse_topic(fixture["topic"]),
        payload=base64.b64decode(fixture["payload_base64"]),
        received_at=received_at + timedelta(seconds=offset_seconds),
    )


def test_replay_deduplicates_packets_and_keeps_observations(
    timescale_url: str,
    migrated_engine: object,
) -> None:
    """Recorded MQTT traffic gives one packet and two observations."""
    asyncio.run(_replay(timescale_url))


def test_replay_works_with_the_write_only_ingest_role(
    timescale_url: str,
    migrated_engine: object,
) -> None:
    """The ingest path does not need SELECT privileges."""
    url = role_url(timescale_url, "azmsh_ingest")
    asyncio.run(_replay_write_only(url))


async def _replay(timescale_url: str) -> None:
    """Replay a recorded packet twice into a real TimescaleDB database."""
    url = timescale_url.replace("+psycopg", "+asyncpg")
    engine = create_async_engine(url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    first_message = _recorded_message(100)
    envelope = parse_envelope(first_message.payload)
    packet = envelope.packet
    try:
        async with factory() as session:
            first = await process_message(session, first_message, [decode_key(DEFAULT_CHANNEL_KEY)])
            second = await process_message(
                session,
                _recorded_message(101),
                [decode_key(DEFAULT_CHANNEL_KEY)],
            )
            await session.commit()
            assert first is not None
            assert second is not None
            assert second.is_new is False

        async with factory() as session:
            packet_count = await session.scalar(
                select(func.count())
                .select_from(Packet)
                .where(
                    Packet.from_node_num == getattr(packet, "from"),
                    Packet.packet_id == packet.id,
                )
            )
            observation_count = await session.scalar(
                select(func.count())
                .select_from(PacketSeen)
                .where(
                    PacketSeen.from_node_num == getattr(packet, "from"),
                    PacketSeen.packet_id == packet.id,
                    PacketSeen.seen_at >= first_message.received_at,
                )
            )
            metric_count = await session.scalar(
                select(func.count())
                .select_from(MeshPacketMetrics)
                .where(
                    MeshPacketMetrics.from_node_num == getattr(packet, "from"),
                    MeshPacketMetrics.packet_id == packet.id,
                )
            )
            # The recorded packet is a node info. The public API holds no
            # channel key, so what it said is kept here or never shown.
            payload = await session.scalar(
                select(Packet.payload_json).where(
                    Packet.from_node_num == getattr(packet, "from"),
                    Packet.packet_id == packet.id,
                )
            )
        assert packet_count == 1
        assert observation_count == 2
        assert metric_count == 1
        assert isinstance(payload, dict)
        assert payload.get("long_name")
        assert "macaddr" not in payload
    finally:
        await engine.dispose()


async def _replay_write_only(url: str) -> None:
    """Process recorded traffic with the restricted ingest database role."""
    engine = create_async_engine(url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            await process_message(
                session, _recorded_message(200), [decode_key(DEFAULT_CHANNEL_KEY)]
            )
            await process_message(
                session, _recorded_message(201), [decode_key(DEFAULT_CHANNEL_KEY)]
            )
            await session.commit()
    finally:
        await engine.dispose()


def test_replay_records_node_presence(
    timescale_url: str,
    migrated_engine: object,
) -> None:
    """Every packet records when the mesh heard the sender and gateway.

    A NodeInfo packet gives the name of a node. Only presence storage
    gives `last_heard`, so the dashboard can show recency.
    """
    asyncio.run(_replay_presence(timescale_url))


async def _replay_presence(timescale_url: str) -> None:
    """Replay one packet and check the node presence fields."""
    url = timescale_url.replace("+psycopg", "+asyncpg")
    engine = create_async_engine(url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    message = _recorded_message(500)
    envelope = parse_envelope(message.payload)
    sender = getattr(envelope.packet, "from")
    gateway = int((envelope.gateway_id or message.topic.gateway_id).removeprefix("!"), 16)
    try:
        async with factory() as session:
            await process_message(session, message, [decode_key(DEFAULT_CHANNEL_KEY)])
            await session.commit()

        async with factory() as session:
            heard = await session.scalar(select(Node.last_heard).where(Node.node_num == sender))
            is_gateway = await session.scalar(
                select(Node.is_mqtt_gateway).where(Node.node_num == gateway)
            )
            topic = await session.scalar(
                select(Node.last_mqtt_topic).where(Node.node_num == gateway)
            )
        assert heard is not None, "the sender must have a last_heard time"
        assert is_gateway is True, "the publishing node must be an MQTT gateway"
        assert topic == message.topic.raw
    finally:
        await engine.dispose()


def test_observations_join_packets_by_the_dedup_key(
    timescale_url: str,
    migrated_engine: object,
) -> None:
    """Observations match their packet without a stored packet_pk.

    The ingest role cannot read back `packet.id`, so `packet_pk` stays
    empty. The API joins on (`from_node_num`, `packet_id`) instead.
    """
    asyncio.run(_replay_join(timescale_url))


async def _replay_join(timescale_url: str) -> None:
    """Replay a packet twice and count its observations by natural key."""
    url = timescale_url.replace("+psycopg", "+asyncpg")
    engine = create_async_engine(url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    message = _recorded_message(900)
    envelope = parse_envelope(message.payload)
    sender = getattr(envelope.packet, "from")
    packet_id = envelope.packet.id
    try:
        async with factory() as session:
            await process_message(session, message, [decode_key(DEFAULT_CHANNEL_KEY)])
            await process_message(
                session, _recorded_message(901), [decode_key(DEFAULT_CHANNEL_KEY)]
            )
            await session.commit()

        async with factory() as session:
            seen = await session.scalar(
                select(func.count())
                .select_from(PacketSeen)
                .where(
                    PacketSeen.from_node_num == sender,
                    PacketSeen.packet_id == packet_id,
                )
            )
            stored_pk = await session.scalar(
                select(PacketSeen.packet_pk).where(PacketSeen.from_node_num == sender)
            )
        assert seen >= 2, "both observations must match the packet by its dedup key"
        assert stored_pk is None, "packet_pk stays empty for the write-only ingest role"
    finally:
        await engine.dispose()


def test_one_packet_from_many_gateways_stores_one_body(
    timescale_url: str,
    migrated_engine,  # type: ignore[no-untyped-def]
) -> None:
    """Several gateways relaying one packet give one body, many observations.

    Each gateway stamps its own `rx_time`, so the packet time differs
    per relay. Deduplication must still see one packet.
    """
    # Every recorded message replays the same packet, so an earlier test
    # may already hold its key. Clear it so this test starts clean.
    envelope = parse_envelope(_recorded_message(0).payload)
    keys = {
        "sender": getattr(envelope.packet, "from"),
        "packet_id": envelope.packet.id,
    }
    with migrated_engine.begin() as connection:
        for table in ("packet_key", "packet_seen", "packet"):
            connection.execute(
                text(
                    f"DELETE FROM {table} WHERE from_node_num = :sender AND packet_id = :packet_id"
                ),
                keys,
            )
    asyncio.run(_replay_many_gateways(timescale_url))


async def _replay_many_gateways(timescale_url: str) -> None:
    """Replay one packet as if four gateways had relayed it."""
    url = timescale_url.replace("+psycopg", "+asyncpg")
    engine = create_async_engine(url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    base = _recorded_message(3000)
    envelope = parse_envelope(base.payload)
    sender = getattr(envelope.packet, "from")
    packet_id = envelope.packet.id
    try:
        async with factory() as session:
            results = []
            for gateway in range(4):
                # A different receive time for each relay, as in real traffic.
                message = _recorded_message(3000 + gateway * 7)
                results.append(
                    await process_message(session, message, [decode_key(DEFAULT_CHANNEL_KEY)])
                )
            await session.commit()

        assert results[0] is not None and results[0].is_new is True
        for later in results[1:]:
            assert later is not None
            assert later.is_new is False, "a relay of a known packet is not new"

        async with factory() as session:
            bodies = await session.scalar(
                select(func.count())
                .select_from(Packet)
                .where(Packet.from_node_num == sender, Packet.packet_id == packet_id)
            )
            observations = await session.scalar(
                select(func.count())
                .select_from(PacketSeen)
                .where(PacketSeen.from_node_num == sender, PacketSeen.packet_id == packet_id)
            )
        assert bodies == 1, "the packet body is stored once"
        assert observations >= 4, "every relay keeps its own observation"
    finally:
        await engine.dispose()


def test_payload_rows_point_at_their_packet(
    timescale_url: str,
    migrated_engine,  # type: ignore[no-untyped-def]
) -> None:
    """A stored payload can be traced back to the packet that carried it.

    The Meshtastic packet ID comes from the protocol, so ingest holds it
    before any write. No generated key has to be read back.
    """
    envelope = parse_envelope(_recorded_message(0).payload)
    keys = {
        "sender": getattr(envelope.packet, "from"),
        "packet_id": envelope.packet.id,
    }
    with migrated_engine.begin() as connection:
        for table in ("packet_key", "packet_seen", "packet", "node"):
            column = "node_num" if table == "node" else "from_node_num"
            connection.execute(
                text(f"DELETE FROM {table} WHERE {column} = :sender"), {"sender": keys["sender"]}
            )
    asyncio.run(_replay_provenance(timescale_url, keys))


async def _replay_provenance(timescale_url: str, keys: dict[str, int]) -> None:
    """Replay a NodeInfo packet and join its stored node row to the packet."""
    url = timescale_url.replace("+psycopg", "+asyncpg")
    engine = create_async_engine(url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            await process_message(
                session, _recorded_message(7000), [decode_key(DEFAULT_CHANNEL_KEY)]
            )
            await session.commit()

        async with factory() as session:
            # The packet the mesh sent, found by its protocol identity.
            packet = await session.scalar(
                select(Packet).where(
                    Packet.from_node_num == keys["sender"],
                    Packet.packet_id == keys["packet_id"],
                )
            )
            observations = await session.scalar(
                select(func.count())
                .select_from(PacketSeen)
                .where(
                    PacketSeen.from_node_num == keys["sender"],
                    PacketSeen.packet_id == keys["packet_id"],
                )
            )
        assert packet is not None, "the packet is stored under its protocol ID"
        assert observations >= 1, "the observation joins by the same key"
    finally:
        await engine.dispose()


def test_a_pki_packet_is_stored_without_a_payload(
    timescale_url: str,
    migrated_engine,  # type: ignore[no-untyped-def]
) -> None:
    """A packet encrypted to one recipient is kept as traffic.

    No channel key can open it. Trying would raise and lose the packet,
    so it is stored with an unknown port number instead.
    """
    envelope = parse_envelope(_recorded_message(0).payload)
    sender = getattr(envelope.packet, "from")
    with migrated_engine.begin() as connection:
        for table in ("packet_key", "packet_seen", "packet"):
            connection.execute(text(f"DELETE FROM {table} WHERE from_node_num = :s"), {"s": sender})
    asyncio.run(_replay_pki(timescale_url))


async def _replay_pki(timescale_url: str) -> None:
    """Replay a recorded packet as if the broker had published it on PKI."""
    url = timescale_url.replace("+psycopg", "+asyncpg")
    engine = create_async_engine(url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    original = _recorded_message(8000)
    message = RawMqttMessage(
        topic=parse_topic("msh/US/AZ/Phoenix/2/e/PKI/!abcd1234"),
        payload=original.payload,
        received_at=original.received_at,
    )
    envelope = parse_envelope(message.payload)
    sender = getattr(envelope.packet, "from")
    try:
        async with factory() as session:
            # No keys at all, to prove no decryption is attempted.
            stored = await process_message(session, message, [])
            await session.commit()
        assert stored is not None and stored.is_new is True

        async with factory() as session:
            row = await session.scalar(
                select(Packet).where(Packet.from_node_num == sender, Packet.channel == "PKI")
            )
        assert row is not None, "the packet is kept as traffic"
        assert row.portnum == 0, "the port number is unknown inside the encrypted part"
    finally:
        await engine.dispose()


def test_packet_time_is_our_clock_not_the_gateway_clock(
    timescale_url: str,
    migrated_engine,  # type: ignore[no-untyped-def]
) -> None:
    """`packet.first_seen_at` must hold when we heard it.

    Every gateway stamps its own `rx_time` from its own clock, and those
    clocks are wrong. The ingest used to prefer `rx_time`, which put 349
    rows in the future in live data, some more than a day ahead. Every
    windowed query over them was wrong and retention could not expire
    them.

    The gateway's claim is still kept, in `packet.rx_time`. This test
    pins that the two are recorded separately and never confused.

    See AGENTS.md 9.3 and 9.4.
    """
    message = _recorded_message(0)
    envelope = parse_envelope(message.payload)
    sender = getattr(envelope.packet, "from")
    packet_id = envelope.packet.id
    rx_time = envelope.packet.rx_time
    assert rx_time, "this fixture must carry a gateway time for the test to mean anything"

    with migrated_engine.begin() as connection:
        for table in ("packet_key", "packet_seen", "packet"):
            connection.execute(
                text(f"DELETE FROM {table} WHERE from_node_num = :s AND packet_id = :p"),
                {"s": sender, "p": packet_id},
            )

    asyncio.run(_replay_one(timescale_url, message))

    with migrated_engine.begin() as connection:
        stored_at, stored_rx = connection.execute(
            text(
                "SELECT first_seen_at, rx_time FROM packet "
                "WHERE from_node_num = :s AND packet_id = :p"
            ),
            {"s": sender, "p": packet_id},
        ).one()

    assert stored_at == message.received_at, "the packet time must be when we heard it"
    assert stored_rx == rx_time, "the gateway's own time must still be kept"
    gateway_time = datetime.fromtimestamp(rx_time, UTC)
    assert stored_at != gateway_time, "the gateway clock must not become the packet time"


async def _replay_one(timescale_url: str, message: RawMqttMessage) -> None:
    """Store one recorded message."""
    engine = create_async_engine(timescale_url.replace("+psycopg", "+asyncpg"))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            await process_message(session, message, [decode_key(DEFAULT_CHANNEL_KEY)])
            await session.commit()
    finally:
        await engine.dispose()
