"""Shared packet fields for storage handlers."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class HandlerContext:
    """Packet fields shared by packet-family handlers."""

    packet_pk: int | None
    # The Meshtastic packet ID. Ingest holds it before any write, so
    # every payload row can point at the packet that carried it.
    packet_id: int
    # The request a reply answers, from the Data payload. Traceroute
    # replies carry it; most other packets do not.
    request_id: int | None
    from_node_num: int
    to_node_num: int | None
    channel: str | None
    reply_id: int | None
    emoji: bool
    store_text_messages: bool
    seen_at: datetime
