"""Read-only dashboard statistic endpoints."""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, TypedDict, cast
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from sonoran import read_models
from sonoran.api import hourly
from sonoran.api.cache import KeyedCache, TimedCache
from sonoran.api.dependencies import get_session, require_node_num
from sonoran.api.names import format_node_id, name_of, resolve_names
from sonoran.api.preset_scope import preset_filter, require_preset
from sonoran.api.window import (
    Window,
    cache_seconds,
    optional_window,
    retained_from,
    window_query,
)
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

# A power loop is several restarts close together (#365): the node boots,
# fails, boots again, and re-sends its NodeInfo on each boot. Restarts are
# counted from `uptime_seconds` falling between a node's readings, in our
# receive order (AGENTS.md 9.4), never inferred from a battery level.
#
# There used to be a "brownout band" of 5 to 35 % battery here, and any
# node in it that restarted once in the window was "maybe power cycling":
# 24 nodes on the 30 day view, one of them up for 21 days. The band had no
# firmware, datasheet or measurement behind it (AGENTS.md §3A.2), so the
# battery is now shown as context only.
#
# The span is the issue's ("N restarts within 24 h", #365).
LOOP_SPAN = timedelta(hours=24)
# Measured on our data, 2026-10-14, 521 nodes over 30 days (docs/DECISIONS.md
# "#365"): at 4 or more restarts inside 24 h, every node (8 of 8) also sent
# NodeInfo above its default on that day; at 3, 5 of 14 did; at 2, 15 of 52.
LOOP_RESTARTS = 4

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
#: caller that varies the window cannot grow it without limit.
_window_cache: KeyedCache[dict[str, object]] = KeyedCache(capacity=16)
#: The windowed hardware mix (#294), capped the same way.
_hardware_window_cache: KeyedCache[list[dict[str, object]]] = KeyedCache(capacity=16)


