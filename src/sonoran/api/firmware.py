"""The node page's firmware block (#406).

What a node reported in its newest map report, against the stable
release the jobs service stored. The comparison is in
`sonoran/firmware.py`. Both values are read from the database; nothing
here calls out to the internet.
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sonoran.db.models import FirmwareRelease, Node
from sonoran.firmware import firmware_status

#: Where the page sends a reader to update. The official web flasher.
FLASHER_URL = "https://flasher.meshtastic.org/"


async def node_firmware(session: AsyncSession, node_num: int) -> dict[str, Any]:
    """Return the firmware block of one node's detail page."""
    reported = (
        await session.execute(
            select(Node.firmware_version, Node.firmware_version_at).where(Node.node_num == node_num)
        )
    ).one_or_none()
    stable = (
        await session.execute(
            select(
                FirmwareRelease.version, FirmwareRelease.page_url, FirmwareRelease.fetched_at
            ).where(FirmwareRelease.channel == "stable")
        )
    ).one_or_none()
    version = reported.firmware_version if reported is not None else None
    return {
        "version": version,
        "reported_at": reported.firmware_version_at if reported is not None else None,
        "status": firmware_status(version, stable.version if stable is not None else None),
        "stable_version": stable.version if stable is not None else None,
        "stable_url": stable.page_url if stable is not None else None,
        "stable_checked_at": stable.fetched_at if stable is not None else None,
        "flasher_url": FLASHER_URL,
    }
