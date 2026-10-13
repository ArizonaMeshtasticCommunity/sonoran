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

Windows of `read_models.LONG_HOURS` or more are built when their stored
build is older than `READ_MODELS_LONG_EVERY` runs, or when none is
stored. Each build is its own transaction, so a reader sees a whole
build or the one before it, never half of one.

No engine. Each run is its own process under the jobs supervisor
(`jobs/supervisor.py`), with its own memory ceiling, and runs beside a
coverage build when both fit in the container's memory.
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


async def _due(
    session: AsyncSession, settings: Settings, model: Any, window_hours: int, **key: object
) -> bool:
    """True when a window should be built on this run.

    A short window: every run. A long one (`read_models.LONG_HOURS`):
    when nothing is stored, or when the stored build is older than its
    interval, less half a run so the clock does not drift a run late. The
    age is in the database, so it lasts across runs, which are separate
    processes.
    """
    if window_hours < read_models.LONG_HOURS:
        return True
    conditions = [getattr(model, name) == value for name, value in key.items()]
    built_at = await session.scalar(select(model.built_at).where(*conditions))
    if built_at is None:
        return True
    slack = timedelta(minutes=max(settings.read_models_interval_minutes, 1) / 2)
    return (
        datetime.now(UTC) - built_at >= read_models.build_interval(window_hours, settings) - slack
    )


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


async def run_once(session: AsyncSession, settings: Settings) -> None:
    """Build every read model that is due, one transaction each."""
    started = time.monotonic()
    now = datetime.now(UTC)

    link_channels = await _link_channels(session, now)
    presets = [str(item["preset"]) for item in await gaps_store.assessed_presets(session, settings)]
    built = 0
    for channel, hours in plan_links(link_channels, presets):
        if not await _due(session, settings, LinkEvidenceRun, hours, channel=channel, hours=hours):
            continue
        end = datetime.now(UTC)
        since = end - timedelta(hours=hours)
        edges = await graph.link_evidence(session, since, channel or None)
        counts = await graph._packet_counts(session, since)
        await read_models.write_links(session, channel, hours, since, end, edges.values(), counts)
        built += 1
        del edges, counts

    for hours in read_models.BROADCAST_HOURS:
        if not await _due(session, settings, BroadcastRun, hours, hours=hours):
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
        "built %d read models in %.1fs (link channels %s, presets %s)",
        built,
        time.monotonic() - started,
        link_channels,
        presets,
    )