@router.get("")
async def stats(
    request: Request,
    window: Window | None = Depends(optional_window),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    """Return current dashboard summary counts.

    Held for `STATS_CACHE_SECONDS`. A mesh does not change its totals
    in a way anybody reads at second resolution, and these are the four
    unbounded counts in the API.

    With a window (`hours`, or `since` and `until`), packets and uploads
    are counted over that window of receive time instead, and `previous`
    holds the same two counts for the window of the same length before
    it. Nodes and gateways stay totals of every node ever seen (Will,
    #292). Without a window the answer is unchanged.
    """
    settings: Settings = request.app.state.settings
    if window is None:
        return dict(
            await _summary_cache.get(cache_seconds(settings, None), lambda: _read_summary(session))
        )
    return await _window_cache.get(
        window.key,
        cache_seconds(settings, window),
        lambda: _read_window_summary(session, settings, window),
    )


async def _read_window_summary(
    session: AsyncSession, settings: Settings, window: Window
) -> dict[str, object]:
    """Count packets and uploads in the window, and nodes over all time.

    The window is receive time, bounded at both ends, so a row dated in
    the future by a gateway clock written before the 9.4 fix does not
    count. See AGENTS.md 9.4.

    `previous` is None when the window before starts earlier than the
    packet retention. Those rows are gone, so a comparison with them
    would show a rise that did not happen.
    """
    earlier = window.start - (window.end - window.start)
    lifetime = await _lifetime_nodes(session)
    return {
        **window.describe(settings),
        "node_count": lifetime["node_count"],
        "gateway_count": lifetime["gateway_count"],
        **await _window_counts(session, window.start, window.end),
        "previous": (
            None
            if earlier < retained_from(settings)
            else await _window_counts(session, earlier, window.start)
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
    """Count the packets first seen, and the uploads, in `[start, end)`.

    From the hourly totals, with the partial hour at each end from the
    raw rows, so the count is exact (#366). It read millions of raw
    rows, and a 30 day window took 12.7 s.
    """
    return {
        "packet_count": await hourly.count_packets(session, start, end),
        "observation_count": await hourly.count_uploads(session, start, end),
    }


async def _kept(session: AsyncSession, model: Any, time: Any, count: Any) -> int:
    """Count every row a raw table still keeps, through the hourly totals.

    From its oldest row to its newest, both included. The totals are
    kept longer than the raw rows, so the oldest raw row, not the oldest
    total, is where the count starts. The newest row may be dated in the
    future by a gateway clock from before AGENTS.md 9.4, and this count
    has always held every row, so it ends after the newest row.
    """
    oldest, newest = (
        await session.execute(select(func.min(time), func.max(time)).select_from(model))
    ).one()
    if oldest is None or newest is None:
        return 0
    return int(await count(session, oldest, newest + timedelta(microseconds=1)))


async def _read_summary(session: AsyncSession) -> dict[str, int]:
    """Count the nodes, the packets, the observations, and the gateways."""
    lifetime = await _lifetime_nodes(session)
    return {
        "node_count": lifetime["node_count"],
        "packet_count": await _kept(session, Packet, Packet.first_seen_at, hourly.count_packets),
        "observation_count": await _kept(
            session, PacketSeen, PacketSeen.seen_at, hourly.count_uploads
        ),
        "gateway_count": lifetime["gateway_count"],
    }


@router.get("/hardware")
async def hardware(
    request: Request,
    window: Window | None = Depends(optional_window),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, object]]:
    """Return node counts grouped by hardware model.

    Without a window, every node ever seen. With one, the nodes that sent
    a packet inside it (#294): "boards heard in the last 30 days". The
    packet is the evidence rather than `node.last_heard`, because
    `last_heard` holds only the latest time, and a node heard in a past
    range and again since would drop out of that range.
    """
    settings: Settings = request.app.state.settings
    if window is None:
        return await _hardware_cache.get(
            cache_seconds(settings, None), lambda: _read_hardware(session)
        )
    return await _hardware_window_cache.get(
        window.key,
        cache_seconds(settings, window),
        lambda: _read_hardware(session, window),
    )


async def _read_hardware(
    session: AsyncSession, window: Window | None = None
) -> list[dict[str, object]]:
    """Group every node, or every node heard in the window, by its hardware."""
    statement = (
        select(Node.hw_model, func.count().label("count"))
        .group_by(Node.hw_model)
        .order_by(func.count().desc())
    )
    if window is not None:
        # The senders of the window from the hourly totals (#371). It read
        # every raw packet of the window for them: 1.5 s over 30 days.
        statement = statement.where(
            Node.node_num.in_(hourly.senders_heard(window.start, window.end))
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
    preset: str | None = None,
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
    wanted = require_preset(preset)
    # The preset is part of the key. Without it the dashboard on
    # LongFast would be answered with the MediumFast counts.
    key = f"{hours or 0}:{channel or ''}:{wanted or ''}"
    return await _portnums_cache.get(
        key,
        cache_seconds(settings, hours),
        lambda: _read_portnums(session, hours, channel, wanted),
    )


async def _read_portnums(
    session: AsyncSession, hours: int | None, channel: str | None, preset: str | None = None
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
    if preset is not None:
        statement = statement.where(preset_filter(Packet.modem_preset, Packet.channel, preset))
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


#: The three windowed tables and charts on the Statistics page (#294).
#:
#: Each read aggregates the whole window of `packet`, and the page's
#: default window is 30 days, so without a hold every load of the page
#: ran three full-retention aggregates. Keyed by the window and the
#: other parameters, and capped.
_top_cache: KeyedCache[list[dict[str, object]]] = KeyedCache(capacity=16)
_activity_cache: KeyedCache[dict[str, object]] = KeyedCache(capacity=16)
_broadcast_cache: KeyedCache[dict[str, object]] = KeyedCache(capacity=16)
_daily_cache: KeyedCache[dict[str, object]] = KeyedCache(capacity=16)


@router.get("/top")
async def top_talkers(
    request: Request,
    window: Window = Depends(window_query(24)),
    limit: int = Query(default=20, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, object]]:
    """Return top packet senders in the selected time window.

    Each row also carries `air_util_tx`: the node's own average share of
    air time spent sending, from its device telemetry. On a shared
    channel a busy sender is a cost to everybody else, and the page says
    so beside the count (#60). None when the node reports no telemetry.
    """
    settings: Settings = request.app.state.settings
    return await _top_cache.get(
        f"{window.key}:{limit}",
        cache_seconds(settings, window),
        lambda: _read_top(session, window, limit),
    )


async def _read_top(session: AsyncSession, window: Window, limit: int) -> list[dict[str, object]]:
    """Count each sender's packets in the window, busiest first."""
    now = window.end
    start = window.start
    # From the hourly totals per sender (#371), with the partial hour at
    # each end from the raw rows. It counted every raw packet of the
    # window: 4.7 s over 30 days. Bounded at both ends, like `/activity`
    # and `/broadcast`: a packet row dated in the future must not count
    # in every window. See AGENTS.md 9.4.
    rows = await hourly.top_senders(session, start, now, limit)
    senders = [node for node, _ in rows]
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
            "node_id": format_node_id(node),
            "display_name": name_of(names, node),
            "packet_count": total,
            "air_util_tx": _rounded_or_none(air.get(node)),
        }
        for node, total in rows
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
    #: Restarts counted in the window: readings whose uptime fell.
    restarts: int
    #: The most restarts inside any `LOOP_SPAN` of the window.
    restarts_24h: int
    #: NodeInfo sent inside that busiest span, against its default (1.0 is
    #: the default). None unless `restarts_24h` reaches `LOOP_RESTARTS`.
    nodeinfo_ratio_24h: float | None
    #: At least one restart counted in the window.
    restarted: bool
    #: `LOOP_RESTARTS` or more restarts inside `LOOP_SPAN`, and NodeInfo
    #: sent faster than its default inside that same span.
    likely_power_loop: bool


async def _node_health(
    session: AsyncSession,
    node_nums: list[int],
    start: datetime,
    window_seconds: int,
    end: datetime | None = None,
) -> dict[int, NodeHealth]:
    """Return each node's latest battery and uptime, and its counted restarts.

    A restart is a reading whose `uptime_seconds` is lower than the node's
    reading before it (#365). The readings are put in our receive order
    -- the receive time of the packet that carried each one, AGENTS.md
    9.4 -- and only readings received inside the window count. The first
    reading of the window has nothing before it, so it is never a restart.

    A power loop is `LOOP_RESTARTS` or more restarts inside `LOOP_SPAN`
    while the node sends NodeInfo above its default **in that same span**.
    A window-long NodeInfo average hides a bad day: one node with 15
    restarts in a day averaged 0.87x over 30 days and 1.75x on the day.

    What this cannot tell: a node that restarts and is not heard between
    two boots shows one restart, not two; a node that sends no device
    telemetry shows none; and a reading that arrives late from a backlog,
    after a newer one, reads as a restart if its uptime is lower.
    """
    if not node_nums:
        return {}

    now = end or datetime.now(UTC)
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

    restarts = await _restart_times(session, node_nums, start, now)

    health: dict[int, NodeHealth] = {}
    for node_num, battery, voltage, uptime in latest:
        times = restarts.get(node_num, [])
        most, span_start = busiest_span(times, LOOP_SPAN)
        nodeinfo = None
        if most >= LOOP_RESTARTS and span_start is not None:
            nodeinfo = await _nodeinfo_ratio(session, node_num, span_start, now)
        health[node_num] = NodeHealth(
            battery_level=battery,
            voltage=voltage,
            uptime_seconds=uptime,
            on_battery=battery is not None and battery <= ON_MAINS_ABOVE,
            restarts=len(times),
            restarts_24h=most,
            nodeinfo_ratio_24h=nodeinfo,
            restarted=bool(times),
            likely_power_loop=is_power_loop(most, nodeinfo),
        )
    return health


async def _nodeinfo_ratio(
    session: AsyncSession, node_num: int, start: datetime, end: datetime
) -> float:
    """NodeInfo the node sent in its busiest span, against its default.

    The span is `LOOP_SPAN` from `start`, cut at the window's `end`: a
    loop going on now has had only part of a day, and is judged on that
    part (`nodeinfo_expected`), never on a full day it has not had yet.
    """
    stop = min(start + LOOP_SPAN, end)
    sent = await session.scalar(
        select(func.count()).where(
            Packet.from_node_num == node_num,
            Packet.portnum == portnums_pb2.PortNum.Value("NODEINFO_APP"),  # type: ignore[attr-defined]
            Packet.first_seen_at >= start,
            Packet.first_seen_at < stop,
        )
    )
    return round((sent or 0) / nodeinfo_expected(stop - start), 2)


def nodeinfo_expected(length: timedelta) -> float:
    """How many NodeInfo a node sends at its default in `length`, at least one.

    The default is `node_info_broadcast_secs`. At least one, so a span of
    a few minutes does not turn one NodeInfo into a large ratio.
    """
    return max(length.total_seconds() / BROADCAST_INTERVALS["NODEINFO_APP"], 1.0)


# How far behind the receive time a reading's own time can be, so the
# readings of a window are found by the device-time index. One upload on
# this deployment arrived 19.5 days late (`ingest/handlers/clocks.py`).
READING_LAG = timedelta(days=20)


async def _restart_times(
    session: AsyncSession, node_nums: list[int], start: datetime, end: datetime
) -> dict[int, list[datetime]]:
    """Each node's restarts in `[start, end]`, as the receive times of the readings."""
    received = Packet.first_seen_at
    before = (
        func.lag(DeviceMetrics.uptime_seconds)
        .over(partition_by=DeviceMetrics.node_num, order_by=(received, DeviceMetrics.id))
        .label("before")
    )
    readings = (
        select(
            DeviceMetrics.node_num.label("node"),
            received.label("at"),
            DeviceMetrics.uptime_seconds.label("uptime"),
            before,
        )
        # By (node, packet ID), the packet's identity (AGENTS.md 9.1).
        # Ingest never knows the row id, so `packet_pk` is empty on the
        # rows it writes: joined on it, live data found 18 of 521 nodes.
        .join(
            Packet,
            and_(
                Packet.from_node_num == DeviceMetrics.node_num,
                Packet.packet_id == DeviceMetrics.packet_id,
                received >= start,
                received <= end,
            ),
        )
        .where(
            DeviceMetrics.node_num.in_(node_nums),
            DeviceMetrics.uptime_seconds.is_not(None),
            DeviceMetrics.time >= start - READING_LAG,
            DeviceMetrics.time <= end,
        )
        .subquery()
    )
    rows = await session.execute(
        select(readings.c.node, readings.c.at)
        .where(readings.c.uptime < readings.c.before)
        .order_by(readings.c.node, readings.c.at)
    )
    found: dict[int, list[datetime]] = {}
    for node, at in rows.all():
        found.setdefault(int(node), []).append(at)
    return found


def busiest_span(times: list[datetime], span: timedelta) -> tuple[int, datetime | None]:
    """The most restarts inside any stretch of `span`, and where it starts.

    The stretch starts at its first restart. With no restarts: (0, None).
    """
    ordered = sorted(times)
    most, start, first = 0, None, 0
    for last, at in enumerate(ordered):
        while at - ordered[first] >= span:
            first += 1
        if last - first + 1 > most:
            most, start = last - first + 1, ordered[first]
    return most, start


def most_restarts_within(times: list[datetime], span: timedelta) -> int:
    """The most restarts inside any stretch of `span`."""
    return busiest_span(times, span)[0]


def is_power_loop(restarts_in_span: int, nodeinfo_ratio: float | None) -> bool:
    """`LOOP_RESTARTS` or more restarts in `LOOP_SPAN`, and NodeInfo above its default.

    A booting node sends its NodeInfo, so a node in a loop sends it more
    often than `node_info_broadcast_secs` asks. Either part alone is
    something else: restarts at the default rate are a node somebody
    reboots; a fast NodeInfo with no restarts is a setting.
    """
    return restarts_in_span >= LOOP_RESTARTS and nodeinfo_ratio is not None and nodeinfo_ratio > 1.0


def broadcast_order(
    *, loop: bool, notable: list[str], faster: list[str], packets: int, node: int
) -> tuple[bool, bool, int, int, int, int]:
    """Sort key of the broadcast table (#365).

    Counted power loops first, then the rows the table's heading names
    (`NOTABLE_RATIO` or more), then by how many families are notable and
    faster than default, then by packets. The node number breaks ties, so
    a stored ranking and a live one agree.
    """
    return (not loop, not notable, -len(notable), -len(faster), -packets, node)


#: Above this many hours the activity chart is drawn by day, not by hour.
#: A 30 day chart by hour has 720 columns, too many to read.
HOURLY_UP_TO_HOURS = 72


@router.get("/daily")
async def daily(
    request: Request,
    window: Window = Depends(window_query(720)),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    """Return what the mesh did on each local day of the window (#294).

    Packets first seen, uploads, and distinct nodes that sent a packet,
    for each day in `DISPLAY_TIMEZONE`. This is traffic on the day.
    `/snapshots/daily` is not: it holds the whole-table totals the jobs
    service counted once a UTC day, which is "packets still kept", and
    it stays as it is for anybody who reads it.

    A day with no traffic is a zero. A day older than packet retention
    is left out, because its rows are gone and a zero would claim the
    mesh was quiet.
    """
    settings: Settings = request.app.state.settings
    return await _daily_cache.get(
        window.key,
        cache_seconds(settings, window),
        lambda: _read_daily(session, settings, window),
    )


async def _read_daily(
    session: AsyncSession, settings: Settings, window: Window
) -> dict[str, object]:
    """Count each local day's packets, uploads and senders."""
    zone = ZoneInfo(settings.display_timezone)
    # From the hourly totals, with the partial hour at each end from the
    # raw rows (#366). It counted every raw row of the window by day.
    packet_days, upload_days = await hourly.daily_counts(
        session, settings.display_timezone, window.start, window.end
    )

    def local(moment: datetime) -> date:
        return moment.astimezone(zone).date()

    packets = {local(day): counts for day, counts in packet_days.items()}
    uploads = {local(day): count for day, count in upload_days.items()}
    first = local(max(window.start, retained_from(settings)))
    # The end is exclusive. A window that ends at a local midnight holds
    # nothing of the day that midnight starts, so that day is not listed.
    last = local(window.end - timedelta(microseconds=1))
    days = []
    current = first
    while current <= last:
        sent, nodes = packets.get(current, (0, 0))
        days.append(
            {
                "day": current.isoformat(),
                "packet_count": sent,
                "observation_count": uploads.get(current, 0),
                "node_count": nodes,
            }
        )
        current += timedelta(days=1)
    return {**window.describe(settings), "timezone": settings.display_timezone, "days": days}


@router.get("/activity")
async def activity(
    request: Request,
    window: Window = Depends(window_query(24)),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    """Return packet counts for each hour or day, split by packet family.

    This answers "what is the mesh actually doing", and how that changes
    through the day. Node info and position usually dominate.

    The time used is when this process received the packet, never a time
    the packet carries. Node clocks have been seen nearly 28 hours out.
    See AGENTS.md 9.4.

    Windows longer than `HOURLY_UP_TO_HOURS` come in local days, and
    `bucket` says which. `hours` holds the start of each bucket either
    way, so an older reader still gets a list of times.
    """
    settings: Settings = request.app.state.settings
    return await _activity_cache.get(
        window.key,
        cache_seconds(settings, window),
        lambda: _read_activity(session, settings, window),
    )


async def _read_activity(
    session: AsyncSession, settings: Settings, window: Window
) -> dict[str, object]:
    """Group the window's packets by bucket and family."""
    by_day = window.hours > HOURLY_UP_TO_HOURS
    # From the hourly totals by family, with the partial hour at each
    # end from the raw rows (#368). It grouped every raw packet of the
    # window: 525 ms of database time for 30 days.
    #
    # The window's upper bound still matters. `packet.first_seen_at`
    # holds the gateway's own clock when it sent one, and those clocks
    # run wrong: rows dated more than a day ahead exist. Without the
    # bound the chart grows hours that have not happened. See
    # docs/ISSUES.md 1.5.
    rows = await hourly.family_counts(
        session, settings.display_timezone, window.start, window.end, by_day=by_day
    )

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
        **window.describe(settings),
        "bucket": "day" if by_day else "hour",
        "hours": hours_seen,
        "families": [
            {
                "name": name,
                "total": totals[name],
                # One value for each bucket, zero where nothing was sent.
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
    restarts=0,
    restarts_24h=0,
    nodeinfo_ratio_24h=None,
    restarted=False,
    likely_power_loop=False,
)


def _node_num_of(item: BroadcastReport) -> int:
    """Return the node number a report was built from."""
    return int(item["node_id"].lstrip("!"), 16)


@router.get("/broadcast")
async def broadcast_rates(
    request: Request,
    window: Window = Depends(window_query(24)),
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
    settings: Settings = request.app.state.settings
    return await _broadcast_cache.get(
        f"{window.key}:{limit}",
        cache_seconds(settings, window),
        lambda: _read_broadcast(session, settings, window, limit),
    )


async def _read_broadcast(
    session: AsyncSession, settings: Settings, window: Window, limit: int
) -> dict[str, object]:
    """Measure each node's broadcast rates over the window.

    A rolling window the jobs service builds (#371) is read from its
    tables while the build is fresh, and states the window it measured.
    """
    hours = int(window.key[1:]) if window.key[1:].isdigit() and window.key[0] == "h" else None
    stored = None
    if hours in read_models.BROADCAST_HOURS:
        stored = await read_models.read_broadcast(session, hours)
    if stored is not None:
        measured = Window(stored.window_start, stored.window_end, key=window.key)
        body = await _present_broadcast(session, measured.describe(settings), stored.ranking, limit)
        return body | {"built_at": stored.built_at}
    ranking = await broadcast_ranking(session, window.start, window.end)
    body = await _present_broadcast(session, window.describe(settings), ranking, limit)
    return body | {"built_at": datetime.now(UTC)}


#: One ranked node: number, packets, notable families, families faster
#: than the default, each family's rate, and the health reading.
RankedNode = tuple[int, int, list[str], list[str], dict[str, dict[str, object]], dict | None]


@dataclass
class BroadcastRanking:
    """Every node's broadcast rates over one window, ranked, with no names.

    What the jobs service stores (#371) and what the endpoint presents.
    """

    nodes: list[RankedNode]
    notable_count: int
    power_loop_count: int


async def broadcast_ranking(
    session: AsyncSession, start: datetime, end: datetime
) -> BroadcastRanking:
    """Count each node's broadcasts in `[start, end)` and rank the nodes.

    The counts come from the hourly totals per sender and port (#371),
    with the partial hour at each end from the raw rows. It grouped every
    raw packet of the window: 1.7 s over 30 days.
    """
    window_seconds = round((end - start).total_seconds())
    wanted = {name: portnums_pb2.PortNum.Value(name) for name in BROADCAST_INTERVALS}  # type: ignore[attr-defined]
    by_number = {number: name for name, number in wanted.items()}

    rows = await hourly.sender_port_counts(session, start, end, list(wanted.values()))

    families: dict[int, dict[str, FamilyRate]] = {}
    for node_num, portnum, total in rows:
        name = by_number[portnum]
        default = BROADCAST_INTERVALS[name]
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

    health = await _node_health(session, list(families), start, window_seconds, end)
    report = [_broadcast_report(node_num, "", rates) for node_num, rates in families.items()]
    report.sort(
        key=lambda item: broadcast_order(
            loop=health.get(_node_num_of(item), EMPTY_HEALTH)["likely_power_loop"],
            notable=item["notable"],
            faster=item["faster_than_default"],
            packets=item["packet_count"],
            node=_node_num_of(item),
        )
    )
    return BroadcastRanking(
        nodes=[
            (
                _node_num_of(item),
                item["packet_count"],
                item["notable"],
                item["faster_than_default"],
                {name: vars(rate) for name, rate in item["families"].items()},
                cast("dict | None", health.get(_node_num_of(item))),
            )
            for item in report
        ],
        notable_count=sum(1 for item in report if item["notable"]),
        power_loop_count=sum(
            1
            for item in report
            if health.get(_node_num_of(item), EMPTY_HEALTH)["likely_power_loop"]
        ),
    )


async def _present_broadcast(
    session: AsyncSession,
    described: dict[str, object],
    ranking: BroadcastRanking,
    limit: int,
) -> dict[str, object]:
    """The endpoint's answer from a ranking: names joined now, `limit` applied."""
    shown = ranking.nodes[:limit]
    names = await resolve_names(session, [node for node, *_ in shown])
    return {
        **described,
        "intervals": BROADCAST_INTERVALS,
        "notable_ratio": NOTABLE_RATIO,
        "loop_restarts": LOOP_RESTARTS,
        "loop_hours": round(LOOP_SPAN.total_seconds() / 3600),
        "node_count": len(ranking.nodes),
        "notable_count": ranking.notable_count,
        "power_loop_count": ranking.power_loop_count,
        "nodes": [
            {
                "node_id": format_node_id(node),
                "display_name": name_of(names, node),
                "packet_count": packets,
                "notable": notable,
                "faster_than_default": faster,
                "families": families,
                "health": health,
            }
            for node, packets, notable, faster, families, health in shown
        ],
    }
