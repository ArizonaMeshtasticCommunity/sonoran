"""Store what `ingest/presets.py` decides (#313).

The ingest role has INSERT and UPDATE, and SELECT on a few key columns
only (AGENTS.md 9.1 and 9.2). Each statement here is shaped by that:

- Every write is a plain `UPDATE ... WHERE key = ...`. There is no
  `ON CONFLICT DO UPDATE`, which PostgreSQL denies to this role.
- A packet is found by its natural key, (`from_node_num`, `packet_id`),
  and by its partition column, so the update reads one chunk. The
  generated `packet.id` cannot be read back and is never used.
- Nothing here reads a `packet` row. The only read is the start-up
  read of each gateway's stored preset from `node`.

Revision i313 grants the column reads these statements need.
"""

from datetime import datetime, timedelta

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from sonoran.db.models import Node, Packet
from sonoran.ingest.handlers.presence import is_real_node
from sonoran.ingest.presets import PacketPreset, PresetTracker


async def load_gateway_presets(session: AsyncSession, tracker: PresetTracker) -> int:
    """Seed the tracker from `node.uplink_preset`. Return how many it read."""
    rows = (
        await session.execute(
            select(Node.node_num, Node.uplink_preset, Node.uplink_preset_at).where(
                Node.uplink_preset.is_not(None)
            )
        )
    ).all()
    for node_num, preset, at in rows:
        tracker.seed(node_num, preset, at)
    return len(rows)


async def store_packet_preset(
    session: AsyncSession,
    from_node: int,
    packet_id: int,
    change: PacketPreset,
    slack: timedelta,
) -> None:
    """Write a packet's new majority preset.

    When the tracker knows the packet's own time, the update names it
    exactly. Otherwise it names a window that ends at the observation
    that started the tally and is `slack` long. A packet older than that
    keeps the preset it has, which is the documented cost of a restart.
    """
    if change.exact:
        when = Packet.first_seen_at == change.first_seen_at
    else:
        when = Packet.first_seen_at.between(change.first_seen_at - slack, change.first_seen_at)
    await session.execute(
        update(Packet)
        .where(Packet.from_node_num == from_node, Packet.packet_id == packet_id, when)
        .values(modem_preset=change.preset)
    )


async def store_last_preset(
    session: AsyncSession, node_num: int, preset: str, at: datetime
) -> None:
    """Set a node's `last_preset`, unless a newer packet already set it.

    `at` is the receive time of the packet, never a time the packet
    claims for itself (AGENTS.md 9.4). The node row exists, because
    `store_heard` runs for the sender first.
    """
    if not is_real_node(node_num):
        return
    await session.execute(
        update(Node)
        .where(
            Node.node_num == node_num,
            or_(Node.last_preset_at.is_(None), Node.last_preset_at <= at),
        )
        .values(last_preset=preset, last_preset_at=at)
    )


async def store_vote(
    session: AsyncSession,
    tracker: PresetTracker,
    from_node: int,
    packet_id: int,
    preset: str | None,
    at: datetime,
    is_new: bool,
) -> None:
    """Count one observation, and store whatever it changed.

    Run it after the packet and the sender's node row are stored. A new
    packet's first preset is already in its INSERT, so only the node is
    written then.
    """
    change = tracker.vote(from_node, packet_id, preset, at, is_new)
    if change is None:
        return
    if not change.inserted:
        await store_packet_preset(session, from_node, packet_id, change, tracker.tally_ttl)
    await store_last_preset(session, from_node, change.preset, change.first_seen_at)
