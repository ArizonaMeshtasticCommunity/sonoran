"""Build the read models: the long-window views the API reads (#371).

Each run builds, one after another:

- **Link evidence** for every channel with neighbour reports or
  traceroutes in the last 7 days (the busiest `MAX_LINK_CHANNELS`), and
  for every channel together, over the graph page's windows. For each
  assessed preset also over the longest-link board's windows. The graph
  and the board read the same build.
- **Broadcast rates** over the Statistics page's quick ranges.
- **The nodes heard on each preset channel** in the last 7 days, for the
  coverage page.

Windows of `read_models.LONG_HOURS` or more are built on every
`READ_MODELS_LONG_EVERY`-th run only, and on the first run when none is
stored. Each build is its own transaction, so a reader sees a whole
build or the one before it, never half of one.

No engine, so this may run beside a coverage build. It does not: it
holds tens of thousands of rows for a 30 day window, and the jobs
container's memory is shared with the coverage run. The scheduler skips
a run while coverage is going. The API computes the views live meanwhile,
which is what it did before.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sonoran import read_models
from sonoran.api.channels import channel_filter
from sonoran.api.routes import graph
from sonoran.api.routes.stats import broadcast_ranking
from sonoran.config import Settings
from sonoran.db.models import BroadcastRun, LinkEvidenceRun, PacketSeen
from sonoran.gaps import store as gaps_store
from sonoran.logging import get_logger
from sonoran.radio.presets import preset_for_channel

logger = get_logger(__name__)

#: At most this many channels get link evidence of their own. Topic
#: channels with a handful of links are cheap, but the list is open-ended.
MAX_LINK_CHANNELS = 6


async def _link_channels(session: AsyncSession, now: datetime) -> list[str]:
    """The channels with links in the last 7 days, busiest first."""
    counts = await graph._channel_link_counts(session, now - timedelta(hours=168))
    named = [(name, total) for name, total in counts.items() if name and total > 0]
    named.sort(key=lambda item: (-item[1], item[0]))
    return [name for name, _ in named[:MAX_LINK_CHANNELS]]


async def _preset_channels(session: AsyncSession, now: datetime) -> list[str]:
    """The channels with traffic in the last 7 days that name a modem preset."""
    counts = await graph._channel_packet_counts(session, now - timedelta(hours=168))
    return sorted(name for name in counts if name and preset_for_channel(name) is not None)


async def _stored(session: AsyncSession, model: Any, **key: object) -> bool:
    """True when a build is stored for this key, fresh or not."""
    conditions = [getattr(model, name) == value for name, value in key.items()]
    found = await session.scalar(select(model.built_at).where(*conditions))
    return found is not None


def plan_links(link_channels: list[str], presets: list[str]) -> list[tuple[str, int]]:
    """The (channel, hours) builds of link evidence, in order.

    The graph's windows for every channel with links and for every
    channel together, then the board's windows for each preset. Each pair
    once. `run_once` decides whether a long window is due on a run.
    """
    planned: list[tuple[str, int]] = []
    for channel in [read_models.EVERY_CHANNEL, *link_channels]:
        planned += [(channel, hours) for hours in read_models.GRAPH_HOURS]
    for preset in presets:
        planned += [(preset, hours) for hours in read_models.BOARD_HOURS]
    return list(dict.fromkeys(planned))


async def run_once(session: AsyncSession, settings: Settings, run_number: int) -> None:
    """Build every read model that is due, one transaction each."""
    started = time.monotonic()
    now = datetime.now(UTC)
    long_every = max(settings.read_models_long_every, 1)
    long_due = run_number % long_every == 0

    link_channels = await _link_channels(session, now)
    presets = [str(item["preset"]) for item in await gaps_store.assessed_presets(session, settings)]
    built = 0
    for channel, hours in plan_links(link_channels, presets):
        if hours >= read_models.LONG_HOURS and not long_due:
            # Due only every few runs, unless nothing is stored at all.
            if await _stored(session, LinkEvidenceRun, channel=channel, hours=hours):
                continue
        end = datetime.now(UTC)
        since = end - timedelta(hours=hours)
        edges = await graph.link_evidence(session, since, channel or None)
        counts = await graph._packet_counts(session, since)
        await read_models.write_links(session, channel, hours, since, end, edges.values(), counts)
        built += 1
        del edges, counts

    for hours in read_models.BROADCAST_HOURS:
        if hours >= read_models.LONG_HOURS and not long_due:
            if await _stored(session, BroadcastRun, hours=hours):
                continue
        end = datetime.now(UTC)
        since = end - timedelta(hours=hours)
        ranking = await broadcast_ranking(session, since, end)
        await read_models.write_broadcast(session, hours, since, end, ranking)
        built += 1

    for channel in await _preset_channels(session, now):
        for hours in read_models.CHANNEL_NODE_HOURS:
            heard = (
                await session.scalars(
                    select(PacketSeen.from_node_num)
                    .where(
                        PacketSeen.seen_at >= datetime.now(UTC) - timedelta(hours=hours),
                        channel_filter(PacketSeen.channel, channel),
                    )
                    .distinct()
                )
            ).all()
            await read_models.write_channel_nodes(session, channel, hours, heard)
            built += 1

    logger.info(
        "built %d read models in %.1fs (link channels %s, presets %s, 30 day windows %s)",
        built,
        time.monotonic() - started,
        link_channels,
        presets,
        "due" if long_due else "kept",
    )
