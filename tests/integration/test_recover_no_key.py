"""Recovering packets that were filed as unreadable and can be read now (#252).

This replays the production failure end to end rather than testing the
recovery in isolation. A signed telemetry packet -- the shape NGSP and 48
other senders were sending -- is ingested while no key can open it, so it
is stored exactly as production stored it: ``no_key``, ``portnum`` 0, raw
bytes kept, no telemetry row. Then ``recover`` runs with the key and the
schema that can read it.

The assertions cover the four ways a backfill goes wrong:

- a dry run that writes;
- a recovered packet whose data does not reach its table (the whole point:
  the reader saw stale telemetry, not a wrong ``payload_state``);
- genuinely foreign traffic being "recovered" into nonsense;
- a second run recovering the same packet again.
"""

import asyncio
import os
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from sonoran.config import DEFAULT_CHANNEL_KEY
from sonoran.crypto.decrypt import decode_key, decrypt_with_key
from sonoran.db.models import DeviceMetrics, Packet
from sonoran.ingest.pipeline import process_message
from sonoran.ingest.recover import recover
from sonoran.meshtastic import mesh_pb2, mqtt_pb2, portnums_pb2, telemetry_pb2
from sonoran.mqtt.client import RawMqttMessage
from sonoran.mqtt.topics import parse_topic

SENDER = 0x7E57A11
GATEWAY = "!abcd1234"
TOPIC = f"msh/US/AZ/Phoenix/2/e/MediumFast/{GATEWAY}"
NOW = datetime.now(UTC).replace(microsecond=0)


def _signed_telemetry(packet_id: int, key: bytes, battery: int) -> RawMqttMessage:
    """An encrypted, signed telemetry packet, as newer firmware sends one."""
    telemetry = telemetry_pb2.Telemetry()
    telemetry.time = int(NOW.timestamp())
    telemetry.device_metrics.battery_level = battery
    telemetry.device_metrics.voltage = 4.1

    data = mesh_pb2.Data()
    data.portnum = portnums_pb2.PortNum.TELEMETRY_APP
    data.payload = telemetry.SerializeToString()
    data.bitfield = 1
    data.xeddsa_signature = os.urandom(64)  # field 10: what broke the old schema

    packet = mesh_pb2.MeshPacket()
    setattr(packet, "from", SENDER)
    packet.to = 0xFFFFFFFF
    packet.id = packet_id
    packet.channel = 8
    packet.hop_limit = 3
    packet.hop_start = 3
    # AES-CTR: encrypting and decrypting are the same operation.
    packet.encrypted = decrypt_with_key(data.SerializeToString(), packet_id, SENDER, key)

    envelope = mqtt_pb2.ServiceEnvelope()
    envelope.packet.CopyFrom(packet)
    envelope.channel_id = "MediumFast"
    envelope.gateway_id = GATEWAY
    return RawMqttMessage(
        topic=parse_topic(TOPIC),
        payload=envelope.SerializeToString(),
        received_at=NOW + timedelta(seconds=packet_id % 60),
    )


def test_a_signed_packet_filed_as_no_key_is_recovered(
    timescale_url: str,
    migrated_engine,  # type: ignore[no-untyped-def]
) -> None:
    asyncio.run(_run(timescale_url, migrated_engine))


async def _run(timescale_url: str, migrated_engine) -> None:  # type: ignore[no-untyped-def]
    with migrated_engine.begin() as connection:
        for table in ("device_metrics", "packet_key", "packet_seen", "packet"):
            column = "node_num" if table == "device_metrics" else "from_node_num"
            connection.execute(text(f"DELETE FROM {table} WHERE {column} = :s"), {"s": SENDER})

    engine = create_async_engine(timescale_url.replace("+psycopg", "+asyncpg"))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    mediumfast = decode_key(DEFAULT_CHANNEL_KEY)
    foreign = os.urandom(16)
    since = NOW - timedelta(minutes=5)

    async def state() -> dict[int, tuple[str | None, int]]:
        async with factory() as session:
            rows = await session.execute(
                select(Packet.packet_id, Packet.payload_state, Packet.portnum).where(
                    Packet.from_node_num == SENDER
                )
            )
            return {r.packet_id: (r.payload_state, r.portnum) for r in rows}

    async def batteries() -> list[float | None]:
        async with factory() as session:
            rows = await session.execute(
                select(DeviceMetrics.battery_level).where(DeviceMetrics.node_num == SENDER)
            )
            return [r.battery_level for r in rows]

    try:
        # 1. Stored as production stored it: nothing could open it.
        async with factory() as session:
            await process_message(session, _signed_telemetry(1001, mediumfast, 87), [])
            await process_message(session, _signed_telemetry(1002, foreign, 55), [])
            await session.commit()
        assert await state() == {1001: ("no_key", 0), 1002: ("no_key", 0)}
        assert await batteries() == [], "no telemetry row before recovery"

        # 2. A dry run reports and writes nothing.
        async with factory() as session:
            dry = await recover(
                session, [mediumfast], since, apply=False, store_text_messages=False
            )
            await session.rollback()
        assert dry["recovered:67"] == 1, dry
        assert dry["still_no_key"] == 1, dry
        assert await state() == {1001: ("no_key", 0), 1002: ("no_key", 0)}, (
            "a dry run wrote to the database"
        )

        # 3. Applied: the readable one is recovered and its data reaches its table.
        async with factory() as session:
            done = await recover(
                session, [mediumfast], since, apply=True, store_text_messages=False
            )
            await session.commit()
        assert done["recovered:67"] == 1, done
        assert await state() == {1001: ("readable", 67), 1002: ("no_key", 0)}, (
            "the foreign packet must stay no_key; only the readable one is recovered"
        )
        assert await batteries() == [87], (
            "the recovered telemetry did not reach device_metrics, which is what the "
            "reader actually saw go stale"
        )

        # 4. Running again recovers nothing twice.
        async with factory() as session:
            again = await recover(
                session, [mediumfast], since, apply=True, store_text_messages=False
            )
            await session.commit()
        assert sum(v for k, v in again.items() if k.startswith("recovered:")) == 0, again
        assert await batteries() == [87], "a second run stored the telemetry twice"
    finally:
        await engine.dispose()
