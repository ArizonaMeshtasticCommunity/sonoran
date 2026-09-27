"""Read-only dashboard statistic endpoints."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TypedDict

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from sonoran.api.cache import KeyedCache, TimedCache
from sonoran.api.dependencies import get_session, require_node_num
from sonoran.api.names import format_node_id, name_of, resolve_names
from sonoran.config import Settings
from sonoran.db.models import DailySnapshot, DeviceMetrics, Node, Packet, PacketSeen
from sonoran.decode.portnums import traffic_label
from sonoran.meshtastic import portnums_pb2

router = APIRouter(prefix="/api/stats", tags=["stats"])

# How often the firmware sends each broadcast by default, in seconds.
#
# These are the shipped settings, not rules. A node may send faster on
# purpose. They are here because a node often sends faster by accident,
# and on a shared band that costs everybody airtime.
#
# Read the result as "worth asking about", never as "misconfigured".
# The count includes every packet of the family, and only some of them
# come from the broadcast timer:
#
# - A node sends its node info when it boots. A node with a bad power
#   supply that reboots all day looks extremely chatty.
# - A node sends its node info and its position when another node asks
#   for them. That is the asking node's doing, not this one's.
# - Smart position sends when the node moves, so a node in a vehicle
#   reports far more often than its interval implies.
#
# For those reasons this module does not claim a node is below the
# firmware's own minimum, even where one exists. It reports the rate it
# measured and leaves the conclusion to somebody who can ask the owner.
BROADCAST_INTERVALS: dict[str, int] = {
    # position_broadcast_secs
    "POSITION_APP": 900,
    # node_info_broadcast_secs
    "NODEINFO_APP": 10800,
    # device_update_interval and environment_update_interval
    "TELEMETRY_APP": 1800,
    # neighbor info update_interval
    "NEIGHBORINFO_APP": 21600,
}

# How many times faster than the default a node must be before it is
# worth asking about. Two is inside the noise of reboots and requests.
NOTABLE_RATIO = 3.0

# The battery band where a node is most likely stuck in a restart loop.
#
# Between these two figures a node has enough charge to boot and start
# transmitting, but not enough to hold the current a transmission draws.
# It browns out, restarts, announces itself again, and repeats. That is
# why a node with a low battery can be one of the noisiest on the mesh.
#
# Below the lower figure the node is usually just flat and silent, which
# is a different problem and not a loop.
BROWNOUT_LOW = 5.0
BROWNOUT_HIGH = 35.0

# Above 100 percent means the node is on mains. That is how the firmware
# reports a powered device, not a battery charged past full.
ON_MAINS_ABOVE = 100.0


# The three whole-table answers on this router, each held for a while.
#
# These are the only endpoints in the API that read a hypertable with
# no time window at all: `COUNT(*)` over `packet` and `packet_seen`,
# and two ungrouped scans over every row of `packet` and `node`. The
# work is proportional to everything ever kept, so it grows with
# retention and never with what the reader asked for.
#
# The dashboard calls all three on every load, on a three-core box that
# also runs the ingest and the coverage engine. One reader refreshing a
# page was enough to put three full scans on the queue.
#
# An approximate count was the other option and was measured and
# rejected: see `docs/API.md`. `pg_class.reltuples` on a hypertable
# parent is 0, because the rows live in the chunks, so an approximation
# means summing every chunk's estimate — more query, not less, and an
# answer that is wrong by an unknown amount on a page whose whole
# purpose is to report counts.
#
# So the figures stay exact and the reader shares them. The lock in
# `TimedCache` is the part that matters under load: without it, every
# request that arrives in the instant the hold expires runs its own
# scan.
_summary_cache: TimedCache[dict[str, int]] = TimedCache()
_hardware_cache: TimedCache[list[dict[str, object]]] = TimedCache()
#: Keyed, because `/portnums` now takes a window and a channel.
#:
#: A `TimedCache` holds ONE value, so the moment the endpoint gained
#: parameters it would have answered every caller with the first caller's
#: window -- the dashboard asking for 24 hours on MediumFast and the
#: firehose's suggestion list asking for everything would have taken
#: whichever arrived first. `KeyedCache` also caps how many keys it keeps,
#: so a caller varying `hours` cannot grow it without limit.
_portnums_cache: KeyedCache[list[dict[str, object]]] = KeyedCache(capacity=32)


#: The windowed answers, one for each window asked for. Capped, so a
#: caller that varies `hours` cannot grow it without limit.
_window_cache: KeyedCache[dict[str, object]] = KeyedCache(capacity=16)


@router.get("")
async def stats(
    request: Request,
    hours: int | None = Query(default=None, ge=1, le=720),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    """Return current dashboard summary counts.

    Held for `STATS_CACHE_SECONDS`. A mesh does not change its totals
    in a way anybody reads at second resolution, and these are the four
    unbounded counts in the API.

    With `hours`, packets and uploads are counted over the last `hours`
    of receive time instead, and `previous` holds the same two counts
    for the window before. Nodes and gateways stay totals of every node
    ever seen (Will, #292). Without `hours` the answer is unchanged.
    """
    settings: Settings = request.app.state.settings
    if hours is None:
        return dict(
            await _summary_cache.get(settings.stats_cache_seconds, lambda: _read_summary(session))
        )
    return await _window_cache.get(
        str(hours),
        settings.stats_cache_seconds,
        lambda: _read_window_summary(session, settings, hours),
    )


async def _read_window_summary(
    session: AsyncSession, settings: Settings, hours: int
) -> dict[str, object]:
    """Count packets and uploads in the window, and nodes over all time.

    The window is receive time, bounded at both ends, so a row dated in
    the future by a gateway clock written before the 9.4 fix does not
    count. See AGENTS.md 9.4.

    `previous` is None when the window before starts earlier than the
    packet retention. Those rows are gone, so a comparison with them
    would show a rise that did not happen.
    """
    now = datetime.now(UTC)
    span = timedelta(hours=hours)
    start = now - span
    earlier = start - span
    retained_from = now - timedelta(days=settings.retention_days_packet)
    lifetime = await _lifetime_nodes(session)
    return {
        "window_hours": hours,
        "node_count": lifetime["node_count"],
        "gateway_count": lifetime["gateway_count"],
        **await _window_counts(session, start, now),
        "previous": (
            None if earlier < retained_from else await _window_counts(session, earlier, start)
        ),
    }


async def _lifetime_nodes(session: AsyncSession) -> dict[str, int]:
    """Count every node ever seen, and every node ever flagged a gateway."""
    return {
        "node_count": (await session.scalar(select(func.count()).select_from(Node))) or 0,
        "gateway_count": (
            await session.scalar(select(func.count()).select_from(Node).where(Node.is_mqtt_gateway))
        )
        or 0,
    }


async def _window_counts(session: AsyncSession, start: datetime, end: datetime) -> dict[str, int]:
    """Count the packets first seen, and the uploads, in `[start, end)`."""
    packets = await session.scalar(
        select(func.count())
        .select_from(Packet)
        .where(Packet.first_seen_at >= start, Packet.first_seen_at < end)
    )
    uploads = await session.scalar(
        select(func.count())
        .select_from(PacketSeen)
        .where(PacketSeen.seen_at >= start, PacketSeen.seen_at < end)
    )
    return {"packet_count": packets or 0, "observation_count": uploads or 0}


async def _read_summary(session: AsyncSession) -> dict[str, int]:
    """Count the nodes, the packets, the observations, and the gateways."""
    lifetime = await _lifetime_nodes(session)
    return {
        "node_count": lifetime["node_count"],
        "packet_count": (await session.scalar(select(func.count()).select_from(Packet))) or 0,
        "observation_count": (await session.scalar(select(func.count()).select_from(PacketSeen)))
        or 0,
        "gateway_count": lifetime["gateway_count"],
    }


@router.get("/hardware")
async def hardware(
    request: Request, session: AsyncSession = Depends(get_session)
) -> list[dict[str, object]]:
    """Return node counts grouped by hardware model."""
    settings: Settings = request.app.state.settings
    return await _hardware_cache.get(settings.stats_cache_seconds, lambda: _read_hardware(session))


async def _read_hardware(session: AsyncSession) -> list[dict[str, object]]:
    """Group every node by the hardware it reported."""
    statement = (
        select(Node.hw_model, func.count().label("count"))
        .group_by(Node.hw_model)
        .order_by(func.count().desc())
    )
    return [
        {"hw_model": model, "count": count}
        for model, count in (await session.execute(statement)).all()
    ]


@router.get("/portnums")
async def portnums(
    request: Request,
    hours: int | None = Query(default=None, ge=1, le=8760),
    channel: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, object]]:
    """Return packet counts grouped by port number, with readable names.

    Both filters are optional and both default to off, which is every
    packet the database holds on every channel -- what this endpoint has
    always answered, and what the firehose's suggestion list wants.

    The dashboard passes both, because its chart is now a link into the
    firehose (plan §7.1) and a link is only honest if the two pages count
    the same packets. Its panel says "Packet types (24 h)" and the figures
    under that heading were all-time on every preset, so the chart named
    a window it was not holding.
    """
    settings: Settings = request.app.state.settings
    key = f"{hours or 0}:{channel or ''}"
    return await _portnums_cache.get(
        key, settings.stats_cache_seconds, lambda: _read_portnums(session, hours, channel)
    )


async def _read_portnums(
    session: AsyncSession, hours: int | None, channel: str | None
) -> list[dict[str, object]]:
    """Group packets by port number, optionally by window and channel."""
    statement = select(
        # By state as well as port: a portnum of 0 is four different
        # things and this listing called all of them UNKNOWN_APP (#157).
        Packet.portnum,
        Packet.payload_state,
        func.count().label("total"),
    ).group_by(Packet.portnum, Packet.payload_state)
    if hours is not None:
        statement = statement.where(
            Packet.first_seen_at >= datetime.now(UTC) - timedelta(hours=hours)
        )
    if channel:
        statement = statement.where(Packet.channel == channel)
    rows = await session.execute(statement)
    return [
        {
            "portnum": portnum,
            "name": traffic_label(portnum, payload_state),
            "count": total,
        }
        for portnum, payload_state, total in rows.all()
    ]


@router.get("/snapshots/daily")
async def daily_snapshots(
    days: int = Query(default=30, ge=1, le=365),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, object]]:
    """Return daily snapshots newest first."""
    rows = await session.scalars(
        select(DailySnapshot).order_by(DailySnapshot.day.desc()).limit(days)
    )
    return [
        {
            "day": item.day,
            "node_count": item.node_count,
            "packet_count": item.packet_count,
            "observation_count": item.observation_count,
            "gateway_count": item.gateway_count,
            "text_count": item.text_count,
        }
        for item in rows.all()
    ]


@router.get("/top")
async def top_talkers(
    hours: int = Query(default=24, ge=1, le=720),
    limit: int = Query(default=20, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, object]]:
    """Return top packet senders in the selected time window.

    Each row also carries `air_util_tx`: the node's own average share of
    air time spent sending, from its device telemetry. On a shared
    channel a busy sender is a cost to everybody else, and the page says
    so beside the count (#60). None when the node reports no telemetry.
    """
    now = datetime.now(UTC)
    start = now - timedelta(hours=hours)
    rows = (
        await session.execute(
            select(Packet.from_node_num, func.count().label("total"))
            .where(Packet.first_seen_at >= start)
            .group_by(Packet.from_node_num)
            .order_by(func.count().desc())
            .limit(limit)
        )
    ).all()
    senders = [row.from_node_num for row in rows]
    air: dict[int, float | None] = {
        node: value
        for node, value in (
            await session.execute(
                # Bounded at BOTH ends.
                #
                # `DeviceMetrics.time` is the node's own clock, and
                # this had a lower bound only. A node running ahead had
                # every future-dated reading it has ever sent averaged
                # into the answer for "the last hour": measured on
                # production, one node's one-hour figure came from five
                # rows of which four were dated in the future, so its
                # number was effectively a lifetime average at any
                # window size. 79 rows across 13 nodes are ahead of now
                # today, the furthest by nearly ten years.
                #
                # AGENTS.md 9.4. The upper bound does not repair a bad
                # clock, but it stops one node's clock from deciding
                # what a window means.
                select(DeviceMetrics.node_num, func.avg(DeviceMetrics.air_util_tx))
                .where(
                    DeviceMetrics.node_num.in_(senders),
                    DeviceMetrics.time >= start,
                    DeviceMetrics.time <= now,
                    DeviceMetrics.air_util_tx.is_not(None),
                )
                .group_by(DeviceMetrics.node_num)
            )
        ).all()
    }
    names = await resolve_names(session, senders)
    return [
        {
            "node_id": format_node_id(row.from_node_num),
            "display_name": name_of(names, row.from_node_num),
            "packet_count": row.total,
            "air_util_tx": _rounded_or_none(air.get(row.from_node_num)),
        }
        for row in rows
    ]


def _rounded_or_none(value: float | None) -> float | None:
    return None if value is None else round(float(value), 2)


@router.get("/reliability/{node_id}")
async def reliability(
    node_id: str, session: AsyncSession = Depends(get_session)
) -> dict[str, object]:
    """Return packet and gateway counts for one node."""
    node_num = require_node_num(node_id)
    packet_count = await session.scalar(
        select(func.count()).select_from(Packet).where(Packet.from_node_num == node_num)
    )
    gateways = await session.execute(
        select(PacketSeen.gateway_node_num, func.count().label("count"))
        .where(PacketSeen.from_node_num == node_num)
        .group_by(PacketSeen.gateway_node_num)
        .order_by(func.count().desc())
    )
    return {
        "node_id": f"!{node_num:08x}",
        "packet_count": packet_count or 0,
        "gateways": [
            {"node_id": f"!{gateway:08x}", "count": count} for gateway, count in gateways.all()
        ],
    }


class NodeHealth(TypedDict):
    """What the device telemetry says about one node's health."""

    battery_level: float | None
    voltage: float | None
    uptime_seconds: int | None
    on_battery: bool
    #: The battery is in the band where a restart loop is likely.
    brownout_risk: bool
    #: The node cannot have been running for the whole window, so it
    #: restarted inside it.
    restarted: bool
    #: Restarting and in the brownout band. This node probably needs
    #: power, not a change of settings.
    likely_power_loop: bool


async def _node_health(
    session: AsyncSession, node_nums: list[int], start: datetime, window_seconds: int
) -> dict[int, NodeHealth]:
    """Return the latest battery and uptime of each node.

    A node that keeps announcing itself is usually restarting, and a
    node that keeps restarting usually has a power problem. This reads
    the evidence for that.

    The longest uptime reported in the window is the useful part. A node
    that ran the whole window must report an uptime at least as long as
    the window. A shorter one restarted.

    The time on these rows comes from the node, not from this process,
    so a node with a badly wrong clock can fall outside the window. See
    AGENTS.md 9.4. That loses the node from this report; it never
    invents a fault.
    """
    if not node_nums:
        return {}

    # Bounded at both ends, and this one matters more than a window.
    #
    # `DISTINCT ON ... ORDER BY time DESC` picks the reading the node
    # says is newest, so without an upper bound a node claiming 2036
    # always wins its own "latest battery" -- and keeps winning it
    # after the radio has been off for a month. 79 rows across 13 nodes
    # are dated in the future today. See AGENTS.md 9.4.
    now = datetime.now(UTC)
    latest = (
        await session.execute(
            select(
                DeviceMetrics.node_num,
                DeviceMetrics.battery_level,
                DeviceMetrics.voltage,
                DeviceMetrics.uptime_seconds,
            )
            .where(
                DeviceMetrics.node_num.in_(node_nums),
                DeviceMetrics.time >= start,
                DeviceMetrics.time <= now,
            )
            .distinct(DeviceMetrics.node_num)
            .order_by(DeviceMetrics.node_num, DeviceMetrics.time.desc())
        )
    ).all()

    uptime_rows = (
        await session.execute(
            select(DeviceMetrics.node_num, func.max(DeviceMetrics.uptime_seconds))
            .where(
                DeviceMetrics.node_num.in_(node_nums),
                DeviceMetrics.time >= start,
                DeviceMetrics.time <= now,
            )
            .group_by(DeviceMetrics.node_num)
        )
    ).all()
    longest: dict[int, int | None] = {node: uptime for node, uptime in uptime_rows}

    health: dict[int, NodeHealth] = {}
    for node_num, battery, voltage, uptime in latest:
        on_battery = battery is not None and battery <= ON_MAINS_ABOVE
        brownout = on_battery and battery is not None and BROWNOUT_LOW <= battery <= BROWNOUT_HIGH
        best = longest.get(node_num)
        restarted = best is not None and best < window_seconds
        health[node_num] = NodeHealth(
            battery_level=battery,
            voltage=voltage,
            uptime_seconds=uptime,
            on_battery=on_battery,
            brownout_risk=brownout,
            restarted=restarted,
            likely_power_loop=restarted and brownout,
        )
    return health


@router.get("/activity")
async def activity(
    hours: int = Query(default=24, ge=1, le=720),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    """Return packet counts for each hour, split by packet family.

    This answers "what is the mesh actually doing", and how that changes
    through the day. Node info and position usually dominate.

    The time used is when this process received the packet, never a time
    the packet carries. Node clocks have been seen nearly 28 hours out.
    See AGENTS.md 9.4.
    """
    now = datetime.now(UTC)
    start = now - timedelta(hours=hours)
    bucket = func.date_trunc("hour", Packet.first_seen_at).label("hour")
    rows = (
        await session.execute(
            select(bucket, Packet.portnum, Packet.payload_state, func.count().label("total"))
            # The upper bound is not redundant. `packet.first_seen_at`
            # holds the gateway's own clock when it sent one, and those
            # clocks run wrong: rows dated more than a day ahead exist.
            # Without this the chart grows hours that have not happened.
            # See docs/ISSUES.md 1.5.
            .where(Packet.first_seen_at >= start, Packet.first_seen_at <= now)
            .group_by(bucket, Packet.portnum, Packet.payload_state)
            .order_by(bucket)
        )
    ).all()

    hours_seen: list[datetime] = []
    seen: set[datetime] = set()
    totals: dict[str, int] = {}
    series: dict[str, dict[datetime, int]] = {}
    for moment, portnum, payload_state, total in rows:
        if moment not in seen:
            seen.add(moment)
            hours_seen.append(moment)
        name = traffic_label(portnum, payload_state)
        totals[name] = totals.get(name, 0) + total
        # `+=`, not `=`. Grouping by state as well as port means one
        # band can now be reached by more than one row in the same
        # bucket -- a readable portnum 0 and a PKI one both land on
        # different names, but two states that map to the same name
        # would otherwise have the later row overwrite the earlier.
        band = series.setdefault(name, {})
        band[moment] = band.get(moment, 0) + total

    # Busiest family first, so a stacked chart reads from the bottom.
    order = sorted(totals, key=lambda name: -totals[name])
    return {
        "window_hours": hours,
        "hours": hours_seen,
        "families": [
            {
                "name": name,
                "total": totals[name],
                # One value for each hour, zero where nothing was sent.
                "counts": [series[name].get(moment, 0) for moment in hours_seen],
            }
            for name in order
        ],
    }


@dataclass
class FamilyRate:
    """How often one node sent one family of broadcast."""

    count: int
    interval_seconds: int
    default_seconds: int
    #: How many times faster than the shipped default. 3.0 means the
    #: node sent three times as often as a stock node would.
    ratio: float
    faster_than_default: bool
    notable: bool


class BroadcastReport(TypedDict):
    """One node's broadcast behaviour, before it is made public."""

    node_id: str
    display_name: str
    packet_count: int
    families: dict[str, FamilyRate]
    notable: list[str]
    faster_than_default: list[str]


def _broadcast_report(
    node_num: int, display_name: str, rates: dict[str, FamilyRate]
) -> BroadcastReport:
    """Gather one node's rates into the shape the report sorts on."""
    return BroadcastReport(
        node_id=format_node_id(node_num),
        display_name=display_name,
        packet_count=sum(rate.count for rate in rates.values()),
        families=rates,
        notable=[name for name, rate in rates.items() if rate.notable],
        faster_than_default=[name for name, rate in rates.items() if rate.faster_than_default],
    )


EMPTY_HEALTH = NodeHealth(
    battery_level=None,
    voltage=None,
    uptime_seconds=None,
    on_battery=False,
    brownout_risk=False,
    restarted=False,
    likely_power_loop=False,
)


def _node_num_of(item: BroadcastReport) -> int:
    """Return the node number a report was built from."""
    return int(item["node_id"].lstrip("!"), 16)


@router.get("/broadcast")
async def broadcast_rates(
    hours: int = Query(default=24, ge=1, le=720),
    limit: int = Query(default=40, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    """Return how often each node sends, against the firmware defaults.

    A node that sends its position every minute costs the whole mesh
    airtime. This measures the rate each node actually achieved, so an
    owner can see whether their settings are keener than they meant.

    Three limits, and they matter. See the note on `BROADCAST_INTERVALS`
    for why this names nodes worth asking about and not nodes proved
    wrong:

    1. The interval is the window divided by the count, so it is an
       average. A node that joined halfway through looks half as busy as
       it really is.
    2. The count holds every packet of the family, not only the ones the
       broadcast timer sent. Boots and replies to requests are in there.
    3. A node that sent nothing is absent, not slow.

    Only families with a known default appear. A node sending text
    quickly is having a conversation, not a misconfiguration.
    """
    now = datetime.now(UTC)
    start = now - timedelta(hours=hours)
    window_seconds = hours * 3600
    wanted = {name: portnums_pb2.PortNum.Value(name) for name in BROADCAST_INTERVALS}  # type: ignore[attr-defined]
    by_number = {number: name for name, number in wanted.items()}

    rows = (
        await session.execute(
            select(Packet.from_node_num, Packet.portnum, func.count().label("total"))
            # The upper bound keeps future-dated rows out of the count,
            # which would otherwise make a node look busier than it is.
            # See docs/ISSUES.md 1.5.
            .where(
                Packet.first_seen_at >= start,
                Packet.first_seen_at <= now,
                Packet.portnum.in_(wanted.values()),
            )
            .group_by(Packet.from_node_num, Packet.portnum)
        )
    ).all()

    families: dict[int, dict[str, FamilyRate]] = {}
    for node_num, portnum, total in rows:
        name = by_number[portnum]
        default = BROADCAST_INTERVALS[name]
        # The average gap between one packet of this family and the next.
        interval = window_seconds / total
        ratio = default / interval
        families.setdefault(node_num, {})[name] = FamilyRate(
            count=total,
            interval_seconds=round(interval),
            default_seconds=default,
            ratio=round(ratio, 1),
            faster_than_default=ratio > 1,
            notable=ratio >= NOTABLE_RATIO,
        )

    names = await resolve_names(session, families)
    health = await _node_health(session, list(families), start, window_seconds)
    report = [
        _broadcast_report(node_num, name_of(names, node_num), rates)
        for node_num, rates in families.items()
    ]

    # A node in a power loop first: that one needs a hand, not a telling
    # off. Then the ones worth asking about, then the merely keen, then
    # by how much traffic they make.
    report.sort(
        key=lambda item: (
            not health.get(_node_num_of(item), EMPTY_HEALTH)["likely_power_loop"],
            -len(item["notable"]),
            -len(item["faster_than_default"]),
            -item["packet_count"],
        )
    )
    return {
        "window_hours": hours,
        "intervals": BROADCAST_INTERVALS,
        "notable_ratio": NOTABLE_RATIO,
        "brownout_band": [BROWNOUT_LOW, BROWNOUT_HIGH],
        "node_count": len(report),
        "notable_count": sum(1 for item in report if item["notable"]),
        "power_loop_count": sum(
            1
            for item in report
            if health.get(_node_num_of(item), EMPTY_HEALTH)["likely_power_loop"]
        ),
        "nodes": [
            {
                "node_id": item["node_id"],
                "display_name": item["display_name"],
                "packet_count": item["packet_count"],
                "notable": item["notable"],
                "faster_than_default": item["faster_than_default"],
                "families": {name: vars(rate) for name, rate in item["families"].items()},
                "health": health.get(_node_num_of(item)),
            }
            for item in report[:limit]
        ],
    }
