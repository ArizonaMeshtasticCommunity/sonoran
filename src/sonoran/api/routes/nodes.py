"""Read-only node endpoints."""

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import ColumnElement, Select, and_, func, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from sonoran.api.dependencies import get_session, parse_node_id
from sonoran.api.names import display_name, format_node_id, name_of, resolve_names
from sonoran.api.schemas import NodeSummary
from sonoran.db.models import (
    AirQualityMetrics,
    DeviceMetrics,
    EnvironmentMetrics,
    NeighborMetrics,
    Node,
    NodeConfig,
    Packet,
    PacketSeen,
    PaxMetrics,
    PowerMetrics,
    TextMessage,
)
from sonoran.meshtastic import portnums_pb2
from sonoran.positions import is_usable

router = APIRouter(prefix="/api/nodes", tags=["nodes"])

TELEMETRY_MODELS = {
    "device": DeviceMetrics,
    "environment": EnvironmentMetrics,
    "air_quality": AirQualityMetrics,
    "power": PowerMetrics,
    "pax": PaxMetrics,
}

# Environment fields that the user interface shows as weather.
WEATHER_FIELDS = (
    "temperature",
    "relative_humidity",
    "barometric_pressure",
    "wind_speed",
    "wind_direction",
    "rainfall",
    "lux",
    "uv_lux",
    "iaq",
    "gas_resistance",
)


def _summary(node: Node) -> NodeSummary:
    """Map a node ORM row to its public representation."""
    return NodeSummary(
        node_id=format_node_id(node.node_num),
        node_num=node.node_num,
        long_name=node.long_name,
        short_name=node.short_name,
        display_name=display_name(node.node_num, node.long_name, node.short_name),
        hw_model=node.hw_model,
        role=node.role,
        last_heard=node.last_heard,
        is_mqtt_gateway=node.is_mqtt_gateway,
        has_position=is_usable(node.last_lat, node.last_lon),
    )


