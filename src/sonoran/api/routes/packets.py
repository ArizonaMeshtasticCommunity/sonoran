"""Read-only packet endpoints."""

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import ColumnElement, and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from sonoran.api.dependencies import get_session, parse_node_id
from sonoran.api.names import name_of, resolve_names
from sonoran.db.models import (
    AirQualityMetrics,
    DeviceMetrics,
    EnvironmentMetrics,
    NeighborMetrics,
    Packet,
    PacketSeen,
    PositionMetrics,
    PowerMetrics,
    TextMessage,
)
from sonoran.meshtastic import portnums_pb2

router = APIRouter(prefix="/api/packets", tags=["packets"])


def _node_id(value: int | None) -> str:
    """Format a node number for a JSON response."""
    return "^all" if value is None else f"!{value:08x}"


def _same_packet(packet: type[Packet], seen: type[PacketSeen]) -> ColumnElement[bool]:
    """Match a packet to its observations by the deduplication key.

    The ingest role has no SELECT right, so it cannot read back the
    generated `packet.id` and cannot store it on the observation. The
    two rows are joined by (`from_node_num`, `packet_id`) instead, which
    is the documented deduplication key.
    """
    return and_(
        seen.from_node_num == packet.from_node_num,
        seen.packet_id == packet.packet_id,
    )


def _packet_item(
    packet: Packet,
    seen_count: int,
    names: dict[int, dict[str, str | None]] | None = None,
) -> dict[str, object]:
    """Map a packet row to its public summary."""
    try:
        portnum = portnums_pb2.PortNum.Name(packet.portnum)  # type: ignore[attr-defined]
    except ValueError:
        portnum = str(packet.portnum)
    names = names or {}
    return {
        "packet_key": f"{packet.from_node_num}:{packet.packet_id}",
        "from_node": _node_id(packet.from_node_num),
        "from_name": name_of(names, packet.from_node_num),
        "to_node": _node_id(packet.to_node_num),
        "to_name": name_of(names, packet.to_node_num),
        "portnum": portnum,
        "channel": packet.channel,
        "hop_start": packet.hop_start,
        "hop_limit": packet.hop_limit,
        "first_seen_at": packet.first_seen_at,
        "seen_count": seen_count,
    }


def _parse_portnum(value: str) -> int:
    """Parse a numeric or protobuf port-number name."""
    if value.isdecimal():
        return int(value)
    try:
        return portnums_pb2.PortNum.Value(value)  # type: ignore[attr-defined]
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="invalid portnum") from exc


@router.get("")
async def list_packets(
    portnum: str | None = None,
    from_node: str | None = Query(default=None, alias="from"),
    to_node: str | None = Query(default=None, alias="to"),
    channel: str | None = None,
    since: datetime | None = None,
    before: datetime | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, object]]:
    """Return packets newest first."""
    count = func.count(PacketSeen.id).label("seen_count")
    statement = (
        select(Packet, count)
        .outerjoin(PacketSeen, _same_packet(Packet, PacketSeen))
        .group_by(Packet.id, Packet.first_seen_at)
        .order_by(Packet.first_seen_at.desc())
        .limit(limit)
    )
    if portnum is not None:
        statement = statement.where(Packet.portnum == _parse_portnum(portnum))
    if from_node:
        statement = statement.where(Packet.from_node_num == parse_node_id(from_node))
    if to_node:
        statement = statement.where(Packet.to_node_num == parse_node_id(to_node))
    if channel:
        statement = statement.where(Packet.channel == channel)
    if since:
        statement = statement.where(Packet.first_seen_at >= since)
    if before:
        statement = statement.where(Packet.first_seen_at < before)
    rows = (await session.execute(statement)).all()
    names = await resolve_names(
        session, [num for packet, _ in rows for num in (packet.from_node_num, packet.to_node_num)]
    )
    return [_packet_item(packet, seen_count, names) for packet, seen_count in rows]


def _values(model: Any, row: object) -> dict[str, object]:
    """Return the stored columns of one decoded row."""
    skip = {"id", "packet_pk", "packet_id", "node_num", "from_node_num"}
    return {
        column.name: getattr(row, column.name)
        for column in model.__table__.columns
        if column.name not in skip and getattr(row, column.name) is not None
    }


