"""Count packets and uploads from the hourly totals, exactly (#366, #368).

`packet_hourly` and `packet_seen_hourly` (revision i366) and
`packet_family_hourly` (revision i368) are TimescaleDB continuous
aggregates. A count over a window is:

- the whole hours inside it, summed from the aggregate, and
- the partial hour at each end, counted from the raw rows.

So the answer is the same number the raw rows give, to the row, and it
reads a few hundred rows where the raw count read millions. The current
hour is a partial hour or comes from the aggregate's real-time part, so
it is always live.

A window shorter than one whole hour is counted from the raw rows alone.

`docs/DATABASE.md` 8 describes the aggregates.
"""

from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import Select, column, func, select, table, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from sonoran.db.models import Packet, PacketSeen

HOUR = timedelta(hours=1)

PACKET_HOURLY = table("packet_hourly", column("bucket"), column("from_node_num"), column("packets"))
PACKET_SEEN_HOURLY = table("packet_seen_hourly", column("bucket"), column("uploads"))
PACKET_FAMILY_HOURLY = table(
    "packet_family_hourly",
    column("bucket"),
    column("portnum"),
    column("payload_state"),
    column("packets"),
)


def floor_hour(moment: datetime) -> datetime:
    """Return the start of the hour `moment` is in."""
    return moment.replace(minute=0, second=0, microsecond=0)


def ceil_hour(moment: datetime) -> datetime:
    """Return the first hour boundary at or after `moment`."""
    floor = floor_hour(moment)
    return floor if floor == moment else floor + HOUR


def split(start: datetime, end: datetime) -> tuple[datetime, datetime] | None:
    """Return the whole hours inside `[start, end)`, or None when there are none."""
    low, high = ceil_hour(start), floor_hour(end)
    return (low, high) if low < high else None


async def _raw(session: AsyncSession, model: Any, time: Any, start: datetime, end: datetime) -> int:
    if start >= end:
        return 0
    return (
        await session.scalar(
            select(func.count()).select_from(model).where(time >= start, time < end)
        )
    ) or 0


async def _summed(
    session: AsyncSession, view: Any, value: Any, start: datetime, end: datetime
) -> int:
    total = await session.scalar(
        select(func.coalesce(func.sum(value), 0)).where(view.c.bucket >= start, view.c.bucket < end)
    )
    return int(total or 0)


async def count_packets(session: AsyncSession, start: datetime, end: datetime) -> int:
    """Return the packets first seen in `[start, end)`."""
    hours = split(start, end)
    if hours is None:
        return await _raw(session, Packet, Packet.first_seen_at, start, end)
    low, high = hours
    return (
        await _raw(session, Packet, Packet.first_seen_at, start, low)
        + await _summed(session, PACKET_HOURLY, PACKET_HOURLY.c.packets, low, high)
        + await _raw(session, Packet, Packet.first_seen_at, high, end)
    )


async def count_uploads(session: AsyncSession, start: datetime, end: datetime) -> int:
    """Return the uploads (observations) received in `[start, end)`."""
    hours = split(start, end)
    if hours is None:
        return await _raw(session, PacketSeen, PacketSeen.seen_at, start, end)
    low, high = hours
    return (
        await _raw(session, PacketSeen, PacketSeen.seen_at, start, low)
        + await _summed(session, PACKET_SEEN_HOURLY, PACKET_SEEN_HOURLY.c.uploads, low, high)
        + await _raw(session, PacketSeen, PacketSeen.seen_at, high, end)
    )


def whole_hour_zone(zone: ZoneInfo, *moments: datetime) -> bool:
    """Return true when the zone is a whole number of hours from UTC at each moment.

    Hourly totals add up to local days only then. Arizona is always
    UTC-7. A zone such as India's, at UTC+5:30, would split an hour
    across two days, and a reader then counts from the raw rows.
    """
    for moment in moments:
        offset = moment.astimezone(zone).utcoffset()
        if offset is None or offset.total_seconds() % 3600:
            return False
    return True


