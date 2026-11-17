"""Where nodes are, for a map that draws more than one node (beta-sonoran#412).

The packet page draws the sender and the gateways that uploaded the
packet. The node page draws the neighbors the node reports. Both need
the position of nodes other than the one the page is about.

The rules are the ones the node map already uses for the node itself:

- A position that is not a real place is no position
  (`sonoran.positions.is_usable`). The node is left off the map.
- A position that its owner rounded is `coarse`
  (`gaps.signals.position_confidence` with `MIN_SITE_PRECISION_BITS`).
  The page draws it hollow, with no radius (#96).

The packet map asks where each node was when the packet was sent, not
where it is now (review of beta-sonoran#413). `resolve_places_at` reads that from
`position_metrics`, which keeps each position for
`RETENTION_DAYS_POSITION` days (30 by default, migration 0005). A position's `time` is never
later than when Sonoran received it (`ingest/handlers/position.py`,
AGENTS.md 9.4), so "at or before the packet" cannot pick a later one.
"""

from collections.abc import Iterable
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sonoran.api.names import BROADCAST_NODE_NUM
from sonoran.db.models import Node, PositionMetrics
from sonoran.gaps.signals import position_confidence
from sonoran.positions import MIN_SITE_PRECISION_BITS


async def resolve_places(
    session: AsyncSession, node_nums: Iterable[int | None]
) -> dict[int, dict[str, object]]:
    """Return the last known position of each node that has a real one.

    The result maps a node number to `lat`, `lon` and `confidence`
    (`exact` or `coarse`). A node with no usable position is absent.
    """
    wanted = {num for num in node_nums if num is not None and num != BROADCAST_NODE_NUM}
    if not wanted:
        return {}
    rows = await session.execute(
        select(
            Node.node_num, Node.last_lat, Node.last_lon, Node.last_position_precision_bits
        ).where(Node.node_num.in_(wanted))
    )
    places: dict[int, dict[str, object]] = {}
    for num, lat, lon, bits in rows.all():
        if num not in wanted:
            continue
        confidence, _ = position_confidence(lat, lon, bits, MIN_SITE_PRECISION_BITS)
        if confidence == "none":
            continue
        places[num] = {"lat": lat, "lon": lon, "confidence": confidence}
    return places


async def resolve_places_at(
    session: AsyncSession, node_nums: Iterable[int | None], at: datetime
) -> dict[int, dict[str, object]]:
    """Return where each node last said it was, at or before `at`.

    The result maps a node number to `lat`, `lon`, `confidence` and the
    `time` of that position. A node that reported no real position
    before `at`, or whose position aged out, is absent. Its current
    position is never used instead: that would draw it where it went
    later.
    """
    wanted = {num for num in node_nums if num is not None and num != BROADCAST_NODE_NUM}
    if not wanted:
        return {}
    rows = await session.execute(
        select(
            PositionMetrics.node_num,
            PositionMetrics.latitude,
            PositionMetrics.longitude,
            PositionMetrics.precision_bits,
            PositionMetrics.time,
        )
        .where(
            PositionMetrics.node_num.in_(wanted),
            PositionMetrics.time <= at,
            PositionMetrics.latitude.is_not(None),
            PositionMetrics.longitude.is_not(None),
        )
        .distinct(PositionMetrics.node_num)
        .order_by(PositionMetrics.node_num, PositionMetrics.time.desc())
    )
    places: dict[int, dict[str, object]] = {}
    for num, lat, lon, bits, time in rows.all():
        if num not in wanted:
            continue
        confidence, _ = position_confidence(lat, lon, bits, MIN_SITE_PRECISION_BITS)
        if confidence == "none":
            continue
        places[num] = {"lat": lat, "lon": lon, "confidence": confidence, "time": time}
    return places
