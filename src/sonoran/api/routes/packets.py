"""Read-only packet endpoints."""

from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import ColumnElement, and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from sonoran.api.dependencies import get_session, require_node_num
from sonoran.api.names import name_of, resolve_names
from sonoran.api.packet_summary import summaries, text_of
from sonoran.db.models import (
    AirQualityMetrics,
    DeviceMetrics,
    EnvironmentMetrics,
    MeshPacketMetrics,
    NeighborMetrics,
    Packet,
    PacketSeen,
    PositionMetrics,
    PowerMetrics,
    TextMessage,
)
from sonoran.meshtastic import portnums_pb2

router = APIRouter(prefix="/api/packets", tags=["packets"])

# How far before a packet's first sighting its metrics rows are read. The
# bound lets the hypertable read skip old chunks. It does not decide which
# rows count: every row is keyed on the packet itself.
_METRICS_SLACK = timedelta(hours=1)


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
    summary: bool = False,
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, object]]:
    """Return packets newest first.

    Set `summary=true` to add a one line `summary` of what each packet
    said, read from the decoded tables. See `api/packet_summary.py`.
    """
    # Pick the page first, count second.
    #
    # This used to group the whole join before applying the limit, so
    # the limit could not push down and the planner read every chunk of
    # `packet` on every request -- 724k rows, five sequential scans, and
    # a 14 MB sort spilled to disk, for a hundred rows. Measured at
    # 629 ms, with `packet_first_seen_at_idx` never used.
    #
    # Choosing the page in its own statement lets the index do the
    # ordering, so only the rows that will be returned are ever joined
    # to `packet_seen`. Measured at 19.8 ms, and the sort fits in
    # memory. Same answer either way.
    #
    # This is the shape `map.py` already uses for the same reason; see
    # the note there about a correlated read.
    picked = select(Packet.id.label("pk")).order_by(Packet.first_seen_at.desc()).limit(limit)
    if portnum is not None:
        picked = picked.where(Packet.portnum == _parse_portnum(portnum))
    if from_node:
        picked = picked.where(Packet.from_node_num == require_node_num(from_node))
    if to_node:
        picked = picked.where(Packet.to_node_num == require_node_num(to_node))
    if channel:
        picked = picked.where(Packet.channel == channel)
    if since:
        picked = picked.where(Packet.first_seen_at >= since)
    if before:
        picked = picked.where(Packet.first_seen_at < before)
    page = picked.cte("page")

    count = func.count(PacketSeen.id).label("seen_count")
    statement = (
        select(Packet, count)
        .join(page, page.c.pk == Packet.id)
        .outerjoin(PacketSeen, _same_packet(Packet, PacketSeen))
        .group_by(Packet.id, Packet.first_seen_at)
        .order_by(Packet.first_seen_at.desc())
    )
    rows = (await session.execute(statement)).all()
    names = await resolve_names(
        session, [num for packet, _ in rows for num in (packet.from_node_num, packet.to_node_num)]
    )
    items = [_packet_item(packet, seen_count, names) for packet, seen_count in rows]
    if summary and rows:
        lines = await summaries(
            session,
            [(packet.from_node_num, packet.packet_id) for packet, _ in rows],
            min(packet.first_seen_at for packet, _ in rows),
        )
        for item, (packet, _) in zip(items, rows, strict=True):
            parts = lines.get((packet.from_node_num, packet.packet_id))
            item["summary"] = text_of(parts)
            # The same line with each measurement as a number and its SI
            # unit, so the browser can write it in the reader's units.
            item["summary_parts"] = parts
    return items


def _values(model: Any, row: object) -> dict[str, object]:
    """Return the stored columns of one decoded row."""
    skip = {"id", "packet_pk", "packet_id", "node_num", "from_node_num"}
    return {
        column.name: getattr(row, column.name)
        for column in model.__table__.columns
        if column.name not in skip and getattr(row, column.name) is not None
    }


def _named_neighbours(
    values: list[dict[str, object]], names: dict[int, dict[str, str | None]]
) -> list[dict[str, object]]:
    """Add the ID and the readable name of each reported neighbour.

    A neighbour report names the nodes it heard by number only, because
    that is all `neighbor_metrics` stores. The packet page therefore
    printed `!0a51a002` in the table of reported neighbours, while the
    gateway table higher up the same page printed "Usery Pass Relay" for
    the very same node (#240).

    The name is joined here and not in the browser. The browser holds no
    node table, so it would need one request per neighbour to build the
    same answer, and the gateway rows on this page are already named
    server side by `resolve_names`. One more query for the whole list is
    the cheaper half of that comparison.

    `name_of` falls back to the ID form for a node this dashboard has
    never seen a node-info packet from, so `neighbor_name` is always a
    string worth printing and the browser needs no fallback of its own.
    `neighbor_node_num` stays, because the raw panel shows the row as the
    database holds it.
    """
    labelled: list[dict[str, object]] = []
    for row in values:
        num = row.get("neighbor_node_num")
        if not isinstance(num, int):
            # Unreachable today: the column is NOT NULL, and `_values`
            # only drops a None. It is here because the alternative is a
            # KeyError that takes out the whole page, and a row with no
            # name still reads.
            labelled.append(row)
            continue
        labelled.append(row | {"neighbor_id": _node_id(num), "neighbor_name": name_of(names, num)})
    return labelled


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
        if not rows:
            continue
        values = [_values(model, row) for row in rows]
        if kind == "neighbors":
            # The only decoded family whose rows point at another node.
            names = await resolve_names(session, [row.neighbor_node_num for row in rows])
            values = _named_neighbours(values, names)
        return {"kind": kind, "values": values}
    return None


@router.get("/{from_node}/{packet_id}")
async def get_packet(
    from_node: str,
    packet_id: int,
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    """Return one packet and its MQTT observations."""
    try:
        from_num = require_node_num(from_node)
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
    # Whether the packet was sealed with the recipient's public key (PKI)
    # rather than the channel key. Ingest keeps it per upload in
    # `mesh_packet_metrics`, so it is read from there. None when no row
    # recorded it, which is not the same as false.
    pki_encrypted = await session.scalar(
        select(func.bool_or(MeshPacketMetrics.pki_encrypted)).where(
            MeshPacketMetrics.from_node_num == packet.from_node_num,
            MeshPacketMetrics.packet_id == packet.packet_id,
            MeshPacketMetrics.time >= packet.first_seen_at - _METRICS_SLACK,
        )
    )
    return {
        "packet": _packet_item(packet, len(observations), names)
        | {
            "decoded": await _decoded_payload(session, packet),
            "payload_json": packet.payload_json,
            "want_ack": packet.want_ack,
            "pki_encrypted": pki_encrypted,
            "priority": packet.priority,
            "rx_time": packet.rx_time,
            "raw_bytes_length": None if packet.raw_bytes is None else len(packet.raw_bytes),
        },
        "gateway_count": len({item.gateway_node_num for item in observations}),
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
                # The sender is often its own gateway, so it uploads the
                # packet it just sent. That is a node reporting its own
                # voice, not a radio link, and it must never count as a
                # direct observation. Every such row has hop_start equal
                # to hop_limit, so the hop rule alone calls it direct and
                # then offers its reading as the sender's own link.
                "self_reported": item.gateway_node_num == packet.from_node_num,
                "direct": (
                    packet.hop_start is not None
                    and packet.hop_start == item.hop_limit
                    and item.gateway_node_num != packet.from_node_num
                ),
                "seen_at": item.seen_at,
            }
            for item in observations
        ],
    }
