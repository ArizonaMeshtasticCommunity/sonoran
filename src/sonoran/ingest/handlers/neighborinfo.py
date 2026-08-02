"""NeighborInfo packet storage."""

from datetime import UTC, datetime
from typing import Any

from google.protobuf.message import Message
from sqlalchemy.ext.asyncio import AsyncSession

from sonoran.db.models import NeighborMetrics
from sonoran.ingest.handlers.context import HandlerContext


async def store_neighborinfo(
    session: AsyncSession, message: Message, context: HandlerContext
) -> None:
    """Store one metric row for each neighbor link."""
    report: Any = message
    for neighbor in report.neighbors:
        last_rx_time = (
            datetime.fromtimestamp(neighbor.last_rx_time, UTC) if neighbor.last_rx_time else None
        )
        session.add(
            NeighborMetrics(
                node_num=context.from_node_num,
                packet_pk=context.packet_pk,
                packet_id=context.packet_id,
                neighbor_node_num=neighbor.node_id,
                channel=context.channel,
                snr=neighbor.snr,
                last_rx_time=last_rx_time,
                node_broadcast_interval_secs=neighbor.node_broadcast_interval_secs or None,
                time=context.seen_at,
            )
        )
