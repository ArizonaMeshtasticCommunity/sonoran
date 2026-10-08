"""Read-only node endpoints."""

import base64
import binascii
import json
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import (
    ColumnElement,
    Select,
    and_,
    case,
    func,
    literal,
    not_,
    or_,
    select,
    true,
    tuple_,
)
from sqlalchemy.ext.asyncio import AsyncSession

from sonoran.api.dependencies import (
    LIKE_ESCAPE,
    contains,
    get_session,
    parse_node_id,
    require_node_num,
)
from sonoran.api.names import display_name, format_node_id, name_of, resolve_names
from sonoran.api.preset_scope import preset_filter, require_preset
from sonoran.api.schemas import NodeSummary
from sonoran.api.sightings import direct as direct_sighting
from sonoran.api.sightings import sightings
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
from sonoran.decode.portnums import traffic_label
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
    seen = sightings(PacketSeen.from_node_num == node_num, PacketSeen.seen_at >= since, since=since)
    heard = direct_sighting(seen)
    statement = (
        select(
            seen.c.gateway_node_num,
            func.count().label("total"),
            func.count().filter(heard).label("direct_count"),
            func.max(seen.c.seen_at).label("last_heard"),
            func.avg(seen.c.rx_snr).filter(heard).label("avg_snr"),
            func.max(seen.c.rx_snr).filter(heard).label("best_snr"),
            func.avg(seen.c.rx_rssi).filter(heard).label("avg_rssi"),
        )
        .group_by(seen.c.gateway_node_num)
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
            # Grouped by the state as well as the port, because a
            # portnum of 0 is four different things and this chart used
            # to draw all of them as UNKNOWN_APP (#157).
            select(Packet.portnum, Packet.payload_state, func.count().label("total"))
            .where(Packet.from_node_num == node_num, Packet.first_seen_at >= since)
            .group_by(Packet.portnum, Packet.payload_state)
            .order_by(func.count().desc())
        )
    ).all()
    return {
        "packet_count": sum(row.total for row in rows),
        # One row per BAND, not per (port, state) pair.
        #
        # #198 grouped this query by `payload_state` as well as
        # `portnum`, so a label could be produced more than once: every
        # port except 0 maps to the same band whatever its state, and a
        # node with both readable and unrecorded traffic on one port
        # therefore appeared twice. Live example, before this: sixteen
        # rows for nine bands, with TEXT_MESSAGE_APP, POSITION_APP,
        # TELEMETRY_APP and four more each listed twice and their counts
        # split between the copies.
        #
        # The grouping has to stay -- it is what tells a PKI direct
        # message from a genuine UNKNOWN_APP -- so the merge happens
        # here, after the label is chosen. Summed, not overwritten: two
        # halves of one port's traffic are one number.
        "by_portnum": _bands(rows),
    }


def _bands(rows: Sequence[Any]) -> list[dict[str, object]]:
    """Collapse (portnum, payload_state) rows into one row per band.

    Order is preserved from the query, which sorts by count descending,
    so the busiest band still leads. A band that gains rows by merging
    can therefore sit slightly out of order against a band below it;
    re-sorting after the merge fixes that and costs nothing.
    """
    totals: dict[str, int] = {}
    for row in rows:
        label = traffic_label(row.portnum, row.payload_state)
        totals[label] = totals.get(label, 0) + row.total
    return [
        {"portnum": label, "count": total}
        for label, total in sorted(totals.items(), key=lambda pair: (-pair[1], pair[0]))
    ]


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

# How each sort value travels inside a list cursor (#250). JSON has no
# datetime, so the two times go as ISO text and are read back. The type
# is checked on the way in, so a hand-typed cursor cannot put a string
# where the query compares a number.
_TIME_SORTS = frozenset({"last_heard", "first_seen"})
_NUMBER_SORTS = frozenset({"node_id", "position"})