def _local_day(value: Any, zone: str) -> Any:
    """The local midnight that starts the day `value` falls in."""
    return func.timezone(zone, func.date_trunc("day", func.timezone(zone, value)))


def _raw_by_day(zone: str, start: datetime, end: datetime) -> Select[Any]:
    day = _local_day(Packet.first_seen_at, zone)
    return (
        select(
            day.label("day"),
            Packet.from_node_num.label("node"),
            func.count().label("packets"),
        )
        .where(Packet.first_seen_at >= start, Packet.first_seen_at < end)
        .group_by(day, Packet.from_node_num)
    )


def _uploads_raw_by_day(zone: str, start: datetime, end: datetime) -> Select[Any]:
    day = _local_day(PacketSeen.seen_at, zone)
    return (
        select(day.label("day"), func.count().label("uploads"))
        .where(PacketSeen.seen_at >= start, PacketSeen.seen_at < end)
        .group_by(day)
    )


async def daily_counts(
    session: AsyncSession, zone_name: str, start: datetime, end: datetime
) -> tuple[dict[datetime, tuple[int, int]], dict[datetime, int]]:
    """Return each local day's (packets, distinct senders), and its uploads.

    The keys are the local midnight that starts each day, as the
    database gives it. Whole hours come from the aggregates and the
    partial hour at each end from the raw rows, and the senders of all
    three parts are counted once together, so a sender heard in both an
    edge and a whole hour of one day is one sender.
    """
    zone = ZoneInfo(zone_name)
    hours = split(start, end)
    if hours is None or not whole_hour_zone(zone, start, end):
        packet_parts = [_raw_by_day(zone_name, start, end)]
        upload_parts = [_uploads_raw_by_day(zone_name, start, end)]
    else:
        low, high = hours
        hourly_day = _local_day(PACKET_HOURLY.c.bucket, zone_name)
        seen_day = _local_day(PACKET_SEEN_HOURLY.c.bucket, zone_name)
        packet_parts = [
            _raw_by_day(zone_name, start, low),
            select(
                hourly_day.label("day"),
                PACKET_HOURLY.c.from_node_num.label("node"),
                func.sum(PACKET_HOURLY.c.packets).label("packets"),
            )
            .where(PACKET_HOURLY.c.bucket >= low, PACKET_HOURLY.c.bucket < high)
            .group_by(hourly_day, PACKET_HOURLY.c.from_node_num),
            _raw_by_day(zone_name, high, end),
        ]
        upload_parts = [
            _uploads_raw_by_day(zone_name, start, low),
            select(seen_day.label("day"), func.sum(PACKET_SEEN_HOURLY.c.uploads).label("uploads"))
            .where(PACKET_SEEN_HOURLY.c.bucket >= low, PACKET_SEEN_HOURLY.c.bucket < high)
            .group_by(seen_day),
            _uploads_raw_by_day(zone_name, high, end),
        ]

    parts = union_all(*packet_parts).subquery()
    packet_rows = (
        await session.execute(
            select(
                parts.c.day,
                func.sum(parts.c.packets).label("packets"),
                func.count(func.distinct(parts.c.node)).label("nodes"),
            ).group_by(parts.c.day)
        )
    ).all()
    uploaded = union_all(*upload_parts).subquery()
    upload_rows = (
        await session.execute(
            select(uploaded.c.day, func.sum(uploaded.c.uploads).label("uploads")).group_by(
                uploaded.c.day
            )
        )
    ).all()
    return (
        {row.day: (int(row.packets), int(row.nodes)) for row in packet_rows},
        {row.day: int(row.uploads) for row in upload_rows},
    )


def _raw_by_sender(start: datetime, end: datetime) -> Select[Any]:
    return (
        select(Packet.from_node_num.label("node"), func.count().label("packets"))
        .where(Packet.first_seen_at >= start, Packet.first_seen_at < end)
        .group_by(Packet.from_node_num)
    )


