"""Mesh packet header metric storage."""

from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from sonoran.db.models import MeshPacketMetrics
from sonoran.meshtastic import mesh_pb2


async def store_mesh_packet_metrics(
    session: AsyncSession,
    packet: Any,
    packet_pk: int | None,
    gateway_node_num: int | None,
    time: datetime,
    message_size_bytes: int,
) -> None:
    """Store routing and transport fields for one unique mesh packet."""
    try:
        transport = mesh_pb2.MeshPacket.TransportMechanism.Name(  # type: ignore[attr-defined]
            packet.transport_mechanism
        )
    except ValueError:
        transport = None
    session.add(
        MeshPacketMetrics(
            packet_pk=packet_pk,
            from_node_num=getattr(packet, "from"),
            to_node_num=packet.to or 0,
            packet_id=packet.id,
            reporting_gateway_node_num=gateway_node_num,
            via_mqtt=packet.via_mqtt,
            message_size_bytes=message_size_bytes,
            relay_node_num=packet.relay_node or None,
            next_hop_node_num=packet.next_hop or None,
            transport_mechanism=transport,
            pki_encrypted=packet.pki_encrypted,
            time=time,
        )
    )