def _node_cursor(sort: str, order: str, value: object, node_num: int) -> str:
    """Return the `cursor` that continues the node list after one row (#250).

    Opaque to the page. It names the last row served by its sort value
    and its `node_num`, which is the list's whole order and unique. It
    also carries the sort and order it was made under, so that
    `_read_node_cursor` can refuse it under any other.
    """
    if isinstance(value, datetime):
        value = value.isoformat()
    payload = [sort, order, value, node_num]
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")


def _read_node_cursor(raw: str, sort: str, order: str) -> tuple[Any, int]:
    """Decode a node list `cursor`, or answer 422.

    A cursor from another sort or order is refused, not applied. Its
    value means nothing in this order, so it would skip or repeat rows
    with no error at all.
    """
    try:
        padded = raw + "=" * (-len(raw) % 4)
        made_sort, made_order, value, node_num = json.loads(base64.urlsafe_b64decode(padded))
        if value is not None:
            if made_sort in _TIME_SORTS:
                value = datetime.fromisoformat(value)
            elif made_sort in _NUMBER_SORTS:
                if isinstance(value, bool) or not isinstance(value, int):
                    raise TypeError("a number sort needs a whole number")
            elif not isinstance(value, str):
                raise TypeError("a text sort needs text")
        if isinstance(node_num, bool) or not isinstance(node_num, int):
            raise TypeError("node_num must be a whole number")
    except (ValueError, TypeError, binascii.Error) as exc:
        raise HTTPException(status_code=422, detail="invalid cursor") from exc
    if (made_sort, made_order) != (sort, order):
        raise HTTPException(
            status_code=422,
            detail=f"the cursor was made for sort={made_sort}&order={made_order}",
        )
    return value, node_num


