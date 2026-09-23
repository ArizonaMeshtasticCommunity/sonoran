"""Read-only endpoints behind the richer parts of the node page.

The node page grew four parts in one batch (#52 to #56): health cards,
a "potential issues" panel, charts over time, and route widgets. Each
part reads here, apart from the packet timeline, which extends
`/api/nodes/{node_id}/packets`.

**The health cards and the potential issues panel share one source.**
Both read `/api/nodes/{node_id}/gaps`, which serves the rows the gaps
job already wrote. Nothing here computes a gap signal. If the two parts
of the page computed their own verdicts they would one day disagree,
and `gaps/signals.py` is the only module that may decide what a signal
means.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from sonoran.api.dependencies import get_session, require_node_num
from sonoran.api.names import format_node_id, name_of, resolve_names
from sonoran.api.routes.gaps import read_assessment
from sonoran.api.routes.graph import _mentions, _trace_links
from sonoran.config import Settings
from sonoran.db.models import DeviceMetrics, NeighborMetrics, Node, Packet, PacketSeen, Traceroute
from sonoran.decode.portnums import traffic_label
from sonoran.gaps import store as gaps_store
from sonoran.gaps.signals import position_confidence
from sonoran.gaps.siting import distance_km
from sonoran.positions import MIN_SITE_PRECISION_BITS

router = APIRouter(prefix="/api/nodes", tags=["nodes"])

# How many gateways the direct signal chart draws. More lines than this
# cannot be told apart on one chart.
SIGNAL_GATEWAYS = 6

# The most traceroutes the route widgets read. A row limit must never
# decide what evidence exists (AGENTS.md 9.19), so the answer says when
# it was reached rather than pretend the list was whole.
ROUTE_TRACE_LIMIT = 2000


def bucket_seconds(hours: int) -> int:
    """Return the width of one chart bucket for a window.

    A chart needs a few hundred points, not every row. A 30 day window
    on a node that reports each minute is 43,000 rows, and these are
    hypertables. The buckets keep every window to about 300 points or
    fewer.
    """
    if hours <= 6:
        return 300
    if hours <= 24:
        return 900
    if hours <= 168:
        return 3600
    return 6 * 3600


# ----------------------------------------------------------------- gaps


@router.get("/{node_id}/gaps")
async def node_gaps(node_id: str, request: Request) -> dict[str, object]:
    """Return what the gaps assessment says about one node, per preset.

    This reads the artefact the gaps job wrote and nothing else. It opens
    no database session. A node can need help on one preset and be fine
    on another, so each preset keeps its own row. See AGENTS.md 9.7.

    `available: false` is a working state: no assessment has been
    written yet. A node that is absent from an assessment is named in
    `not_listed`, because "not assessed" is a different answer from
    "assessed and fine".
    """
    wanted = format_node_id(require_node_num(node_id))
    settings: Settings = request.app.state.settings
    index = gaps_store.read_index(settings)
    listed = index.get("presets") if index else None
    presets = [
        item["preset"]
        for item in (listed if isinstance(listed, list) else [])
        if isinstance(item, dict) and isinstance(item.get("preset"), str)
    ]
    if not presets:
        return {"available": False, "reason": "no_assessment", "assessments": [], "not_listed": []}

    assessments: list[dict[str, object]] = []
    not_listed: list[str] = []
    for preset in presets:
        document = read_assessment(settings, preset)
        if document is None:
            continue
        rows = document.get("nodes")
        row = next(
            (
                item
                for item in (rows if isinstance(rows, list) else [])
                if isinstance(item, dict) and item.get("node_id") == wanted
            ),
            None,
        )
        if row is None:
            not_listed.append(preset)
            continue
        assessments.append(
            {
                "preset": preset,
                "window_hours": document.get("window_hours"),
                "generated_at": document.get("generated_at"),
                "gateways_active": document.get("gateways_active"),
                "signal_order": document.get("signal_order", []),
                "signal_labels": document.get("signal_labels", {}),
                "node": row,
            }
        )
    # The preset the node sends most on first, so the page leads with it.
    assessments.sort(key=lambda item: -_packets_of(item))
    return {
        "available": True,
        "reason": None,
        "assessments": assessments,
        "not_listed": not_listed,
    }


def _packets_of(assessment: dict[str, object]) -> int:
    node = assessment.get("node")
    packets = node.get("packets") if isinstance(node, dict) else None
    return packets if isinstance(packets, int) else 0


# -------------------------------------------------------------- history


@router.get("/{node_id}/history")
async def node_history(
    node_id: str,
    hours: int = Query(default=24, ge=1, le=720),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    """Return the series behind the node page charts (#53).

    - `device`: battery, voltage, channel use and air time, averaged in
      each bucket. Empty when the node sends no device telemetry, so the
      page can leave the chart out rather than draw an empty axis.
    - `packets`: what the node sent in each bucket, split by type. A
      quiet stretch in it is a reporting gap, which is how a solar node
      that goes dark each night shows itself.
    - `direct_signal`: SNR and RSSI at each gateway that heard the node
      directly, with no hop used and not from its own upload. Relayed
      observations carry the last hop's reading, never this node's
      (AGENTS.md 9.5 and 9.5.1).

    Every series is bounded above by now. Node clocks run wrong, and a
    row dated tomorrow would otherwise stretch the axis (AGENTS.md 9.4).
    """
    node_num = require_node_num(node_id)
    now = datetime.now(UTC)
    since = now - timedelta(hours=hours)
    width = bucket_seconds(hours)
    return {
        "window_hours": hours,
        "bucket_seconds": width,
        "device": await _device_series(session, node_num, since, now, width),
        "packets": await _packet_series(session, node_num, since, now, width),
        "direct_signal": await _direct_signal(session, node_num, since, now, width),
    }


def _bucket(column: Any, width: int, origin: datetime) -> Any:
    """Return the start of the bucket a timestamp falls in."""
    return func.date_bin(timedelta(seconds=width), column, origin)


async def _device_series(
    session: AsyncSession, node_num: int, since: datetime, now: datetime, width: int
) -> list[dict[str, object]]:
    """Battery and air time over the window, placed by OUR clock.

    `DeviceMetrics.time` is the node's own clock, and AGENTS.md 9.4
    says node clocks are wrong, sometimes badly. This used to bucket on
    that column and clamp to `[since, now]`, so a node running ahead
    had its telemetry fall outside the window and disappear -- and the
    docstring then told the page to read an empty series as "the node
    sends no device telemetry", which is a different thing entirely.

    Measured on production: 79 rows across 13 nodes are dated in the
    future, the furthest at 2036-02-07. For `!700379d3`, 31 of its 55
    rows in a 24 h window were ahead of now, and the endpoint returned
    24 points. More than half of that node's battery chart was missing.

    So the placement comes from the packet that carried the reading.
    `packet.first_seen_at` is stamped when we received it, which is the
    same clock `heard_at` uses and the one the other two series on this
    page already use.

    The join is LEFT with a fallback to the node's own time, because a
    reading we cannot tie to a packet should still be drawn rather than
    silently dropped -- that is the very failure being fixed. Measured,
    that is 1 row in 17,786.
    """
    # Our clock where we have it, the node's where we do not.
    stamped = func.coalesce(Packet.first_seen_at, DeviceMetrics.time)
    bucket = _bucket(stamped, width, since).label("bucket")
    rows = (
        await session.execute(
            select(
                bucket,
                func.avg(DeviceMetrics.battery_level),
                func.avg(DeviceMetrics.voltage),
                func.avg(DeviceMetrics.channel_utilization),
                func.avg(DeviceMetrics.air_util_tx),
            )
            .select_from(DeviceMetrics)
            .outerjoin(
                Packet,
                and_(
                    Packet.from_node_num == DeviceMetrics.node_num,
                    Packet.packet_id == DeviceMetrics.packet_id,
                ),
            )
            .where(
                DeviceMetrics.node_num == node_num,
                stamped >= since,
                stamped <= now,
            )
            .group_by(bucket)
            .order_by(bucket)
        )
    ).all()
    return [
        {
            "time": moment,
            "battery_level": _rounded(battery),
            "voltage": _rounded(voltage, 3),
            "channel_utilization": _rounded(utilisation),
            "air_util_tx": _rounded(air),
        }
        for moment, battery, voltage, utilisation, air in rows
    ]


def _rounded(value: object, places: int = 2) -> float | None:
    return None if value is None else round(float(value), places)  # type: ignore[arg-type]


async def _packet_series(
    session: AsyncSession, node_num: int, since: datetime, now: datetime, width: int
) -> dict[str, object]:
    bucket = _bucket(Packet.first_seen_at, width, since).label("bucket")
    rows = (
        await session.execute(
            # By state as well as port. This is the traffic chart #157
            # names: it drew PKI direct messages, no-key packets and
            # genuine UNKNOWN_APP as one band called UNKNOWN_APP.
            select(bucket, Packet.portnum, Packet.payload_state, func.count())
            .where(
                Packet.from_node_num == node_num,
                Packet.first_seen_at >= since,
                Packet.first_seen_at <= now,
            )
            .group_by(bucket, Packet.portnum, Packet.payload_state)
        )
    ).all()
    # Every bucket of the window, so a silent stretch reads as zero
    # rather than being skipped over by the chart.
    start = since
    buckets: list[datetime] = []
    while start <= now:
        buckets.append(start)
        start += timedelta(seconds=width)
    series: dict[str, dict[datetime, int]] = {}
    for moment, portnum, payload_state, total in rows:
        # `+=`, not `=`: grouping by state as well as port means two
        # rows in one bucket can map to the same band, and assignment
        # would silently keep only the last of them.
        band = series.setdefault(traffic_label(portnum, payload_state), {})
        band[moment] = band.get(moment, 0) + total
    totals = {name: sum(values.values()) for name, values in series.items()}
    return {
        "buckets": buckets,
        "families": [
            {
                "name": name,
                "total": totals[name],
                "counts": [series[name].get(moment, 0) for moment in buckets],
            }
            for name in sorted(totals, key=lambda name: -totals[name])
        ],
    }


def _direct() -> Any:
    """Return the rule for an observation that measured this node itself.

    No hop used, and a gateway that is not the node. See AGENTS.md 9.5
    and 9.5.1, and `_heard_by` in `routes/nodes.py`, which applies the
    same rule.
    """
    return and_(
        Packet.hop_start == PacketSeen.hop_limit,
        PacketSeen.from_node_num != PacketSeen.gateway_node_num,
    )


async def _direct_signal(
    session: AsyncSession, node_num: int, since: datetime, now: datetime, width: int
) -> list[dict[str, object]]:
    bucket = _bucket(PacketSeen.seen_at, width, since).label("bucket")
    joined = and_(
        Packet.from_node_num == PacketSeen.from_node_num,
        Packet.packet_id == PacketSeen.packet_id,
    )
    rows = (
        await session.execute(
            select(
                PacketSeen.gateway_node_num,
                bucket,
                func.avg(PacketSeen.rx_snr),
                func.avg(PacketSeen.rx_rssi),
                func.count(),
            )
            .select_from(PacketSeen)
            .join(Packet, joined)
            .where(
                PacketSeen.from_node_num == node_num,
                PacketSeen.seen_at >= since,
                PacketSeen.seen_at <= now,
                _direct(),
            )
            .group_by(PacketSeen.gateway_node_num, bucket)
            .order_by(bucket)
        )
    ).all()
    by_gateway: dict[int, list[list[object]]] = {}
    heard: dict[int, int] = {}
    for gateway, moment, snr, rssi, total in rows:
        by_gateway.setdefault(gateway, []).append([moment, _rounded(snr), _rounded(rssi, 1)])
        heard[gateway] = heard.get(gateway, 0) + total
    keep = sorted(heard, key=lambda gateway: -heard[gateway])[:SIGNAL_GATEWAYS]
    names = await resolve_names(session, keep)
    return [
        {
            "node_id": format_node_id(gateway),
            "display_name": name_of(names, gateway),
            "direct_count": heard[gateway],
            "points": by_gateway[gateway],
        }
        for gateway in keep
    ]


# --------------------------------------------------------------- routes


@router.get("/{node_id}/routes")
async def node_routes(
    node_id: str,
    hours: int = Query(default=24, ge=1, le=720),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    """Return the route and neighbour widgets of one node (#55).

    - `hears`: nodes this node heard. Its own neighbour reports, and
      traceroute hops that arrived at it.
    - `heard_by`: nodes that heard this node. Their neighbour reports
      that name it, and traceroute hops that left it. The two lists
      differ, and the difference is the useful part: a node that hears
      plenty and is heard by nobody has a transmit problem.
    - `longest_segment`: the longest single hop, by distance, of any
      traceroute this node took part in.
    - `furthest_heard_by` and `furthest_heard`: the most distant node in
      each list.
    - `hop_depth`: how many hops this node's packets took to reach the
      nearest gateway, counted once per packet.

    **A distance needs an exact position at both ends.** A coarse
    position is off by up to kilometres, and a "longest hop" computed
    from one is a guess with a number printed on it. Such pairs are left
    out of every distance here and counted in `coarse_excluded`.
    """
    node_num = require_node_num(node_id)
    now = datetime.now(UTC)
    since = now - timedelta(hours=hours)

    hears: dict[int, dict[str, Any]] = {}
    heard_by: dict[int, dict[str, Any]] = {}

    reports = (
        await session.execute(
            select(
                NeighborMetrics.node_num,
                NeighborMetrics.neighbor_node_num,
                func.count(),
                func.max(NeighborMetrics.snr),
                func.max(NeighborMetrics.time),
            )
            .where(
                NeighborMetrics.time >= since,
                (NeighborMetrics.node_num == node_num)
                | (NeighborMetrics.neighbor_node_num == node_num),
            )
            .group_by(NeighborMetrics.node_num, NeighborMetrics.neighbor_node_num)
        )
    ).all()
    for reporter, neighbour, total, snr, last in reports:
        if reporter == neighbour:
            continue
        # The reporter heard the neighbour.
        if reporter == node_num:
            _note(hears, neighbour, "neighbor", total, snr, last)
        else:
            _note(heard_by, reporter, "neighbor", total, snr, last)

    traces = (
        await session.scalars(
            select(Traceroute)
            .where(Traceroute.seen_at >= since, _mentions(node_num))
            .order_by(Traceroute.seen_at.desc())
            .limit(ROUTE_TRACE_LIMIT)
        )
    ).all()
    segments: list[tuple[int, int, float | None]] = []
    for trace in traces:
        for source, target, snr, _position, _claimed in _trace_links(trace):
            segments.append((source, target, snr))
            # `target` heard `source`.
            if target == node_num:
                _note(hears, source, "traceroute", 1, snr, trace.seen_at)
            elif source == node_num:
                _note(heard_by, target, "traceroute", 1, snr, trace.seen_at)

    involved = {node_num} | set(hears) | set(heard_by)
    involved |= {end for source, target, _ in segments for end in (source, target)}
    positions = await exact_positions(session, involved)
    names = await resolve_names(session, involved)

    coarse_excluded = 0
    longest: dict[str, object] | None = None
    seen_pairs: set[tuple[int, int]] = set()
    for source, target, snr in segments:
        pair = (min(source, target), max(source, target))
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        distance = _distance(positions, source, target)
        if distance is None:
            coarse_excluded += 1
            continue
        if longest is None or distance > longest["distance_km"]:  # type: ignore[operator]
            longest = {
                "from": _named(names, source),
                "to": _named(names, target),
                "distance_km": distance,
                "snr": snr,
            }

    def listed(found: dict[int, dict[str, Any]]) -> list[dict[str, object]]:
        rows = []
        for other, facts in found.items():
            distance = _distance(positions, node_num, other)
            rows.append(
                _named(names, other)
                | {
                    "count": facts["count"],
                    "best_snr": facts["best_snr"],
                    "kinds": sorted(facts["kinds"]),
                    "last": facts["last"],
                    "distance_km": distance,
                }
            )
        rows.sort(key=lambda row: (-int(row["count"]), str(row["node_id"])))  # type: ignore[call-overload]
        return rows

    hears_rows = listed(hears)
    heard_by_rows = listed(heard_by)
    return {
        "window_hours": hours,
        "position": positions.get(node_num) is not None,
        "hears": hears_rows,
        "heard_by": heard_by_rows,
        "longest_segment": longest,
        "furthest_heard_by": _furthest(heard_by_rows),
        "furthest_heard": _furthest(hears_rows),
        "coarse_excluded": coarse_excluded,
        "traces_read": len(traces),
        "trace_limit_reached": len(traces) >= ROUTE_TRACE_LIMIT,
        "hop_depth": await _hop_depth(session, node_num, since, now),
    }


def _note(
    found: dict[int, dict[str, Any]],
    other: int,
    kind: str,
    count: int,
    snr: float | None,
    last: datetime | None,
) -> None:
    """Count one more report of a link to another node."""
    facts = found.setdefault(other, {"count": 0, "best_snr": None, "kinds": set(), "last": None})
    facts["count"] += count
    facts["kinds"].add(kind)
    if snr is not None and (facts["best_snr"] is None or snr > facts["best_snr"]):
        facts["best_snr"] = snr
    if last is not None and (facts["last"] is None or last > facts["last"]):
        facts["last"] = last


def _named(names: dict[int, dict[str, str | None]], node_num: int) -> dict[str, object]:
    return {"node_id": format_node_id(node_num), "display_name": name_of(names, node_num)}


def _furthest(rows: list[dict[str, object]]) -> dict[str, object] | None:
    placed = [row for row in rows if row.get("distance_km") is not None]
    return max(placed, key=lambda row: row["distance_km"]) if placed else None  # type: ignore[arg-type, return-value]


async def exact_positions(
    session: AsyncSession, node_nums: set[int]
) -> dict[int, tuple[float, float]]:
    """Return the position of each node whose position is exact.

    `exact` is the word `gaps/signals.py` uses, from the same rule, so
    this page and the gaps page agree about which positions to trust.
    """
    if not node_nums:
        return {}
    rows = (
        await session.execute(
            select(
                Node.node_num, Node.last_lat, Node.last_lon, Node.last_position_precision_bits
            ).where(Node.node_num.in_(node_nums))
        )
    ).all()
    return {
        node: (lat, lon)
        for node, lat, lon, bits in rows
        if position_confidence(lat, lon, bits, MIN_SITE_PRECISION_BITS)[0] == "exact"
    }


def _distance(positions: dict[int, tuple[float, float]], first: int, second: int) -> float | None:
    one, two = positions.get(first), positions.get(second)
    if one is None or two is None:
        return None
    return round(float(distance_km(one[0], one[1], two[0], two[1])), 2)


async def _hop_depth(
    session: AsyncSession, node_num: int, since: datetime, now: datetime
) -> dict[str, object]:
    """Return how many hops this node's packets took to the nearest gateway.

    Each packet counts once, at the fewest hops any gateway saw it use.
    The node's own uploads are left out: they took no hop because they
    never crossed the air (AGENTS.md 9.5.1).
    """
    fewest = (
        select(func.min(Packet.hop_start - PacketSeen.hop_limit).label("hops"))
        .select_from(PacketSeen)
        .join(
            Packet,
            and_(
                Packet.from_node_num == PacketSeen.from_node_num,
                Packet.packet_id == PacketSeen.packet_id,
            ),
        )
        .where(
            PacketSeen.from_node_num == node_num,
            PacketSeen.gateway_node_num != node_num,
            PacketSeen.seen_at >= since,
            PacketSeen.seen_at <= now,
            Packet.hop_start.is_not(None),
            PacketSeen.hop_limit.is_not(None),
        )
        .group_by(PacketSeen.packet_id)
        .subquery()
    )
    rows = (
        await session.execute(
            select(fewest.c.hops, func.count()).group_by(fewest.c.hops).order_by(fewest.c.hops)
        )
    ).all()
    counts = {int(hops): int(total) for hops, total in rows if hops is not None and hops >= 0}
    packets = sum(counts.values())
    median: int | None = None
    if packets:
        running = 0
        for hops in sorted(counts):
            running += counts[hops]
            if running * 2 >= packets:
                median = hops
                break
    return {
        "packets": packets,
        "median": median,
        "counts": [{"hops": hops, "packets": counts[hops]} for hops in sorted(counts)],
    }
