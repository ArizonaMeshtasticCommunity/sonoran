"""Traceroute packet storage."""

from typing import Any

from google.protobuf.message import Message
from sqlalchemy.ext.asyncio import AsyncSession

from sonoran.db.models import Traceroute
from sonoran.ingest.handlers.context import HandlerContext


async def store_traceroute(
    session: AsyncSession, message: Message, context: HandlerContext
) -> None:
    """Store a traceroute route and its signal-to-noise values."""
    route: Any = message
    session.add(
        Traceroute(
            packet_pk=context.packet_pk,
            packet_id=context.packet_id,
            request_id=context.request_id,
            from_node_num=context.from_node_num,
            to_node_num=context.to_node_num or 0,
            channel=context.channel,
            route=list(route.route),
            route_back=list(route.route_back) or None,
            snr_towards=list(route.snr_towards) or None,
            snr_back=list(route.snr_back) or None,
            seen_at=context.seen_at,
        )
    )