def _after_node(column: Any, order: str, cursor: tuple[Any, int]) -> ColumnElement[bool]:
    """Return the nodes that come after the cursor in the list's order.

    The order is `column` in the chosen direction with NULLs last, then
    `node_num` ascending in both directions. So a row is later when its
    value is further along, or equal with a larger `node_num`, and every
    NULL comes after every value.
    """
    value, node_num = cursor
    tail = Node.node_num > node_num
    if value is None:
        return and_(column.is_(None), tail)
    further = column > literal(value) if order == "asc" else column < literal(value)
    return or_(further, and_(column == literal(value), tail), column.is_(None))


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
    quiet_hours: int | None = None,
    preset: str | None = None,
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
    if preset is not None:
        # The preset of the node's newest tagged packet, which stays put
        # when its last packet was on a topic channel (#313).
        statement = statement.where(preset_filter(Node.last_preset, Node.last_channel, preset))
    if position:
        statement = statement.where(_position_filter(position))
    if licensed is not None:
        statement = statement.where(Node.is_licensed == licensed)
    if first_seen_hours is not None:
        statement = statement.where(
            Node.first_seen >= datetime.now(UTC) - timedelta(hours=first_seen_hours)
        )
    if quiet_hours is not None:
        # The other side of `active_hours`: nodes NOT heard for that long.
        #
        # "Which routers have gone quiet" is the question this list gets
        # asked most, and until now the only way to ask it was to widen
        # the window to "any time" and sort ascending -- which answers a
        # different question and puts the answer at the top by luck.
        #
        # `before` could express it, and the caller would have to name
        # the moment: a browser with a wrong clock would then silently
        # filter on the wrong hour. `active_hours` already sets the
        # precedent that the server names "now", and the two have to
        # agree or a band built from both ("heard this week but not
        # today") is measured against two different clocks.
        #
        # A node with no `last_heard` at all is left out rather than
        # counted as quiet forever, which is what SQL does with NULL here
        # anyway: it has never been heard, so "how long since" has no
        # answer. `active_hours` treats it the same way.
        statement = statement.where(
            Node.last_heard < datetime.now(UTC) - timedelta(hours=quiet_hours)
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
    preset: str | None = None,
    position: str | None = Query(default=None, pattern="^(exact|coarse|none)$"),
    licensed: bool | None = None,
    first_seen_hours: int | None = Query(default=None, ge=1, le=8760),
    quiet_hours: int | None = Query(default=None, ge=1, le=8760),
    gaps: str | None = Query(default=None, pattern="^(bad|ok|unknown)$"),
    gaps_preset: str | None = None,
    sort: str = Query(default="last_heard"),
    order: str = Query(default="desc", pattern="^(asc|desc)$"),
    offset: int = Query(default=0, ge=0, le=100_000),
    cursor: str | None = Query(default=None, max_length=1024),
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

    **Paging is by cursor (#250).** Each non-empty answer carries
    `X-Next-Cursor`, and passing it back as `cursor` returns the rows
    after the last one served, in the same order. `offset` still works.
    It is not what the page uses: `last_heard` changes all the time, and
    a node that moves forward past an offset boundary between two pages
    is never served at all. Nothing in the browser can detect that. A
    cursor names the last row itself, so a row that moves cannot shift
    the next page. The cursor carries its sort and order and is refused
    under any other, as for the packet timeline (#259).
    """
    if sort not in SORTS:
        raise HTTPException(
            status_code=422,
            detail=f"sort must be one of: {', '.join(sorted(SORTS))}",
        )
    after = None if cursor is None else _read_node_cursor(cursor, sort, order)
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
    menu_preset = require_preset(preset)
    # The sort value is selected beside the row, so the cursor can name it
    # exactly as the database compares it. `name` is an expression, not a
    # column the row carries.
    statement = _apply_node_filters(
        select(Node, column.label("sort_value")),
        *filters,
        first_seen_hours,
        quiet_hours,
        preset=menu_preset,
    )
    counted = _apply_node_filters(
        select(func.count()).select_from(Node),
        *filters,
        first_seen_hours,
        quiet_hours,
        preset=menu_preset,
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

    if after is not None:
        statement = statement.where(_after_node(column, order, after))
    served = (
        await session.execute(statement.order_by(*ordering).offset(offset).limit(limit))
    ).all()
    if served:
        last, last_value = served[-1]
        response.headers["X-Next-Cursor"] = _node_cursor(sort, order, last_value, last.node_num)
    return [_summary(node) for node, _value in served]


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
    preset: str | None = None,
    position: str | None = Query(default=None, pattern="^(exact|coarse|none)$"),
    licensed: bool | None = None,
    first_seen_hours: int | None = Query(default=None, ge=1, le=8760),
    quiet_hours: int | None = Query(default=None, ge=1, le=8760),
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

    `preset` is the menu's modem preset. It is never lifted: it says
    which mesh is being counted, not one more filter to compare.
    """
    menu_preset = require_preset(preset)

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
            None if lifted == "quiet_hours" else quiet_hours,
            preset=menu_preset,
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
        quiet_hours,
        preset=menu_preset,
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
                    quiet_hours,
                    preset=menu_preset,
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


# The columns the packet timeline may be ordered by (#54). A whitelist,
# as `SORTS` is for the node list: nothing a caller sends reaches the
# query.
PACKET_SORTS = ("time", "type", "to", "channel", "size", "hops", "gateways", "snr", "rssi")

# The sorts that read the observations rather than the packet row. Each
# one has to summarise every observation in the window before it can
# order anything, so it needs a window, and a bounded one.
SEEN_SORTS = frozenset({"hops", "gateways", "snr", "rssi"})
SEEN_SORT_MAX_HOURS = 168

# The window a `heard` listing reads when none is given, and the most it
# may read. It walks one gateway's uploads, which run to tens of
# thousands a day on a busy gateway.
HEARD_DEFAULT_HOURS = 24
HEARD_MAX_HOURS = 168


def _parse_packet_type(value: str) -> int:
    """Return the port number a type filter names: a number or a protobuf name."""
    if value.isdecimal():
        return int(value)
    try:
        return portnums_pb2.PortNum.Value(value)  # type: ignore[attr-defined]
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="invalid portnum") from exc


def _packet_cursor(sort: str, order: str, value: object, row: Packet) -> str:
    """Return the `before` cursor that continues a listing after `row` (#259).

    Opaque to the page, and carrying the sort it was made under, so a
    second page cannot silently come back in a different order from the
    first: `_read_packet_cursor` refuses a cursor from another sort.

    The row is named by its sort value and then (`first_seen_at`,
    `from_node_num`, `packet_id`), which is the listing's whole order and
    unique: (`from_node_num`, `packet_id`) is the packet's identity
    (AGENTS.md 9.1).
    """
    if isinstance(value, datetime):
        value = value.isoformat()
    payload = [sort, order, value, row.first_seen_at.isoformat(), row.from_node_num, row.packet_id]
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")


def _read_packet_cursor(raw: str, sort: str, order: str) -> tuple[Any, datetime, int, int]:
    """Decode a `before` cursor, or answer 422.

    A cursor made under another sort or order is refused rather than
    applied. Its sort value means nothing in this order, so applying it
    would skip or repeat rows with no error at all.
    """
    try:
        padded = raw + "=" * (-len(raw) % 4)
        made_sort, made_order, value, moment, sender, packet_id = json.loads(
            base64.urlsafe_b64decode(padded.encode())
        )
        when = datetime.fromisoformat(moment)
        if sort == "time" and value is not None:
            value = datetime.fromisoformat(value)
        sender, packet_id = int(sender), int(packet_id)
    except (ValueError, TypeError, binascii.Error) as exc:
        raise HTTPException(status_code=422, detail="invalid before cursor") from exc
    if (made_sort, made_order) != (sort, order):
        raise HTTPException(
            status_code=422,
            detail=f"the before cursor was made for sort={made_sort}&order={made_order}",
        )
    return value, when, sender, packet_id


def _after_cursor(
    column: Any, order: str, cursor: tuple[Any, datetime, int, int]
) -> ColumnElement[bool]:
    """Return the rows that come after the cursor in the listing's order.

    The order is `column` (nulls last), then `first_seen_at`,
    `from_node_num` and `packet_id`, all descending. So a row is later
    when its value is further along, or equal with a later tiebreak --
    and every NULL comes after every value, because NULLs sort last.
    """
    value, when, sender, packet_id = cursor
    # `literal`, not the bare values: `tuple_` would bind them anyway, but
    # only its column-typed signature is visible to mypy, which the CI
    # typecheck job enforces.
    tail = tuple_(Packet.first_seen_at, Packet.from_node_num, Packet.packet_id) < tuple_(
        literal(when), literal(sender), literal(packet_id)
    )
    if value is None:
        return and_(column.is_(None), tail)
    further = column > value if order == "asc" else column < value
    return or_(further, and_(column == value, tail), column.is_(None))


def _observations(keys: Any) -> Any:
    """Return the observation summary of the packets `keys` selects.

    `keys` is a select of (`from_node_num`, `packet_id`) pairs. The
    summary counts gateways that are not the sender (AGENTS.md 9.5.1)
    and takes a signal reading only where no hop was used (9.5).
    """
    uploaded_by_other = PacketSeen.gateway_node_num != PacketSeen.from_node_num
    direct = and_(Packet.hop_start == PacketSeen.hop_limit, uploaded_by_other)
    wanted = keys.subquery()
    return (
        select(
            PacketSeen.from_node_num,
            PacketSeen.packet_id,
            func.count(func.distinct(PacketSeen.gateway_node_num))
            .filter(uploaded_by_other)
            .label("gateways"),
            func.min(Packet.hop_start - PacketSeen.hop_limit)
            .filter(uploaded_by_other)
            .label("fewest_hops"),
            func.max(PacketSeen.rx_snr).filter(direct).label("direct_snr"),
            func.max(PacketSeen.rx_rssi).filter(direct).label("direct_rssi"),
        )
        .select_from(PacketSeen)
        .join(
            wanted,
            and_(
                wanted.c.from_node_num == PacketSeen.from_node_num,
                wanted.c.packet_id == PacketSeen.packet_id,
            ),
        )
        .join(
            Packet,
            and_(
                Packet.from_node_num == PacketSeen.from_node_num,
                Packet.packet_id == PacketSeen.packet_id,
            ),
        )
        .group_by(PacketSeen.from_node_num, PacketSeen.packet_id)
        .subquery()
    )


@router.get("/{node_id}/packets")
async def node_packets(
    node_id: str,
    response: Response,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0, le=100_000),
    before: str | None = Query(default=None, max_length=1024),
    hours: int | None = Query(default=None, ge=1, le=720),
    portnum: str | None = None,
    channel: str | None = None,
    direction: str = Query(default="sent", pattern="^(sent|heard)$"),
    sort: str = Query(default="time"),
    order: str = Query(default="desc", pattern="^(asc|desc)$"),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, object]]:
    """Return the packets of one node, sorted and filtered (#54).

    `direction=sent` lists what the node sent. `direction=heard` lists
    what it uploaded as an MQTT gateway on behalf of other nodes: the
    packets it heard. A `heard` listing reads at most
    `HEARD_MAX_HOURS`, and `HEARD_DEFAULT_HOURS` when no window is
    given.

    The body stays a bare array, as it was, and the count of everything
    that matches travels in `X-Total-Count`, as it does for the node
    list. A page that counted the rows it received would report the cap
    as the whole history.

    Each row carries a summary of its observations:

    - `gateways`: distinct gateways that uploaded it, never the sender
      uploading its own packet (AGENTS.md 9.5.1).
    - `fewest_hops`: the fewest relays any such gateway saw it use.
    - `direct_snr` and `direct_rssi`: the best reading at a gateway that
      heard it with no hop used. A relayed reading belongs to the last
      hop, not to the sender (AGENTS.md 9.5).
    - `size_bytes`: the stored protobuf.

    **The summary is worked out for the rows returned, and no more.** A
    sort by one of those columns has to summarise the whole window
    first, so it needs `hours` of `SEEN_SORT_MAX_HOURS` or less. That
    keeps a 30 day sort off a shared database.

    **Paging is by cursor (#259).** Each answer carries `X-Next-Before`,
    and passing it back as `before` returns the rows after the last one
    served, in the same order. `offset` still works and is not what the
    page uses: packets arrive all the time, and a new one landing
    between two offset pages pushes a row from the first page onto the
    second (a repeat) -- or, in an ascending sort, past the reader
    entirely (a gap, which nothing can detect). A cursor names the last
    row itself, so what arrived since cannot move it. The cursor carries
    its sort and order and is refused under any other, so the sort
    travels to the server with every page.
    """
    if sort not in PACKET_SORTS:
        raise HTTPException(
            status_code=422, detail=f"sort must be one of: {', '.join(PACKET_SORTS)}"
        )
    if sort in SEEN_SORTS and (hours is None or hours > SEEN_SORT_MAX_HOURS):
        raise HTTPException(
            status_code=422,
            detail=f"sorting by {sort} needs hours of {SEEN_SORT_MAX_HOURS} or less",
        )
    cursor = None if before is None else _read_packet_cursor(before, sort, order)
    if direction == "heard":
        hours = min(hours or HEARD_DEFAULT_HOURS, HEARD_MAX_HOURS)
    node_num = require_node_num(node_id)
    since = None if hours is None else datetime.now(UTC) - timedelta(hours=hours)

    filters: list[ColumnElement[bool]] = []
    if direction == "sent":
        filters.append(Packet.from_node_num == node_num)
        if since is not None:
            filters.append(Packet.first_seen_at >= since)
    else:
        # The packets this gateway uploaded for other senders. Its own
        # packets are on the `sent` listing.
        uploads = (
            select(PacketSeen.from_node_num, PacketSeen.packet_id)
            .where(
                PacketSeen.gateway_node_num == node_num,
                PacketSeen.from_node_num != node_num,
                PacketSeen.seen_at >= since,
            )
            .distinct()
            .subquery()
        )
        filters.append(
            tuple_(Packet.from_node_num, Packet.packet_id).in_(
                select(uploads.c.from_node_num, uploads.c.packet_id)
            )
        )
        # No lower bound on the packet's own date here, deliberately.
        #
        # There used to be one, `since - 1 hour`, to keep the scan to
        # the chunks that could hold the row. The assumption behind it
        # -- that a gateway uploads within an hour of the packet first
        # being seen -- does not hold: measured over 24 h, 4,764 of
        # 258,487 observations lagged by more than an hour and the
        # worst by 19.5 days. Every one of those was dropped from the
        # listing AND from X-Total-Count, so the total agreed with the
        # rows and both were wrong.
        #
        # The `uploads` subquery is already bounded by `seen_at`, which
        # is the column this listing is actually about. 9.19: a bound
        # for the planner's benefit must not decide what exists.
    if portnum is not None:
        filters.append(Packet.portnum == _parse_packet_type(portnum))
    if channel:
        filters.append(Packet.channel == channel)

    total = await session.scalar(select(func.count()).select_from(Packet).where(*filters))
    response.headers["X-Total-Count"] = str(total or 0)

    packet_columns = {
        "time": Packet.first_seen_at,
        "type": Packet.portnum,
        "to": Packet.to_node_num,
        "channel": Packet.channel,
        "size": func.octet_length(Packet.raw_bytes),
    }
    if sort in SEEN_SORTS:
        # Summarise the whole window, then order by the summary.
        seen = _observations(select(Packet.from_node_num, Packet.packet_id).where(*filters))
        column = {
            "hops": seen.c.fewest_hops,
            "gateways": seen.c.gateways,
            "snr": seen.c.direct_snr,
            "rssi": seen.c.direct_rssi,
        }[sort]
        statement = (
            select(Packet, column)
            .outerjoin(
                seen,
                and_(
                    seen.c.from_node_num == Packet.from_node_num,
                    seen.c.packet_id == Packet.packet_id,
                ),
            )
            .where(*filters)
        )
    else:
        column = packet_columns[sort]
        statement = select(Packet, column).where(*filters)
    if cursor is not None:
        statement = statement.where(_after_cursor(column, order, cursor))

    ordered = column.asc() if order == "asc" else column.desc()
    # Nulls last and a total order, so a row never lands on two pages or
    # on none. The tiebreak is the packet's identity rather than the
    # surrogate `id` it used to be, because a cursor has to be able to
    # name it and the API never shows `id` (AGENTS.md 9.1).
    served = (
        await session.execute(
            statement.order_by(
                ordered.nullslast(),
                Packet.first_seen_at.desc(),
                Packet.from_node_num.desc(),
                Packet.packet_id.desc(),
            )
            .offset(offset)
            .limit(limit)
        )
    ).all()
    if not served:
        return []
    page = [item for item, _value in served]
    last, last_value = served[-1]
    response.headers["X-Next-Before"] = _packet_cursor(sort, order, last_value, last)

    keys = [(item.from_node_num, item.packet_id) for item in page]
    summary = _observations(
        select(Packet.from_node_num, Packet.packet_id).where(
            tuple_(Packet.from_node_num, Packet.packet_id).in_(keys)
        )
    )
    observed = {
        (row.from_node_num, row.packet_id): row
        for row in (await session.execute(select(summary))).all()
    }
    names = await resolve_names(
        session, {end for item in page for end in (item.from_node_num, item.to_node_num)}
    )
    rows: list[dict[str, object]] = []
    for item in page:
        facts = observed.get((item.from_node_num, item.packet_id))
        rows.append(
            {
                "packet_id": item.packet_id,
                # `select(Packet)` above, so the state is on the row.
                "portnum": traffic_label(item.portnum, item.payload_state),
                "channel": item.channel,
                "seen_at": item.first_seen_at,
                "from_node": format_node_id(item.from_node_num),
                "from_name": name_of(names, item.from_node_num),
                "to_node": format_node_id(item.to_node_num),
                "to_name": name_of(names, item.to_node_num),
                "hop_start": item.hop_start,
                "hop_limit": item.hop_limit,
                "gateways": facts.gateways if facts else 0,
                "fewest_hops": facts.fewest_hops if facts else None,
                "direct_snr": facts.direct_snr if facts else None,
                "direct_rssi": facts.direct_rssi if facts else None,
                "size_bytes": None if item.raw_bytes is None else len(item.raw_bytes),
            }
        )
    return rows


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
