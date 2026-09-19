"""Read-only node endpoints."""

from datetime import UTC, datetime, timedelta
from typing import Any, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import ColumnElement, Select, and_, case, func, not_, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from sonoran.api.dependencies import (
    LIKE_ESCAPE,
    contains,
    get_session,
    parse_node_id,
    require_node_num,
)
from sonoran.api.names import display_name, format_node_id, name_of, resolve_names
from sonoran.api.schemas import NodeSummary
from sonoran.config import Settings
from sonoran.coverage.store import calibration_offsets
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
from sonoran.gaps import store as gaps_store
from sonoran.gaps.signals import position_confidence
from sonoran.meshtastic import portnums_pb2
from sonoran.positions import MIN_SITE_PRECISION_BITS, NULL_ISLAND_MARGIN, is_usable
from sonoran.radio.resolve import resolve_profile

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
        channel=node.last_channel,
        is_licensed=node.is_licensed,
        # The same three words the gaps assessment uses, from the same
        # rule, so a reader who sees "coarse" on one page and "coarse"
        # on the other is being told the same thing.
        position_confidence=position_confidence(
            node.last_lat, node.last_lon, node.last_position_precision_bits, MIN_SITE_PRECISION_BITS
        )[0],
    )


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

    A gateway that is the node itself uploads its own voice. Every such
    row has the hop limits equal, so the hop rule alone calls it direct
    and then offers the node's own reading as a radio link to itself. It
    must not count as direct. See AGENTS.md 9.5.1.
    """
    direct = and_(
        Packet.hop_start == PacketSeen.hop_limit,
        PacketSeen.from_node_num != PacketSeen.gateway_node_num,
    )
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


# The columns the list may be ordered by, and what each one means.
#
# A whitelist, not a lookup of whatever arrived: nothing a caller sends
# reaches the query. `name` orders by what the column actually shows,
# which is the long name, then the short name, then the ID — sorting by
# `long_name` alone would scatter the unnamed nodes through the middle
# of the alphabet rather than gathering them at the end.
SORTS: dict[str, Any] = {
    "last_heard": Node.last_heard,
    "first_seen": Node.first_seen,
    "name": func.lower(func.coalesce(Node.long_name, Node.short_name, Node.node_id)),
    "node_id": Node.node_num,
    "hw": Node.hw_model,
    "role": Node.role,
    "channel": Node.last_channel,
    "position": Node.last_position_precision_bits,
}


def _usable_position() -> ColumnElement[bool]:
    """The SQL form of `positions.is_usable`.

    It has to be the same rule the gaps page applies in Python, or the
    two disagree about the same node. Null island needs both values, not
    either: a node really can sit on the equator, and one really can sit
    on the meridian.
    """
    return and_(
        Node.last_lat.is_not(None),
        Node.last_lon.is_not(None),
        not_(
            and_(
                func.abs(Node.last_lat) <= NULL_ISLAND_MARGIN,
                func.abs(Node.last_lon) <= NULL_ISLAND_MARGIN,
            )
        ),
    )


def _position_filter(value: str) -> ColumnElement[bool]:
    """Select nodes by how well their position is known.

    `exact`, `coarse`, `none`, matching `gaps.signals.position_confidence`.
    A NULL precision is **exact**, not missing: a node that sent no
    precision field at all is the ordinary case for one heard over the
    radio, and it is full precision. See `positions.is_precise_enough`.
    """
    usable = _usable_position()
    if value == "none":
        return not_(usable)
    coarse = and_(
        Node.last_position_precision_bits.is_not(None),
        Node.last_position_precision_bits < MIN_SITE_PRECISION_BITS,
    )
    if value == "coarse":
        return and_(usable, coarse)
    return and_(usable, not_(coarse))


def _apply_node_filters(
    statement: Select[Any],
    q: str | None,
    hw: str | None,
    role: str | None,
    gateway: bool | None,
    active_hours: int | None,
    before: datetime | None,
    channel: str | None = None,
    position: str | None = None,
    licensed: bool | None = None,
    first_seen_hours: int | None = None,
) -> Select[Any]:
    """Apply the documented node list filters to a statement.

    Typed loosely on purpose: the same predicates are applied to the
    select that returns rows and to the one that counts them, so that
    the count can never drift from the page it describes.
    """
    if q:
        match = contains(q)
        predicates: list[ColumnElement[bool]] = [
            Node.long_name.ilike(match, escape=LIKE_ESCAPE),
            Node.short_name.ilike(match, escape=LIKE_ESCAPE),
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
    if channel:
        statement = statement.where(Node.last_channel == channel)
    if position:
        statement = statement.where(_position_filter(position))
    if licensed is not None:
        statement = statement.where(Node.is_licensed == licensed)
    if first_seen_hours is not None:
        statement = statement.where(
            Node.first_seen >= datetime.now(UTC) - timedelta(hours=first_seen_hours)
        )
    return statement


@router.get("", response_model=list[NodeSummary])
async def list_nodes(
    request: Request,
    response: Response,
    q: str | None = None,
    hw: str | None = None,
    role: str | None = None,
    gateway: bool | None = None,
    active_hours: int | None = Query(default=None, ge=1, le=720),
    before: datetime | None = None,
    channel: str | None = None,
    position: str | None = Query(default=None, pattern="^(exact|coarse|none)$"),
    licensed: bool | None = None,
    first_seen_hours: int | None = Query(default=None, ge=1, le=8760),
    gaps: str | None = Query(default=None, pattern="^(bad|ok|unknown)$"),
    gaps_preset: str | None = None,
    sort: str = Query(default="last_heard"),
    order: str = Query(default="desc", pattern="^(asc|desc)$"),
    offset: int = Query(default=0, ge=0, le=100_000),
    limit: int = Query(default=100, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
) -> list[NodeSummary]:
    """Return nodes, ordered by one of the documented columns.

    The body stays a bare array, because this endpoint is documented and
    something outside this repository may read it. The count of
    everything matching the filters travels in `X-Total-Count`.

    That count is the point of the header rather than a nicety. The list
    is capped, and a page that counts the rows it received reports the
    cap: it said "300 nodes match" on a mesh of 2,372. The same fault is
    recorded against `/api/map/traffic` in its own docstring.

    **Ordering happens here, never in the browser.** Sorting the rows a
    caller happens to hold would sort the most recently heard 500 by
    name and present the answer as the first 500 by name. Those are
    different sets and a reader cannot tell them apart by looking.
    """
    if sort not in SORTS:
        raise HTTPException(
            status_code=422,
            detail=f"sort must be one of: {', '.join(sorted(SORTS))}",
        )
    column = SORTS[sort]
    direction = column.asc() if order == "asc" else column.desc()

    # Nulls last whichever way it was clicked. A node with no role is
    # not the smallest role, and a reader scanning a column wants the
    # rows that have nothing to say out of the way.
    #
    # `node_num` breaks the tie. Without it Postgres may order equal
    # rows differently between two queries, so a node could arrive on
    # two pages or on neither. With 160 nodes reporting no role at all,
    # ties are the ordinary case here rather than an edge.
    ordering = (direction.nullslast(), Node.node_num.asc())

    filters = (q, hw, role, gateway, active_hours, before, channel, position, licensed)
    statement = _apply_node_filters(select(Node), *filters, first_seen_hours)
    counted = _apply_node_filters(
        select(func.count()).select_from(Node), *filters, first_seen_hours
    )

    # The gaps state is per preset, because a node can need help on one
    # mesh and be fine on another. Merging them would be the thing
    # AGENTS.md 9.7 forbids everywhere else, wearing a filter's clothes.
    if gaps:
        if not gaps_preset:
            raise HTTPException(
                status_code=422,
                detail="gaps needs gaps_preset: a node can need help on one preset and not another",
            )
        wanted = _gaps_node_nums(request, gaps_preset, gaps)
        if wanted is None:
            # Not an empty result. Nothing has been assessed, and saying
            # "no nodes" would be an answer we do not have.
            raise HTTPException(
                status_code=409,
                detail=f"no gap assessment has been written for {gaps_preset} yet",
            )
        statement = statement.where(Node.node_num.in_(wanted))
        counted = counted.where(Node.node_num.in_(wanted))

    total = await session.scalar(counted)
    response.headers["X-Total-Count"] = str(total or 0)

    rows = (await session.scalars(statement.order_by(*ordering).offset(offset).limit(limit))).all()
    return [_summary(node) for node in rows]


def _gaps_node_nums(request: Request, preset: str, state: str) -> set[int] | None:
    """Return the nodes the gaps assessment puts in one state, or None.

    None means no assessment has been written for that preset, which is
    a different answer from "no nodes are in that state" and must not be
    served as an empty filter that silently matches nothing.

    This reads the artefact the gaps job already wrote, through the same
    store its own routes use. It recomputes nothing and asks the
    database for nothing.
    """
    settings: Settings = request.app.state.settings
    assessment = gaps_store.read_preset(settings, preset)
    if assessment is None:
        return None
    wanted: set[int] = set()
    nodes = cast(list[dict[str, object]], assessment.get("nodes") or [])
    for node in nodes:
        if node.get("worst_state") == state:
            try:
                wanted.add(parse_node_id(str(node["node_id"])))
            except (KeyError, ValueError):
                continue
    return wanted


@router.get("/facets")
async def node_facets(
    request: Request,
    q: str | None = None,
    hw: str | None = None,
    role: str | None = None,
    gateway: bool | None = None,
    active_hours: int | None = Query(default=None, ge=1, le=720),
    before: datetime | None = None,
    channel: str | None = None,
    position: str | None = Query(default=None, pattern="^(exact|coarse|none)$"),
    licensed: bool | None = None,
    first_seen_hours: int | None = Query(default=None, ge=1, le=8760),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    """Return the values each filter could take, and how many nodes each holds.

    A picker that lists forty hardware models and says nothing about
    them makes a reader guess which ones this mesh actually has. With a
    count beside each value the choice is visible before it is made,
    and a value with no nodes behind it can be left out rather than
    offered and then disappointing.

    **The counts are of the other filters, not of this one.** Narrowing
    to one role and then reading the role counts would show that role
    holding everything and the rest holding nothing, which says only
    that the filter is applied. So each facet is counted with its own
    filter lifted and the rest in force, which is the number a reader
    is actually asking for: "if I also picked this, how many would I
    have".
    """

    async def counts(column: Any, lifted: str) -> list[dict[str, object]]:
        # Each facet is counted with its own filter lifted and the rest
        # in force. Counting a facet with itself applied would show the
        # chosen value holding everything and the others holding
        # nothing, which tells a reader only that the filter is on.
        statement = _apply_node_filters(
            select(column, func.count()).select_from(Node),
            None if lifted == "q" else q,
            None if lifted == "hw" else hw,
            None if lifted == "role" else role,
            None if lifted == "gateway" else gateway,
            None if lifted == "active_hours" else active_hours,
            before,
            None if lifted == "channel" else channel,
            None if lifted == "position" else position,
            None if lifted == "licensed" else licensed,
            None if lifted == "first_seen_hours" else first_seen_hours,
        ).group_by(column)
        rows = (await session.execute(statement)).all()
        return [
            {"value": value, "count": total}
            for value, total in sorted(rows, key=lambda row: (-row[1], str(row[0])))
            if value is not None
        ]

    positions = _apply_node_filters(
        select(
            case(
                (not_(_usable_position()), "none"),
                (
                    and_(
                        Node.last_position_precision_bits.is_not(None),
                        Node.last_position_precision_bits < MIN_SITE_PRECISION_BITS,
                    ),
                    "coarse",
                ),
                else_="exact",
            ).label("state"),
            func.count(),
        ).select_from(Node),
        q,
        hw,
        role,
        gateway,
        active_hours,
        before,
        channel,
        None,
        licensed,
        first_seen_hours,
    ).group_by("state")

    # The gaps states, per preset, because a node can need help on one
    # mesh and be fine on another. Offering "needs help" without saying
    # on which would be the merge AGENTS.md 9.7 forbids.
    settings: Settings = request.app.state.settings
    gaps_options: list[dict[str, object]] = []
    index = gaps_store.read_index(settings) or {}
    for entry in cast(list[dict[str, object]], index.get("presets") or []):
        preset = str(entry.get("preset") or "")
        if not preset:
            continue
        for state in ("bad", "unknown"):
            wanted = _gaps_node_nums(request, preset, state)
            if not wanted:
                continue
            total = await session.scalar(
                _apply_node_filters(
                    select(func.count()).select_from(Node),
                    q,
                    hw,
                    role,
                    gateway,
                    active_hours,
                    before,
                    channel,
                    position,
                    licensed,
                    first_seen_hours,
                ).where(Node.node_num.in_(wanted))
            )
            if total:
                gaps_options.append({"preset": preset, "state": state, "count": total})

    return {
        "gaps": gaps_options,
        "hw": await counts(Node.hw_model, "hw"),
        "role": await counts(Node.role, "role"),
        "channel": await counts(Node.last_channel, "channel"),
        "position": [
            {"value": state, "count": total}
            for state, total in (await session.execute(positions)).all()
        ],
        "gateway": await counts(Node.is_mqtt_gateway, "gateway"),
        "licensed": await counts(Node.is_licensed, "licensed"),
    }


@router.get("/{node_id}", response_model=NodeSummary)
async def get_node(node_id: str, session: AsyncSession = Depends(get_session)) -> NodeSummary:
    """Return one node by documented node ID form."""
    node = await session.get(Node, require_node_num(node_id))
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
    node_num = require_node_num(node_id)
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
    node_num = require_node_num(node_id)
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
        select(NodeConfig).where(NodeConfig.node_num == require_node_num(node_id))
    )
    return [
        {"type": item.config_type, "value": item.config_json, "updated_at": item.updated_at}
        for item in rows.all()
    ]


@router.get("/{node_id}/radio")
async def node_radio(
    node_id: str, request: Request, session: AsyncSession = Depends(get_session)
) -> dict[str, object]:
    """Return the radio characteristics a prediction would use.

    The mesh reports the hardware model and nothing else about the
    radio. The rest comes from the overrides file and from the
    calibration job. `sources` says where each value came from, so a
    reader can tell a measurement from a guess.
    """
    node_num = require_node_num(node_id)
    node = await session.scalar(select(Node).where(Node.node_num == node_num))
    if node is None:
        raise HTTPException(status_code=404, detail="node not found")

    identifier = format_node_id(node_num)
    settings = request.app.state.settings
    overrides = request.app.state.radio_overrides
    offsets = calibration_offsets(settings)
    profile = resolve_profile(
        identifier, node.hw_model, overrides, offsets.get(identifier), role=node.role
    )

    return {
        "node_id": identifier,
        "display_name": display_name(node_num, node.long_name, node.short_name),
        "hw_model": node.hw_model,
        "chipset": profile.chipset,
        "hardware_inferred": profile.hardware_inferred,
        "tx_power_dbm": profile.tx_power_dbm,
        "antenna_gain_dbi": profile.antenna_gain_dbi,
        "antenna_height_m": profile.antenna_height_m,
        "cable_loss_db": profile.cable_loss_db,
        "above_clutter": profile.above_clutter,
        "eirp_dbm": round(profile.eirp_dbm, 2),
        "effective_eirp_dbm": round(profile.effective_eirp_dbm, 2),
        "calibration_offset_db": profile.calibration_offset_db,
        "is_measured": profile.is_measured,
        "locked": profile.locked,
        "note": overrides.for_node(identifier).note,
        "sources": dict(profile.sources),
    }


@router.get("/{node_id}/heard-by")
async def heard_by(
    node_id: str,
    hours: int = Query(default=24, ge=1, le=720),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, object]]:
    """Return gateways that observed packets from one node."""
    since = datetime.now(UTC) - timedelta(hours=hours)
    return await _heard_by(session, require_node_num(node_id), since)


@router.get("/{node_id}/packets")
async def node_packets(
    node_id: str,
    limit: int = Query(default=100, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, object]]:
    """Return recent packets from one node."""
    rows = await session.scalars(
        select(Packet)
        .where(Packet.from_node_num == require_node_num(node_id))
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
    node_num = require_node_num(node_id)
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
    node = format_node_id(require_node_num(node_id))
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
    return await _latest_neighbors(session, require_node_num(node_id), limit=100)
