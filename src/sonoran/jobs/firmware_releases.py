"""Fetch the newest stable firmware release (#406).

The list is the one flasher.meshtastic.org reads:
`https://api.meshtastic.org/github/firmware/list` (meshtastic/web-flasher
`stores/firmwareStore.ts`, `createUrl('api/github/firmware/list')`).
The node page compares each node's reported version with it, so a page
view never calls out to the internet.

The job replaces the `firmware_release` rows with DELETE and INSERT in
one transaction, as the other job outputs do (AGENTS.md 4). When the
fetch fails, or the answer has no stable release we can read, the job
changes nothing and the last good release stays.
"""

from datetime import UTC, datetime

import httpx
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from sonoran.config import Settings
from sonoran.db.models import FirmwareRelease
from sonoran.firmware import Release, stable_from_release_list
from sonoran.logging import get_logger

logger = get_logger(__name__)

#: How long one fetch may take, in seconds. The answer is about 60 kB.
FETCH_TIMEOUT_SECONDS = 30.0


async def fetch_stable(
    url: str, transport: httpx.AsyncBaseTransport | None = None
) -> Release | None:
    """Return the newest stable release from the official list, or None."""
    try:
        async with httpx.AsyncClient(
            timeout=FETCH_TIMEOUT_SECONDS,
            transport=transport,
            headers={"User-Agent": "sonoran (azmsh.net Meshtastic dashboard)"},
            follow_redirects=False,
        ) as client:
            response = await client.get(url)
            response.raise_for_status()
            body = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("could not fetch the firmware release list: %s", exc)
        return None
    release = stable_from_release_list(body)
    if release is None:
        logger.warning("the firmware release list has no stable release we can read")
    return release


async def refresh(
    session: AsyncSession,
    settings: Settings,
    transport: httpx.AsyncBaseTransport | None = None,
) -> Release | None:
    """Fetch the stable release and store it. Return it, or None."""
    release = await fetch_stable(settings.firmware_releases_url, transport)
    if release is None:
        return None
    async with session.begin():
        await session.execute(delete(FirmwareRelease))
        session.add(
            FirmwareRelease(
                channel="stable",
                version=release.version,
                page_url=release.page_url,
                fetched_at=datetime.now(UTC),
            )
        )
    logger.info("the stable firmware release is %s", release.version)
    return release
