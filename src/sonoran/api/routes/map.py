"""Read-only map endpoints."""

from datetime import UTC, datetime, timedelta
from typing import cast

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from sonoran.api.channels import channel_filter
from sonoran.api.dependencies import get_session, parse_node_id
from sonoran.api.names import display_name, format_node_id, name_of, resolve_names
from sonoran.api.traces import SNR_SCALE, UNKNOWN_SNR, forward_path, is_reply
from sonoran.db.models import (
    NeighborMetrics,
    Node,
    Packet,
    PacketSeen,
    PositionMetrics,
    Traceroute,
)
from sonoran.meshtastic import portnums_pb2
from sonoran.positions import is_usable

router = APIRouter(prefix="/api/map", tags=["map"])


def _path_of(trace: Traceroute) -> list[int]:
    """Return the nodes one traceroute passed through, in order."""
    return forward_path(trace)


def _hop_snrs(trace: Traceroute, wanted: int) -> list[float | None]:
    """Return one SNR for each hop, in dB, padded with None.

    `snr_towards` is shorter than the hop list about two thirds of the
    time, so the tail carries no reading at all. A hop the firmware
    could not measure holds INT8_MIN, which means "not measured" and not
    -32 dB. See AGENTS.md 9.6.
    """
    readings = list(trace.snr_towards or [])
    out: list[float | None] = []
    for index in range(wanted):
        value = readings[index] if index < len(readings) else None
        if not isinstance(value, int | float) or value == UNKNOWN_SNR:
            out.append(None)
        else:
            out.append(value / SNR_SCALE)
    return out


def _require_node_num(value: str) -> int:
    """Parse a node ID or raise the documented API error."""
    try:
        return parse_node_id(value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/nodes")
async def map_nodes(
    active_hours: int | None = Query(default=None, ge=1, le=720),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, object]]:
    """Return nodes with a current position.

    A node whose position is not a real place is left out. See
    `sonoran.positions`. Rows written before that check went into the
    ingest still hold one, and a map is the wrong place to show it.
    """
    statement = select(Node).where(Node.last_lat.is_not(None), Node.last_lon.is_not(None))
    if active_hours is not None:
        statement = statement.where(
            Node.last_heard >= datetime.now(UTC) - timedelta(hours=active_hours)
        )
    nodes = [
        node
        for node in (await session.scalars(statement)).all()
        if is_usable(node.last_lat, node.last_lon)
    ]
    return [
        {
            "node_id": format_node_id(node.node_num),
            "node_num": node.node_num,
            "display_name": display_name(node.node_num, node.long_name, node.short_name),
            "short_name": node.short_name,
            "long_name": node.long_name,
            "lat": node.last_lat,
            "lon": node.last_lon,
            "altitude": node.last_altitude,
            "last_heard": node.last_heard,
            "hw_model": node.hw_model,
            "role": node.role,
            "is_mqtt_gateway": node.is_mqtt_gateway,
        }
        for node in nodes
    ]


def portnum_name(value: int | None) -> str | None:
    """Return the readable name of a port number.

    An unknown number keeps its digits rather than raising: the firmware
    can send a port this build of the protobufs has never heard of.
    """
    if value is None:
        return None
    try:
        return str(portnums_pb2.PortNum.Name(value))  # type: ignore[attr-defined]
    except ValueError:
        return str(value)


