"""Map report storage: the firmware version a node reports (#406).

A node publishes a map report about itself, unencrypted, on the
`<root>/2/map/` topic (meshtastic/firmware v2.7.26.54e0d8d
src/mqtt/MQTT.cpp `perhapsReportToMap`). It does so only when its owner
turns on map reporting, by default once an hour (src/mesh/Default.h:32,
`default_map_publish_interval_secs`).

Only the firmware version is kept. NodeInfo owns the names, hardware
and role, and a map report never overwrites them.

The ingest role has INSERT and UPDATE only (AGENTS.md 9.2), so this
writes the version with a plain UPDATE after `_ensure_row`, as
`presence.py` does.
"""

from datetime import datetime

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from sonoran.db.models import Node
from sonoran.firmware import clean_reported_version
from sonoran.ingest.handlers.presence import _ensure_row, is_real_node


async def store_firmware_version(
    session: AsyncSession, node_num: int, reported: str | None, seen_at: datetime
) -> bool:
    """Record the version one node reported. Return whether it was stored.

    `seen_at` is the time this process received the report. A report
    whose version is empty or not plain text changes nothing, so the
    last good version stays.
    """
    version = clean_reported_version(reported)
    if version is None or not is_real_node(node_num):
        return False
    await _ensure_row(session, node_num, seen_at)
    await session.execute(
        update(Node)
        .where(Node.node_num == node_num)
        .values(firmware_version=version, firmware_version_at=seen_at)
    )
    return True