async def _decoded_payload(session: AsyncSession, packet: Packet) -> dict[str, object] | None:
    """Return the decoded payload of one packet.

    The packet table stores the raw bytes only. Every decoded value goes
    to the table of its family, keyed by the node and the packet ID. This
    reads it back so a packet page can show what the packet carried.
    """
    # Each family stores its decoded values in its own table. Telemetry
    # splits further, so several tables are tried for one port number.
    candidates: list[tuple[str, Any, Any]] = []
    if packet.portnum == portnums_pb2.TEXT_MESSAGE_APP:  # type: ignore[attr-defined]
        candidates = [("text", TextMessage, TextMessage.from_node_num)]
    elif packet.portnum == portnums_pb2.POSITION_APP:  # type: ignore[attr-defined]
        candidates = [("position", PositionMetrics, PositionMetrics.node_num)]
    elif packet.portnum == portnums_pb2.NEIGHBORINFO_APP:  # type: ignore[attr-defined]
        candidates = [("neighbors", NeighborMetrics, NeighborMetrics.node_num)]
    elif packet.portnum == portnums_pb2.TELEMETRY_APP:  # type: ignore[attr-defined]
        candidates = [
            ("device", DeviceMetrics, DeviceMetrics.node_num),
            ("environment", EnvironmentMetrics, EnvironmentMetrics.node_num),
            ("air_quality", AirQualityMetrics, AirQualityMetrics.node_num),
            ("power", PowerMetrics, PowerMetrics.node_num),
        ]

    for kind, model, node_column in candidates:
        rows = list(
            (
                await session.scalars(
                    select(model).where(
                        node_column == packet.from_node_num,
                        model.packet_id == packet.packet_id,
                    )
                )
            ).all()
        )
        if rows:
            return {"kind": kind, "values": [_values(model, row) for row in rows]}
    return None


@router.get("/{from_node}/{packet_id}")
async def get_packet(
    from_node: str,
    packet_id: int,
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    """Return one packet and its MQTT observations."""
    try:
        from_num = parse_node_id(from_node)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    packet = await session.scalar(
        select(Packet)
        .where(Packet.from_node_num == from_num, Packet.packet_id == packet_id)
        .order_by(Packet.first_seen_at.desc())
    )
    if packet is None:
        raise HTTPException(status_code=404, detail="packet not found")
    observations = (
        await session.scalars(
            select(PacketSeen)
            .where(
                PacketSeen.from_node_num == packet.from_node_num,
                PacketSeen.packet_id == packet.packet_id,
            )
            .order_by(PacketSeen.seen_at.asc())
        )
    ).all()
    names = await resolve_names(
        session,
        [
            packet.from_node_num,
            packet.to_node_num,
            *(item.gateway_node_num for item in observations),
        ],
    )
    return {
        "packet": _packet_item(packet, len(observations), names)
        | {
            "decoded": await _decoded_payload(session, packet),
            "payload_json": packet.payload_json,
            "want_ack": packet.want_ack,
            "priority": packet.priority,
            "rx_time": packet.rx_time,
            "raw_bytes_length": None if packet.raw_bytes is None else len(packet.raw_bytes),
        },
        "observations": [
            {
                "gateway": _node_id(item.gateway_node_num),
                "gateway_name": name_of(names, item.gateway_node_num),
                "mqtt_topic": item.mqtt_topic,
                "channel": item.channel,
                "rx_rssi": item.rx_rssi,
                "rx_snr": item.rx_snr,
                "hop_limit": item.hop_limit,
                # A packet that used no hop reached this gateway direct,
                # so its signal reading describes that radio link.
                "hops_taken": (
                    None
                    if packet.hop_start is None or item.hop_limit is None
                    else packet.hop_start - item.hop_limit
                ),
                "direct": packet.hop_start is not None and packet.hop_start == item.hop_limit,
                "seen_at": item.seen_at,
            }
            for item in observations
        ],
    }