async def counts_by_sender(session: AsyncSession, start: datetime, end: datetime) -> dict[int, int]:
    """Return the packets each sender sent in `[start, end)`.

    The graph gives each node its packet count from this. Whole hours
    come from `packet_hourly`, which is already per sender.
    """
    hours = split(start, end)
    if hours is None:
        parts = [_raw_by_sender(start, end)]
    else:
        low, high = hours
        parts = [
            _raw_by_sender(start, low),
            select(
                PACKET_HOURLY.c.from_node_num.label("node"),
                func.sum(PACKET_HOURLY.c.packets).label("packets"),
            )
            .where(PACKET_HOURLY.c.bucket >= low, PACKET_HOURLY.c.bucket < high)
            .group_by(PACKET_HOURLY.c.from_node_num),
            _raw_by_sender(high, end),
        ]
    joined = union_all(*parts).subquery()
    rows = await session.execute(
        select(joined.c.node, func.sum(joined.c.packets)).group_by(joined.c.node)
    )
    return {int(node): int(packets) for node, packets in rows.all()}


def _raw_by_family(bucket: Any, start: datetime, end: datetime) -> Select[Any]:
    return (
        select(
            bucket.label("bucket"),
            Packet.portnum.label("portnum"),
            Packet.payload_state.label("payload_state"),
            func.count().label("packets"),
        )
        .where(Packet.first_seen_at >= start, Packet.first_seen_at < end)
        .group_by(bucket, Packet.portnum, Packet.payload_state)
    )


async def family_counts(
    session: AsyncSession, zone_name: str, start: datetime, end: datetime, *, by_day: bool
) -> list[tuple[datetime, int, str | None, int]]:
    """Return (bucket, portnum, payload_state, packets) for `[start, end)`, by bucket.

    The activity chart reads this. A bucket is the hour, or with
    `by_day` the local midnight that starts the day. Whole hours come
    from `packet_family_hourly` and the partial hour at each end from
    the raw rows, so each count equals the raw count.

    One exception. A payload recovery (`sonoran.ingest.recover`) can
    change the port and state of old packets. Until the next refresh,
    at most 30 minutes later, those hours show the packets in their old
    family. The total of each hour does not change.
    """
    zone = ZoneInfo(zone_name)
    if by_day:
        raw_bucket = _local_day(Packet.first_seen_at, zone_name)
        hourly_bucket = _local_day(PACKET_FAMILY_HOURLY.c.bucket, zone_name)
    else:
        raw_bucket = func.date_trunc("hour", Packet.first_seen_at)
        hourly_bucket = PACKET_FAMILY_HOURLY.c.bucket
    hours = split(start, end)
    if hours is None or (by_day and not whole_hour_zone(zone, start, end)):
        parts = [_raw_by_family(raw_bucket, start, end)]
    else:
        low, high = hours
        parts = [
            _raw_by_family(raw_bucket, start, low),
            select(
                hourly_bucket.label("bucket"),
                PACKET_FAMILY_HOURLY.c.portnum.label("portnum"),
                PACKET_FAMILY_HOURLY.c.payload_state.label("payload_state"),
                func.sum(PACKET_FAMILY_HOURLY.c.packets).label("packets"),
            )
            .where(PACKET_FAMILY_HOURLY.c.bucket >= low, PACKET_FAMILY_HOURLY.c.bucket < high)
            .group_by(
                hourly_bucket, PACKET_FAMILY_HOURLY.c.portnum, PACKET_FAMILY_HOURLY.c.payload_state
            ),
            _raw_by_family(raw_bucket, high, end),
        ]
    joined = union_all(*parts).subquery()
    rows = await session.execute(
        select(
            joined.c.bucket,
            joined.c.portnum,
            joined.c.payload_state,
            func.sum(joined.c.packets),
        )
        .group_by(joined.c.bucket, joined.c.portnum, joined.c.payload_state)
        .order_by(joined.c.bucket)
    )
    return [
        (bucket, portnum, payload_state, int(packets))
        for bucket, portnum, payload_state, packets in rows.all()
    ]
