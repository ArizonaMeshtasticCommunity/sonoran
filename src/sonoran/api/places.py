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
"""

from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sonoran.api.names import BROADCAST_NODE_NUM
from sonoran.db.models import Node
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
        confidence, _ = position_confidence(lat, lon, bits, MIN_SITE_PRECISION_BITS)
        if confidence == "none":
            continue
        places[num] = {"lat": lat, "lon": lon, "confidence": confidence}
    return places