@router.get("/traffic")
async def traffic(
    minutes: int = Query(default=15, ge=1, le=1440),
    limit: int = Query(default=300, ge=1, le=2000),
    channel: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    """Return recent packet observations for the live traffic layer.

    Each event holds the sender, the gateway that heard it, and what
    kind of packet it was. Every packet family is included: position,
    telemetry, node info, text, traceroute, and the rest.

    The `channel` parameter selects one modem preset. A node on one
    preset cannot hear a node on another, so a map layer must draw one
    at a time. See AGENTS.md 9.7.

    `direct` says whether those two are really in range of each other.
    An observation is direct only when the packet used no hop:

        packet.hop_start = packet_seen.hop_limit

    Most observations are not direct. In live traffic about 82 percent
    were relayed and only 5 percent were direct, so a line drawn for a
    relayed observation crosses ground the signal never took. A client
    must read this flag before it draws the line as a radio link. See
    AGENTS.md 9.5.
    """
    since = datetime.now(UTC) - timedelta(minutes=minutes)
    rows = (
        await session.scalars(
            select(PacketSeen)
            .where(PacketSeen.seen_at >= since, channel_filter(PacketSeen.channel, channel))
            .order_by(PacketSeen.seen_at.desc())
            .limit(limit)
        )
    ).all()

    # The hop count a packet started with is on the packet, not on the
    # observation, so it takes a second read. Only the packets in this
    # window are wanted.
    hop_starts: dict[tuple[int, int], int | None] = {}
    portnums: dict[tuple[int, int], str | None] = {}
    keys = {(row.from_node_num, row.packet_id) for row in rows}
    if keys:
        packet_rows = await session.execute(
            select(Packet.from_node_num, Packet.packet_id, Packet.hop_start, Packet.portnum).where(
                tuple_(Packet.from_node_num, Packet.packet_id).in_(keys)
            )
        )
        for from_node_num, packet_id, hop_start, portnum in packet_rows.all():
            hop_starts[(from_node_num, packet_id)] = hop_start
            portnums[(from_node_num, packet_id)] = portnum_name(portnum)

    node_nums = {num for row in rows for num in (row.from_node_num, row.gateway_node_num)}
    known = {
        node.node_num: node
        for node in (await session.scalars(select(Node).where(Node.node_num.in_(node_nums)))).all()
    }
    names = await resolve_names(session, node_nums)

    def endpoint(num: int) -> dict[str, object]:
        """Return one end of a traffic line."""
        node = known.get(num)
        lat = None if node is None else node.last_lat
        lon = None if node is None else node.last_lon
        if not is_usable(lat, lon):
            lat, lon = None, None
        return {
            "node_id": format_node_id(num),
            "display_name": name_of(names, num),
            "lat": lat,
            "lon": lon,
        }

    events = []
    direct_count = 0
    for row in rows:
        source = endpoint(row.from_node_num)
        gateway = endpoint(row.gateway_node_num)
        hop_start = hop_starts.get((row.from_node_num, row.packet_id))
        # Unknown on either side means it cannot be called direct.
        direct = hop_start is not None and row.hop_limit is not None and hop_start == row.hop_limit
        if direct:
            direct_count += 1
        events.append(
            {
                "time": row.seen_at,
                "packet_id": row.packet_id,
                "channel": row.channel,
                "mqtt_topic": row.mqtt_topic,
                "snr": row.rx_snr,
                "rssi": row.rx_rssi,
                "hop_limit": row.hop_limit,
                "hop_start": hop_start,
                # How many hops the packet burned to reach this gateway.
                # Which nodes it passed through is not recorded anywhere:
                # an ordinary packet carries no route. The count is all
                # there is, so a client can at least say how far the line
                # it draws is from the ground the signal took.
                "hops_taken": (
                    None
                    if hop_start is None or row.hop_limit is None
                    else hop_start - row.hop_limit
                ),
                "direct": direct,
                # What kind of packet it was, so the feed can say more
                # than "something was heard".
                "portnum": portnums.get((row.from_node_num, row.packet_id)),
                "from": source,
                "gateway": gateway,
                "has_line": all(
                    value is not None
                    for value in (source["lat"], source["lon"], gateway["lat"], gateway["lon"])
                )
                and row.from_node_num != row.gateway_node_num,
            }
        )
    return {
        "window_minutes": minutes,
        "event_count": len(events),
        "direct_count": direct_count,
        "events": events,
    }


@router.get("/track/{node_id}")
async def track(
    node_id: str,
    hours: int = Query(default=24, ge=1, le=720),
    max_points: int = Query(default=500, ge=1, le=5000),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, object]]:
    """Return recent position history for one node."""
    node_num = _require_node_num(node_id)
    start = datetime.now(UTC) - timedelta(hours=hours)
    statement = (
        select(PositionMetrics)
        .where(PositionMetrics.node_num == node_num, PositionMetrics.time >= start)
        .order_by(PositionMetrics.time.asc())
        .limit(max_points)
    )
    return [
        {"time": row.time, "lat": row.latitude, "lon": row.longitude, "altitude": row.altitude}
        for row in (await session.scalars(statement)).all()
        if is_usable(row.latitude, row.longitude)
    ]