def _require_node_num(value: str) -> int:
    """Parse a node ID or raise the documented API error."""
    try:
        return parse_node_id(value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _portnum_name(value: int) -> str:
    """Return the protobuf name of a port number, or the number itself."""
    try:
        return portnums_pb2.PortNum.Name(value)  # type: ignore[attr-defined]
    except ValueError:
        return str(value)


def _row_values(model: Any, row: object, skip: tuple[str, ...] = ("id",)) -> dict[str, object]:
    """Return the public column values of one telemetry row."""
    return {
        column.name: getattr(row, column.name)
        for column in model.__table__.columns
        if column.name not in skip
    }


async def _latest_metric(session: AsyncSession, model: Any, node_num: int) -> dict[str, object]:
    """Return the newest telemetry row of one family, or an empty record."""
    row = await session.scalar(
        select(model).where(model.node_num == node_num).order_by(model.time.desc()).limit(1)
    )
    return {} if row is None else _row_values(model, row, skip=("id", "packet_pk", "node_num"))


async def _latest_neighbors(
    session: AsyncSession, node_num: int, limit: int, since: datetime | None = None
) -> list[dict[str, object]]:
    """Return the newest report for each neighbor of one node.

    The window matches the rest of the page. Without it this list would
    keep neighbors the node stopped hearing long ago, and would then
    disagree with the mesh graph, which always uses a window.
    """
    statement = (
        select(NeighborMetrics)
        .where(
            NeighborMetrics.node_num == node_num,
            true() if since is None else NeighborMetrics.time >= since,
        )
        .distinct(NeighborMetrics.neighbor_node_num)
        .order_by(NeighborMetrics.neighbor_node_num, NeighborMetrics.time.desc())
        .limit(limit)
    )
    rows = list((await session.scalars(statement)).all())
    # Show the strongest link first. Reports with no SNR go last.
    rows.sort(key=lambda row: (row.snr is None, -(row.snr or 0.0)))
    names = await resolve_names(session, (row.neighbor_node_num for row in rows))
    return [
        {
            "node_id": format_node_id(row.neighbor_node_num),
            "display_name": name_of(names, row.neighbor_node_num),
            "snr": row.snr,
            "last_rx_time": row.last_rx_time,
            "broadcast_interval_secs": row.node_broadcast_interval_secs,
            "time": row.time,
        }
        for row in rows
    ]


async def _heard_by(
    session: AsyncSession, node_num: int, since: datetime
) -> list[dict[str, object]]:
    """Return the gateways that relayed one node, and how they heard it.

    A gateway usually receives a packet after other nodes relayed it. The
    signal reading on an observation belongs to that last hop, not to the
    link between this node and the gateway.

    A packet arrived direct when no hop was used, that is when the
    remaining hop limit still equals the starting hop limit. Signal
    figures come from those observations only. Everything else is
    counted as relayed and carries no signal figure.
    """
    direct = Packet.hop_start == PacketSeen.hop_limit
    statement = (
        select(
            PacketSeen.gateway_node_num,
            func.count().label("total"),
            func.count().filter(direct).label("direct_count"),
            func.max(PacketSeen.seen_at).label("last_heard"),
            func.avg(PacketSeen.rx_snr).filter(direct).label("avg_snr"),
            func.max(PacketSeen.rx_snr).filter(direct).label("best_snr"),
            func.avg(PacketSeen.rx_rssi).filter(direct).label("avg_rssi"),
        )
        .select_from(PacketSeen)
        .join(
            Packet,
            and_(
                Packet.from_node_num == PacketSeen.from_node_num,
                Packet.packet_id == PacketSeen.packet_id,
            ),
        )
        .where(PacketSeen.from_node_num == node_num, PacketSeen.seen_at >= since)
        .group_by(PacketSeen.gateway_node_num)
        .order_by(func.count().desc())
    )
    rows = (await session.execute(statement)).all()
    names = await resolve_names(session, (row.gateway_node_num for row in rows))
    return [
        {
            "node_id": format_node_id(row.gateway_node_num),
            "display_name": name_of(names, row.gateway_node_num),
            "count": row.total,
            "direct_count": row.direct_count,
            "relayed_count": row.total - row.direct_count,
            "last_heard": row.last_heard,
            "avg_snr": None if row.avg_snr is None else round(float(row.avg_snr), 2),
            "best_snr": row.best_snr,
            "avg_rssi": None if row.avg_rssi is None else round(float(row.avg_rssi), 1),
        }
        for row in rows
    ]


async def _activity(session: AsyncSession, node_num: int, since: datetime) -> dict[str, object]:
    """Return packet counts for one node in the selected window."""
    rows = (
        await session.execute(
            select(Packet.portnum, func.count().label("total"))
            .where(Packet.from_node_num == node_num, Packet.first_seen_at >= since)
            .group_by(Packet.portnum)
            .order_by(func.count().desc())
        )
    ).all()
    return {
        "packet_count": sum(row.total for row in rows),
        "by_portnum": [{"portnum": _portnum_name(row.portnum), "count": row.total} for row in rows],
    }


async def _messages(
    session: AsyncSession, node_num: int, since: datetime, limit: int
) -> dict[str, object]:
    """Return the messages that one node sent in the selected window."""
    total = await session.scalar(
        select(func.count())
        .select_from(TextMessage)
        .where(TextMessage.from_node_num == node_num, TextMessage.seen_at >= since)
    )
    rows = (
        await session.scalars(
            select(TextMessage)
            .where(TextMessage.from_node_num == node_num, TextMessage.seen_at >= since)
            .order_by(TextMessage.seen_at.desc())
            .limit(limit)
        )
    ).all()
    names = await resolve_names(session, (row.to_node_num for row in rows))
    return {
        "count": total or 0,
        "recent": [
            {
                "body": row.body,
                "channel": row.channel,
                "to_node": format_node_id(row.to_node_num),
                "to_name": name_of(names, row.to_node_num),
                "emoji": row.emoji,
                "seen_at": row.seen_at,
            }
            for row in rows
        ],
    }


def _position(node: Node) -> dict[str, object] | None:
    """Return the last known position of one node.

    A position that is not a real place counts as no position. The node
    page draws a map from this, and a node with no fix would otherwise
    appear in the ocean off West Africa. See `sonoran.positions`.
    """
    if not is_usable(node.last_lat, node.last_lon):
        return None
    return {
        "lat": node.last_lat,
        "lon": node.last_lon,
        "altitude": node.last_altitude,
        "time": node.position_time,
    }


def _apply_node_filters(
    statement: Select[tuple[Node]],
    q: str | None,
    hw: str | None,
    role: str | None,
    gateway: bool | None,
    active_hours: int | None,
    before: datetime | None,
) -> Select[tuple[Node]]:
    """Apply the documented node list filters to a statement."""
    if q:
        match = f"%{q}%"
        predicates: list[ColumnElement[bool]] = [
            Node.long_name.ilike(match),
            Node.short_name.ilike(match),
        ]
        try:
            predicates.append(Node.node_num == parse_node_id(q))
        except ValueError:
            pass
        statement = statement.where(or_(*predicates))
    if hw:
        statement = statement.where(Node.hw_model == hw)
    if role:
        statement = statement.where(Node.role == role)
    if gateway is not None:
        statement = statement.where(Node.is_mqtt_gateway == gateway)
    if active_hours is not None:
        statement = statement.where(
            Node.last_heard >= datetime.now(UTC) - timedelta(hours=active_hours)
        )
    if before is not None:
        statement = statement.where(Node.last_heard < before)
    return statement


@router.get("", response_model=list[NodeSummary])
async def list_nodes(
    q: str | None = None,
    hw: str | None = None,
    role: str | None = None,
    gateway: bool | None = None,
    active_hours: int | None = Query(default=None, ge=1, le=720),
    before: datetime | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
) -> list[NodeSummary]:
    """Return nodes newest heard first."""
    statement = select(Node).order_by(Node.last_heard.desc().nullslast()).limit(limit)
    statement = _apply_node_filters(statement, q, hw, role, gateway, active_hours, before)
    return [_summary(node) for node in (await session.scalars(statement)).all()]


@router.get("/{node_id}", response_model=NodeSummary)
async def get_node(node_id: str, session: AsyncSession = Depends(get_session)) -> NodeSummary:
    """Return one node by documented node ID form."""
    node = await session.get(Node, _require_node_num(node_id))
    if node is None:
        raise HTTPException(status_code=404, detail="node not found")
    return _summary(node)


@router.get("/{node_id}/detail")
async def node_detail(
    node_id: str,
    request: Request,
    hours: int = Query(default=24, ge=1, le=720),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    """Return every value that the node detail page shows.

    The page needs the node record, its neighbors with signal quality,
    the gateways that heard it, its weather and device telemetry, its
    activity counts, and its recent messages. One request returns all of
    them so the page makes one round trip.
    """
    node_num = _require_node_num(node_id)
    node = await session.get(Node, node_num)
    if node is None:
        raise HTTPException(status_code=404, detail="node not found")
    since = datetime.now(UTC) - timedelta(hours=hours)
    graph_base_url = request.app.state.settings.mesh_graph_base_url.rstrip("/")
    environment = await _latest_metric(session, EnvironmentMetrics, node_num)
    return {
        "node": _summary(node).model_dump()
        | {
            "is_licensed": node.is_licensed,
            "first_seen": node.first_seen,
            "last_channel": node.last_channel,
            "last_mqtt_topic": node.last_mqtt_topic,
            "position": _position(node),
        },
        "window_hours": hours,
        "neighbors": await _latest_neighbors(session, node_num, limit=100, since=since),
        "heard_by": await _heard_by(session, node_num, since),
        "weather": {
            field: environment[field]
            for field in WEATHER_FIELDS
            if environment.get(field) is not None
        },
        "weather_time": environment.get("time"),
        "device": await _latest_metric(session, DeviceMetrics, node_num),
        "air_quality": await _latest_metric(session, AirQualityMetrics, node_num),
        "power": await _latest_metric(session, PowerMetrics, node_num),
        "activity": await _activity(session, node_num, since),
        "messages": await _messages(session, node_num, since, limit=25),
        "graph": {
            "node_graph": f"{graph_base_url}/graph/node/{format_node_id(node_num)}?clickable=true",
            "node_page": f"{graph_base_url}/nodes/{format_node_id(node_num)}",
        },
    }


@router.get("/{node_id}/signal")
async def signal_history(
    node_id: str,
    hours: int = Query(default=24, ge=1, le=720),
    max_points: int = Query(default=500, ge=1, le=5000),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, object]]:
    """Return the signal of each direct radio link of one node over time.

    The reading comes from neighbor reports, which a node sends about
    the neighbors it hears itself. That is a direct radio measurement.

    Gateway observations are not used here. A gateway usually receives a
    packet after other nodes relayed it, so its signal reading belongs
    to the last hop and says nothing about the link to this node.
    """
    node_num = _require_node_num(node_id)
    since = datetime.now(UTC) - timedelta(hours=hours)
    rows = (
        await session.scalars(
            select(NeighborMetrics)
            .where(
                or_(
                    NeighborMetrics.node_num == node_num,
                    NeighborMetrics.neighbor_node_num == node_num,
                ),
                NeighborMetrics.time >= since,
                NeighborMetrics.snr.is_not(None),
            )
            .order_by(NeighborMetrics.time.desc())
            .limit(max_points)
        )
    ).all()
    # The other end of the link is whichever node is not this one.
    others = [row.neighbor_node_num if row.node_num == node_num else row.node_num for row in rows]
    names = await resolve_names(session, others)
    return [
        {
            "time": row.time,
            "neighbor": format_node_id(other),
            "neighbor_name": name_of(names, other),
            "snr": row.snr,
            "reported_by": format_node_id(row.node_num),
            "packet_id": row.packet_id,
        }
        for row, other in zip(reversed(rows), reversed(others), strict=True)
    ]


@router.get("/{node_id}/config")
async def node_config(
    node_id: str, session: AsyncSession = Depends(get_session)
) -> list[dict[str, object]]:
    """Return the latest reported configuration objects for one node."""
    rows = await session.scalars(
        select(NodeConfig).where(NodeConfig.node_num == _require_node_num(node_id))
    )
    return [
        {"type": item.config_type, "value": item.config_json, "updated_at": item.updated_at}
        for item in rows.all()
    ]


@router.get("/{node_id}/heard-by")
async def heard_by(
    node_id: str,
    hours: int = Query(default=24, ge=1, le=720),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, object]]:
    """Return gateways that observed packets from one node."""
    since = datetime.now(UTC) - timedelta(hours=hours)
    return await _heard_by(session, _require_node_num(node_id), since)


