"""PaxCounter packet storage."""

from typing import Any

from google.protobuf.message import Message
from sqlalchemy.ext.asyncio import AsyncSession

from sonoran.db.models import PaxMetrics
from sonoran.ingest.handlers.context import HandlerContext


async def store_paxcounter(
    session: AsyncSession, message: Message, context: HandlerContext
) -> None:
    """Store a people-count telemetry report."""
    report: Any = message
    session.add(
        PaxMetrics(
            node_num=context.from_node_num,
            packet_pk=context.packet_pk,
            packet_id=context.packet_id,
            wifi_count=report.wifi,
            ble_count=report.ble,
            uptime_seconds=report.uptime,
            time=context.seen_at,
        )
    )
