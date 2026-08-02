"""Packet-family storage handlers."""

from sqlalchemy.ext.asyncio import AsyncSession

from sonoran.decode.payloads import DecodedPayload, ProtobufPayload, TextPayload
from sonoran.ingest.handlers.context import HandlerContext
from sonoran.ingest.handlers.meshpacket import (
    store_mesh_packet_metrics as store_mesh_packet_metrics,
)
from sonoran.ingest.handlers.neighborinfo import store_neighborinfo
from sonoran.ingest.handlers.nodeinfo import store_nodeinfo
from sonoran.ingest.handlers.paxcounter import store_paxcounter
from sonoran.ingest.handlers.position import store_position
from sonoran.ingest.handlers.telemetry import store_telemetry
from sonoran.ingest.handlers.text import store_text
from sonoran.ingest.handlers.traceroute import store_traceroute
from sonoran.meshtastic import portnums_pb2


async def store_payload(
    session: AsyncSession,
    decoded: DecodedPayload,
    context: HandlerContext,
) -> None:
    """Store data for one decoded packet family."""
    if isinstance(decoded, TextPayload):
        await store_text(session, decoded, context)
        return
    if not isinstance(decoded, ProtobufPayload):
        return
    if decoded.portnum == portnums_pb2.NODEINFO_APP:  # type: ignore[attr-defined]
        await store_nodeinfo(session, decoded.message, context)
    elif decoded.portnum == portnums_pb2.POSITION_APP:  # type: ignore[attr-defined]
        await store_position(session, decoded.message, context)
    elif decoded.portnum == portnums_pb2.TELEMETRY_APP:  # type: ignore[attr-defined]
        await store_telemetry(session, decoded.message, context)
    elif decoded.portnum == portnums_pb2.NEIGHBORINFO_APP:  # type: ignore[attr-defined]
        await store_neighborinfo(session, decoded.message, context)
    elif decoded.portnum == portnums_pb2.TRACEROUTE_APP:  # type: ignore[attr-defined]
        await store_traceroute(session, decoded.message, context)
    elif decoded.portnum == portnums_pb2.PAXCOUNTER_APP:  # type: ignore[attr-defined]
        await store_paxcounter(session, decoded.message, context)
