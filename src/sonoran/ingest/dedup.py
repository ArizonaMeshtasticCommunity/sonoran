"""Packet and observation storage with deduplication."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast

from sqlalchemy import CursorResult, null
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from sonoran.db.models import Packet, PacketKey, PacketSeen


@dataclass(frozen=True)
class PacketInput:
    """The fields for one unique packet."""

    from_node_num: int
    packet_id: int
    to_node_num: int | None
    portnum: int
    channel: str | None
    hop_start: int | None
    hop_limit: int | None
    want_ack: bool
    priority: int | None
    rx_time: int | None
    first_seen_at: datetime
    raw_bytes: bytes
    # What the packet carried, for the families `decode.stored` keeps.
    # Only ingest holds the channel keys, so this is the one place it
    # can be written. None for every other family.
    payload_json: dict[str, Any] | None = None
    # Why the payload could or could not be read (#157). Ingest is the
    # only place that knows: it has one code path per state, so this is
    # recorded rather than inferred.
    payload_state: str | None = None


@dataclass(frozen=True)
class ObservationInput:
    """The fields for one MQTT observation."""

    gateway_node_num: int
    mqtt_topic: str
    channel: str | None
    rx_rssi: int | None
    rx_snr: float | None
    hop_limit: int | None
    seen_at: datetime


@dataclass(frozen=True)
class StoredPacket:
    """The packet identity and whether this message created it."""

    packet_pk: int | None
    is_new: bool


async def _claim_packet(session: AsyncSession, packet: PacketInput) -> bool:
    """Return true when this message is the first sighting of a packet.

    The claim is an insert into the key table. When the row already
    exists PostgreSQL does nothing and reports no affected row, so a
    repeat is detected without reading the table.
    """
    result = cast(
        "CursorResult[Any]",
        await session.execute(
            insert(PacketKey)
            .values(
                from_node_num=packet.from_node_num,
                packet_id=packet.packet_id,
                first_seen_at=packet.first_seen_at,
            )
            .on_conflict_do_nothing(index_elements=[PacketKey.from_node_num, PacketKey.packet_id]),
        ),
    )
    return bool(result.rowcount)


async def store_packet(
    session: AsyncSession,
    packet: PacketInput,
    observation: ObservationInput,
) -> StoredPacket:
    """Store one packet and always store its MQTT observation.

    Several gateways relay the same packet. Each relay is a real
    observation with its own signal reading, so every message writes a
    `packet_seen` row. The packet body is written once, on the first
    sighting only.
    """
    is_new = await _claim_packet(session, packet)
    if is_new:
        try:
            async with session.begin_nested():
                await session.execute(
                    insert(Packet)
                    .inline()
                    .values(
                        from_node_num=packet.from_node_num,
                        packet_id=packet.packet_id,
                        to_node_num=packet.to_node_num,
                        portnum=packet.portnum,
                        channel=packet.channel,
                        hop_start=packet.hop_start,
                        hop_limit=packet.hop_limit,
                        want_ack=packet.want_ack,
                        priority=packet.priority,
                        rx_time=packet.rx_time,
                        first_seen_at=packet.first_seen_at,
                        raw_bytes=packet.raw_bytes,
                        # A JSONB column stores Python None as the JSON
                        # value null, not as SQL NULL. "Nothing kept" must
                        # be SQL NULL, so a query for it can use IS NULL.
                        payload_json=null() if packet.payload_json is None else packet.payload_json,
                        payload_state=packet.payload_state,
                    )
                )
        except IntegrityError:
            # The row exists from before the key table. Treat it as seen.
            is_new = False

    session.add(
        PacketSeen(
            packet_pk=None,
            from_node_num=packet.from_node_num,
            packet_id=packet.packet_id,
            gateway_node_num=observation.gateway_node_num,
            mqtt_topic=observation.mqtt_topic,
            channel=observation.channel,
            rx_rssi=observation.rx_rssi,
            rx_snr=observation.rx_snr,
            hop_limit=observation.hop_limit,
            seen_at=observation.seen_at,
        )
    )
    return StoredPacket(packet_pk=None, is_new=is_new)