@router.get("/{node_id}/packets")
async def node_packets(
    node_id: str,
    limit: int = Query(default=100, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, object]]:
    """Return recent packets from one node."""
    rows = await session.scalars(
        select(Packet)
        .where(Packet.from_node_num == _require_node_num(node_id))
        .order_by(Packet.first_seen_at.desc())
        .limit(limit)
    )
    return [
        {
            "packet_id": item.packet_id,
            "portnum": _portnum_name(item.portnum),
            "channel": item.channel,
            "seen_at": item.first_seen_at,
        }
        for item in rows.all()
    ]


@router.get("/{node_id}/telemetry")
async def telemetry(
    node_id: str,
    family: str,
    start: datetime | None = None,
    end: datetime | None = None,
    max_points: int = Query(default=500, ge=1, le=5000),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, object]]:
    """Return telemetry points for one node and metric family."""
    node_num = _require_node_num(node_id)
    model = TELEMETRY_MODELS.get(family)
    if model is None:
        raise HTTPException(status_code=422, detail="invalid telemetry family")
    end = end or datetime.now(UTC)
    start = start or end - timedelta(hours=24)
    statement = (
        select(model)
        .where(model.node_num == node_num, model.time.between(start, end))  # type: ignore[attr-defined]
        .order_by(model.time.desc())  # type: ignore[attr-defined]
        .limit(max_points)
    )
    rows = await session.scalars(statement)
    return [_row_values(model, row) for row in rows.all()]


@router.get("/{node_id}/graph")
async def graph(node_id: str, request: Request) -> dict[str, str]:
    """Return mesh-graph links for one node."""
    node = format_node_id(_require_node_num(node_id))
    base_url = request.app.state.settings.mesh_graph_base_url.rstrip("/")
    return {
        "node_graph": f"{base_url}/graph/node/{node}?clickable=true",
        "node_page": f"{base_url}/nodes/{node}",
    }


@router.get("/{node_id}/neighbors")
async def neighbors(
    node_id: str, session: AsyncSession = Depends(get_session)
) -> list[dict[str, object]]:
    """Return the latest stored neighbor links for one node."""
    return await _latest_neighbors(session, _require_node_num(node_id), limit=100)
