"""Position packet storage."""

from datetime import UTC, datetime
from typing import Any

from google.protobuf.message import Message
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from sonoran.db.models import Node, PositionMetrics
from sonoran.ingest.handlers.context import HandlerContext
from sonoran.positions import clean


def _position_time(position: Any, fallback: datetime) -> datetime:
    """Use the position time when the packet provides one."""
    if position.time:
        return datetime.fromtimestamp(position.time, UTC)
    return fallback


async def store_position(session: AsyncSession, message: Message, context: HandlerContext) -> None:
    """Store position history and update the latest node position."""
    position: Any = message
    time = _position_time(position, context.seen_at)
    # A node with no fix still sends a position packet. The numbers in
    # it are whatever the field held, which puts the node in the ocean
    # off West Africa. Store nothing rather than store a wrong place.
    latitude, longitude = clean(
        position.latitude_i / 10_000_000 if position.latitude_i else None,
        position.longitude_i / 10_000_000 if position.longitude_i else None,
    )
    values = {
        "node_num": context.from_node_num,
        "packet_pk": context.packet_pk,
        "packet_id": context.packet_id,
        "latitude": latitude,
        "longitude": longitude,
        "altitude": position.altitude or None,
        "ground_speed": position.ground_speed or None,
        "ground_track": position.ground_track or None,
        "precision_bits": position.precision_bits or None,
        "sats_in_view": position.sats_in_view or None,
        "time": time,
    }
    session.add(PositionMetrics(**values))
    await session.execute(
        update(Node)
        .where(Node.node_num == context.from_node_num)
        .values(
            last_lat=latitude,
            last_lon=longitude,
            last_altitude=values["altitude"],
            position_time=time,
            updated_at=context.seen_at,
        )
    )