@router.get("/edges")
async def edges(
    hours: int = Query(default=12, ge=1, le=720),
    limit: int = Query(default=1000, ge=1, le=5000),
    channel: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, object]]:
    """Return recent neighbor links for map lines.

    A neighbor report names two nodes that hear each other directly, so
    a straight line between them is a real radio link.

    Traceroutes are deliberately absent. This endpoint used to add one
    line for each traceroute, drawn between the two ends of the trace.
    Those ends can be many hops apart and often have no link at all, so
    the line meant nothing. Use `/api/map/traceroute-paths`, which draws
    the hops the packet really took.

    The `channel` parameter selects one modem preset. A node on one
    preset cannot hear a node on another preset, so a map layer must
    draw one channel at a time. Without the parameter the response holds
    every channel together.
    """
    start = datetime.now(UTC) - timedelta(hours=hours)
    neighbor_rows = await session.scalars(
        select(NeighborMetrics)
        .where(NeighborMetrics.time >= start, channel_filter(NeighborMetrics.channel, channel))
        .order_by(NeighborMetrics.time.desc())
        .limit(limit)
    )
    edges: list[dict[str, object]] = [
        {
            "from_node": format_node_id(row.node_num),
            "to_node": format_node_id(row.neighbor_node_num),
            "snr": row.snr,
            "kind": "neighbor",
            "channel": row.channel,
            "time": row.time,
        }
        for row in neighbor_rows.all()
    ]
    edges.sort(key=lambda edge: cast(datetime, edge["time"]), reverse=True)
    return edges[:limit]


@router.get("/traceroute-paths")
async def traceroute_paths(
    minutes: int = Query(default=15, ge=1, le=1440),
    limit: int = Query(default=40, ge=1, le=200),
    channel: str | None = None,
    completed_only: bool = True,
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    """Return recent traceroutes as the chain of hops they really took.

    The map animates each of these along its path as it arrives, so the
    lines it draws are links that carried the packet.

    Only completed traceroutes are returned by default. Anybody can send
    a request to any node, and most never come back: in live traffic
    1,278 of 1,808 in a day were requests with no reply. A request only
    says somebody asked. Its hop list is whatever the packet managed on
    the way out, which is not a path to the node that was asked, and
    drawing it claims a route that was never proved.

    A reply is the proof. It carries `request_id`, which is how a reply
    is told from a request, and it travelled the whole way back.

    Set `completed_only` to false to see the attempts as well.

    A hop is drawn only when both of its ends have a position. The rest
    are reported with `has_line` false, so the client can count them
    without drawing a line that would be wrong.

    SNR readings are in quarter dB and the firmware writes INT8_MIN for
    a hop it could not measure. Both are handled here, so the client
    receives dB or null. See AGENTS.md 9.6.
    """
    since = datetime.now(UTC) - timedelta(minutes=minutes)
    conditions = [Traceroute.seen_at >= since, channel_filter(Traceroute.channel, channel)]
    if completed_only:
        # A reply answers a request, so it is the only row that carries
        # the request ID. See AGENTS.md 9.8.
        conditions.append(Traceroute.request_id.is_not(None))
    rows = (
        await session.scalars(
            select(Traceroute).where(*conditions).order_by(Traceroute.seen_at.desc()).limit(limit)
        )
    ).all()

    node_nums = {num for row in rows for num in _path_of(row)}
    known = {
        node.node_num: node
        for node in (await session.scalars(select(Node).where(Node.node_num.in_(node_nums)))).all()
    }
    names = await resolve_names(session, node_nums)

    def point(num: int) -> dict[str, object]:
        """Return one node on a path."""
        node = known.get(num)
        lat = None if node is None else node.last_lat
        lon = None if node is None else node.last_lon
        if not is_usable(lat, lon):
            lat, lon = None, None
        return {
            "node_id": format_node_id(num),
            "display_name": name_of(names, num),
            "lat": lat,
            "lon": lon,
        }

    traces = []
    for row in rows:
        path = _path_of(row)
        points = [point(num) for num in path]
        snrs = _hop_snrs(row, len(points) - 1)
        hops = [
            {
                "from": points[index],
                "to": points[index + 1],
                "snr": snrs[index],
                "has_line": all(
                    value is not None
                    for value in (
                        points[index]["lat"],
                        points[index]["lon"],
                        points[index + 1]["lat"],
                        points[index + 1]["lon"],
                    )
                )
                and path[index] != path[index + 1],
            }
            for index in range(len(points) - 1)
        ]
        traces.append(
            {
                # The row identity, which is what `#traceroute/{id}`
                # opens. `trace_id` is the mesh-graph key and is not the
                # same thing: a reply is keyed on the request it answers.
                "id": row.id,
                "trace_id": row.request_id or row.packet_id,
                "time": row.seen_at,
                "channel": row.channel,
                "is_reply": is_reply(row),
                "from": points[0],
                "to": points[-1],
                # The number of links drawn, which is one more than the
                # "hops" the traceroute pages report: those count the
                # nodes in between, this counts the segments.
                "link_count": len(hops),
                "hops": hops,
            }
        )
    return {
        "window_minutes": minutes,
        "completed_only": completed_only,
        "trace_count": len(traces),
        "traces": traces,
    }
