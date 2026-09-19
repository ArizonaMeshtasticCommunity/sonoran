"""Read-only mesh graph endpoints.

The graph page draws the nodes of one channel and the links between
them. A link comes from a neighbor report or from a traceroute hop. The
response is ready to draw. The browser does no join.

One graph holds one channel. A LoRa modem preset is a different radio
configuration, so a node on LongFast cannot hear a node on MediumFast.
Drawing them together would show links that cannot exist.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import and_, func, or_, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from sonoran.api.channels import CORE_TIER, UNKNOWN_CHANNEL, channel_filter, classify
from sonoran.api.dependencies import get_session, require_node_num
from sonoran.api.names import BROADCAST_NODE_NUM, format_node_id, name_of, resolve_names
from sonoran.api.traces import (
    SNR_SCALE,
    UNKNOWN_SNR,
    evidenced_hops,
    forward_path,
    is_reply,
)
from sonoran.db.models import NeighborMetrics, Node, Packet, PacketSeen, Traceroute
from sonoran.positions import clean

router = APIRouter(prefix="/api/graph", tags=["graph"])

NEIGHBOR_KIND = "neighbor"
TRACEROUTE_KIND = "traceroute"

__all__ = ["SNR_SCALE", "UNKNOWN_SNR", "router"]


@dataclass
class Edge:
    """One link between two nodes."""

    source: int
    target: int
    kind: str
    snr: float | None
    time: datetime
    count: int = 1
    # Whether anything that completed evidences this link. A neighbor
    # report always does: a node names a neighbour it hears itself. A
    # traceroute does when it is a reply, because the request reached
    # the far end and came back.
    #
    # A request that was never answered is the other case. The broker
    # saw it in flight, so the hops it had already made are real and
    # measured. Nothing confirmed the round trip, so the evidence runs
    # one way. Such links are true but weaker, and a page may want to
    # tell them apart.
    confirmed: bool = True

    def as_json(self) -> dict[str, object]:
        """Return the public form of this link."""
        return {
            "source": format_node_id(self.source),
            "target": format_node_id(self.target),
            "kind": self.kind,
            "snr": self.snr,
            "count": self.count,
            "confirmed": self.confirmed,
            "time": self.time,
        }


EdgeMap = dict[tuple[int, int], Edge]


def _key(a: int, b: int) -> tuple[int, int]:
    """Return one key for a link, in either direction."""
    return (a, b) if a <= b else (b, a)


def _is_node(value: int) -> bool:
    """Return true when a value names a real node.

    The broadcast address is a destination, not a radio. A traceroute
    addressed to everyone would otherwise draw a node called Everyone
    that every path connects to.
    """
    return bool(value) and value != BROADCAST_NODE_NUM


def _add(edges: EdgeMap, edge: Edge) -> None:
    """Add a link, or count one more sighting of a known link.

    A measured SNR always beats no SNR. Many reports carry no value for
    the last hop, so keeping only the first report would leave a link
    unmeasured even when a later report measured it. Between two
    measured values the newer one wins.

    Confirmation works the same way round. One report that completed is
    enough, so a link seen first by an unanswered request and later by a
    reply counts as confirmed.
    """
    if not (_is_node(edge.source) and _is_node(edge.target)):
        return
    key = _key(edge.source, edge.target)
    known = edges.get(key)
    if known is None:
        edges[key] = edge
        return
    known.count += 1
    known.confirmed = known.confirmed or edge.confirmed
    if edge.snr is not None and (known.snr is None or edge.time > known.time):
        known.snr = edge.snr
        known.time = max(known.time, edge.time)


async def _neighbor_edges(
    session: AsyncSession, since: datetime, limit: int, channel: str | None
) -> EdgeMap:
    """Return the links that recent neighbor reports show on one channel."""
    statement = (
        select(NeighborMetrics)
        .where(NeighborMetrics.time >= since, channel_filter(NeighborMetrics.channel, channel))
        .order_by(NeighborMetrics.time.desc())
        .limit(limit)
    )
    rows = (await session.scalars(statement)).all()
    edges: EdgeMap = {}
    for row in rows:
        if row.node_num == row.neighbor_node_num:
            continue
        _add(
            edges,
            Edge(
                source=row.node_num,
                target=row.neighbor_node_num,
                kind=NEIGHBOR_KIND,
                snr=row.snr,
                time=row.time,
            ),
        )
    return edges


def _trace_links(row: Traceroute) -> list[tuple[int, int, float | None, int, int]]:
    """Return the links one traceroute proves.

    Each item holds the two ends, the reading, the position of the hop,
    and how many hops the whole path claims.

    The graph and the link page both read a row through this one
    function. They used to hold a copy each, and the copies disagreed:
    the graph drew links that the link page could then find no evidence
    for. See `sonoran.api.traces` for the three rules that apply.
    """
    path = forward_path(row)
    hops, _ = evidenced_hops(path, list(row.snr_towards or []))
    claimed = max(len(path) - 1, 0)
    return [
        (source, target, snr, index + 1, claimed)
        for index, (source, target, snr) in enumerate(hops)
        if source != target
    ]


async def _traceroute_edges(
    session: AsyncSession, since: datetime, limit: int, channel: str | None
) -> EdgeMap:
    """Return the links that recent traceroutes show.

    There is one link between each pair of hops that follow each other,
    for as far along the path as the report reached.
    """
    statement = (
        select(Traceroute)
        .where(Traceroute.seen_at >= since, channel_filter(Traceroute.channel, channel))
        .order_by(Traceroute.seen_at.desc())
        .limit(limit)
    )
    rows = (await session.scalars(statement)).all()
    edges: EdgeMap = {}
    for row in rows:
        confirmed = is_reply(row)
        for source, target, snr, _position, _claimed in _trace_links(row):
            _add(
                edges,
                Edge(
                    source=source,
                    target=target,
                    kind=TRACEROUTE_KIND,
                    snr=snr,
                    time=row.seen_at,
                    confirmed=confirmed,
                ),
            )
    return edges


async def _packet_counts(session: AsyncSession, since: datetime) -> dict[int, int]:
    """Return the packet count of each node in the window."""
    rows = await session.execute(
        select(Packet.from_node_num, func.count().label("count"))
        .where(Packet.first_seen_at >= since)
        .group_by(Packet.from_node_num)
    )
    return {node_num: count for node_num, count in rows.all()}


def _node_json(
    node_num: int,
    node: Node | None,
    name: str,
    packet_count: int,
) -> dict[str, object]:
    """Return the public form of one graph node.

    The position comes with it so the page can lay the graph out over
    the ground it really sits on. A mesh is a geographic thing: the two
    clusters a reader picks out of the web are Phoenix and Tucson, and
    a layout that starts from nowhere hides that. Only about six nodes
    in ten report a position, so a client has to seed the rest itself.
    """
    lat, lon = clean(
        None if node is None else node.last_lat,
        None if node is None else node.last_lon,
    )
    return {
        "node_id": format_node_id(node_num),
        "node_num": node_num,
        "display_name": name,
        "short_name": None if node is None else node.short_name,
        "role": None if node is None else node.role,
        "hw_model": None if node is None else node.hw_model,
        "is_mqtt_gateway": bool(node is not None and node.is_mqtt_gateway),
        "lat": lat,
        "lon": lon,
        "has_position": lat is not None,
        "last_heard": None if node is None else node.last_heard,
        "packet_count": packet_count,
        "known": node is not None,
    }


async def _channel_link_counts(session: AsyncSession, since: datetime) -> dict[str | None, int]:
    """Return how many link reports each channel has in the window."""
    counts: dict[str | None, int] = {}
    neighbor_rows = await session.execute(
        select(NeighborMetrics.channel, func.count().label("total"))
        .where(NeighborMetrics.time >= since)
        .group_by(NeighborMetrics.channel)
    )
    traceroute_rows = await session.execute(
        select(Traceroute.channel, func.count().label("total"))
        .where(Traceroute.seen_at >= since)
        .group_by(Traceroute.channel)
    )
    for rows in (neighbor_rows, traceroute_rows):
        for channel, total in rows.all():
            counts[channel] = counts.get(channel, 0) + total
    return counts


async def _channel_packet_counts(session: AsyncSession, since: datetime) -> dict[str | None, int]:
    """Return how many observations each channel has in the window.

    A channel can carry plenty of traffic and still evidence no link: a
    chat or weather channel produces no neighbor report and no
    traceroute. Counting packets as well means such a channel still
    appears in the pickers, so the live traffic layer can be pointed at
    it.
    """
    rows = await session.execute(
        select(PacketSeen.channel, func.count().label("total"))
        .where(PacketSeen.seen_at >= since)
        .group_by(PacketSeen.channel)
    )
    return {channel: total for channel, total in rows.all()}


@router.get("/channels")
async def graph_channels(
    request: Request,
    hours: int = Query(default=24, ge=1, le=720),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    """Return every channel that has mesh links in the window.

    The graph page draws one graph for each of these channels. The
    busiest channel comes first, so the page can select it by default.

    Each channel carries a `tier`. A `core` channel is a modem preset or
    one of the channels this deployment claims as its own; everything
    else is `extra`. The pickers show the two apart, so the mesh proper
    is not buried among the special interest channels.

    Core channels sort before extra ones, so the default selection is
    always a channel the mesh really runs on.

    Links with no channel always sort last, whatever their count. They
    are not a real channel. They were stored before revision 0007 added
    the column, so one graph of them mixes every preset together. A
    large backlog of them must never become the default tab.
    """
    since = datetime.now(UTC) - timedelta(hours=hours)
    links = await _channel_link_counts(session, since)
    packets = await _channel_packet_counts(session, since)
    core = tuple(request.app.state.settings.core_channels)

    ordered = sorted(
        set(links) | set(packets),
        key=lambda name: (
            name is None,
            classify(name, core)["tier"] != CORE_TIER,
            -(links.get(name, 0) + packets.get(name, 0)),
        ),
    )
    channels: list[dict[str, object]] = []
    for name in ordered:
        record: dict[str, object] = dict(classify(name, core))
        if not name:
            record["channel"] = UNKNOWN_CHANNEL
            record["label"] = "Before channel tracking"
            record["group"] = "Unknown"
            record["mixed_presets"] = True
        channels.append(
            record
            | {
                "link_report_count": links.get(name, 0),
                "packet_count": packets.get(name, 0),
            }
        )
    return {"window_hours": hours, "channels": channels}


def _mentions(node: int) -> ColumnElement[bool]:
    """Return the filter that selects the traceroutes naming one node.

    A node appears as an end of the trace or as a hop inside its route.

    This filter has to exist. Without it the query took the newest rows
    and hoped the link was among them, while the graph read four times
    as many. A mesh that logs two thousand traceroutes a day then drew
    plenty of links whose evidence lay outside the smaller window, and
    clicking one showed an empty page. Selecting by node instead of by
    recency means the row limit can no longer hide a link from itself.
    """
    return or_(
        Traceroute.from_node_num == node,
        Traceroute.to_node_num == node,
        Traceroute.route.cast(JSONB).contains([node]),
    )


async def _link_reports(
    session: AsyncSession, a: int, b: int, since: datetime, channel: str | None
) -> list[dict[str, object]]:
    """Return the reports that evidence one link, newest first.

    A neighbor report names both nodes directly. A traceroute evidences
    a link when the two nodes follow each other in its path.
    """
    neighbours = (
        await session.scalars(
            select(NeighborMetrics)
            .where(
                NeighborMetrics.time >= since,
                channel_filter(NeighborMetrics.channel, channel),
                or_(
                    and_(NeighborMetrics.node_num == a, NeighborMetrics.neighbor_node_num == b),
                    and_(NeighborMetrics.node_num == b, NeighborMetrics.neighbor_node_num == a),
                ),
            )
            .order_by(NeighborMetrics.time.desc())
            .limit(50)
        )
    ).all()

    reports: list[dict[str, object]] = [
        {
            "kind": NEIGHBOR_KIND,
            "reported_by": format_node_id(row.node_num),
            "packet_id": row.packet_id,
            "channel": row.channel,
            "snr": row.snr,
            "time": row.time,
        }
        for row in neighbours
    ]

    traces = (
        await session.scalars(
            select(Traceroute)
            .where(
                Traceroute.seen_at >= since,
                channel_filter(Traceroute.channel, channel),
                _mentions(a),
                _mentions(b),
            )
            .order_by(Traceroute.seen_at.desc())
            .limit(500)
        )
    ).all()
    for row in traces:
        for source, target, snr, position, claimed in _trace_links(row):
            if {source, target} != {a, b}:
                continue
            reports.append(
                {
                    "kind": TRACEROUTE_KIND,
                    "reported_by": format_node_id(row.from_node_num),
                    "packet_id": row.packet_id,
                    "channel": row.channel,
                    "snr": snr,
                    "hop": position,
                    "path_length": claimed,
                    "time": row.seen_at,
                }
            )
    reports.sort(key=lambda item: cast(datetime, item["time"]), reverse=True)
    return reports[:50]


@router.get("/link")
async def graph_link(
    a: str,
    b: str,
    hours: int = Query(default=24, ge=1, le=720),
    channel: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    """Return the evidence behind one link on the graph.

    Every report names the packet that carried it, so the packet itself
    can be opened from here.
    """
    first, second = require_node_num(a), require_node_num(b)
    since = datetime.now(UTC) - timedelta(hours=hours)
    reports = await _link_reports(session, first, second, since, channel)
    names = await resolve_names(session, (first, second))
    measured = [
        value
        for report in reports
        if isinstance(value := report["snr"], int | float) and not isinstance(value, bool)
    ]
    return {
        "a": {"node_id": format_node_id(first), "display_name": name_of(names, first)},
        "b": {"node_id": format_node_id(second), "display_name": name_of(names, second)},
        "window_hours": hours,
        "report_count": len(reports),
        "best_snr": max(measured) if measured else None,
        "reports": reports,
    }


@router.get("")
async def mesh_graph(
    hours: int = Query(default=24, ge=1, le=720),
    limit: int = Query(default=2000, ge=1, le=10000),
    channel: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    """Return the mesh of one channel as nodes and links.

    A neighbor link replaces a traceroute link between the same two
    nodes. The neighbor report carries a measured SNR.

    The `channel` parameter selects the preset. Without it the response
    holds every channel together. Nodes of different presets cannot hear
    each other, so a page must ask for one channel at a time.
    """
    since = datetime.now(UTC) - timedelta(hours=hours)
    edges = await _traceroute_edges(session, since, limit, channel)
    edges.update(await _neighbor_edges(session, since, limit, channel))

    node_nums: set[int] = set()
    for edge in edges.values():
        node_nums.update((edge.source, edge.target))

    rows = (await session.scalars(select(Node).where(Node.node_num.in_(node_nums)))).all()
    known = {row.node_num: row for row in rows}
    names = await resolve_names(session, node_nums)
    counts = await _packet_counts(session, since)

    nodes = [
        _node_json(num, known.get(num), name_of(names, num), counts.get(num, 0))
        for num in sorted(node_nums)
    ]
    links = [edge.as_json() for edge in edges.values()]
    return {
        "window_hours": hours,
        "channel": channel,
        "node_count": len(nodes),
        "link_count": len(links),
        "nodes": nodes,
        "links": links,
    }
