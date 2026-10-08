"""Node presence storage.

A NodeInfo packet gives the name of a node. It does not say when the
mesh last heard the node. This module records presence from every
packet, so `node.last_heard` is correct even for a node that never
sends NodeInfo.

The ingest role has INSERT and UPDATE rights only, and no SELECT. That
rule shapes two decisions here.

1. Each function runs two statements instead of one upsert:

       INSERT ... ON CONFLICT DO NOTHING   -- create the row if absent
       UPDATE ...                          -- write the new values

   `ON CONFLICT DO UPDATE` is not used. PostgreSQL denies that form to a
   role without SELECT on the table, because the update path may read
   the stored row. `DO NOTHING` and a plain `UPDATE` both work.

2. The time comes from when this process received the message, not from
   the `rx_time` inside the packet. Receive time rises with the message
   stream, so `last_heard` moves forward on its own. It also stops a
   node with a wrong clock from setting a time far in the past or
   future.
"""

from datetime import datetime

from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from sonoran.db.models import Node

# The broadcast address is not a real node.
BROADCAST_NODE_NUM = 0xFFFFFFFF


def is_real_node(node_num: int | None) -> bool:
    """Return true when a node number belongs to a real node."""
    return bool(node_num) and node_num != BROADCAST_NODE_NUM


async def _ensure_row(session: AsyncSession, node_num: int, seen_at: datetime) -> None:
    """Create the node row when it does not exist yet."""
    await session.execute(
        insert(Node)
        .values(
            node_num=node_num,
            node_id=f"!{node_num:08x}",
            first_seen=seen_at,
            updated_at=seen_at,
        )
        .on_conflict_do_nothing(index_elements=[Node.node_num])
    )


async def store_heard(
    session: AsyncSession,
    node_num: int,
    seen_at: datetime,
    channel: str | None = None,
) -> None:
    """Record that the mesh heard one node.

    Pass the time this process received the message.
    """
    if not is_real_node(node_num):
        return
    await _ensure_row(session, node_num, seen_at)
    values: dict[str, object] = {"last_heard": seen_at, "updated_at": seen_at}
    if channel:
        values["last_channel"] = channel
    await session.execute(update(Node).where(Node.node_num == node_num).values(**values))


async def store_gateway(
    session: AsyncSession,
    node_num: int,
    seen_at: datetime,
    mqtt_topic: str,
    uplink_preset: str | None = None,
) -> None:
    """Record that one node published a packet to the MQTT broker.

    A node that publishes is an MQTT gateway. The flag never returns to
    false, because a gateway that stops publishing was still a gateway.

    `uplink_preset` is the preset a preset-named topic named (#313). It
    goes in the same statement, so it costs no extra round trip, and
    ingest reads it back at start. See `ingest/presets.py`.
    """
    if not is_real_node(node_num):
        return
    await _ensure_row(session, node_num, seen_at)
    values: dict[str, object] = {
        "is_mqtt_gateway": True,
        "last_mqtt_topic": mqtt_topic,
        "last_heard": seen_at,
        "updated_at": seen_at,
    }
    if uplink_preset:
        values["uplink_preset"] = uplink_preset
        values["uplink_preset_at"] = seen_at
    await session.execute(update(Node).where(Node.node_num == node_num).values(**values))
