"""Read models: long-window views built by the jobs service (#371).

The API runs one event loop. A view that covers hours or days, computed
while somebody waits, held up every other request: the longest-link board
took 11.6 s over 30 days. The jobs service now builds these views ahead
of time into the tables of revision i371, and the API reads them.

This module is the one place both sides go through, so the writer and
the reader cannot disagree about a table. It holds what was measured,
never a name or a position: the API joins `node` for those when it reads
(the #351 rule), so a renamed or moved node reads correctly at once.

**Never stale for long.** A stored answer older than three of its build
intervals is not used, and the API computes the view live, as it did
before. So a jobs service that stopped, or a window nobody builds, costs
speed and never correctness.

**Live views are not here.** The map's live layers, the firehose, chat and
the RF waterfall always read the raw rows.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import delete, func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from sonoran.config import Settings, get_settings
from sonoran.db.models import (
    BroadcastNode,
    BroadcastRun,
    ChannelNode,
    ChannelNodesRun,
    LinkEvidenceLink,
    LinkEvidenceNode,
    LinkEvidenceRun,
)

if TYPE_CHECKING:
    from sonoran.api.routes.graph import Edge
    from sonoran.api.routes.stats import BroadcastRanking

#: The windows the graph page offers (6 h, 24 h, 3 days, 7 days).
GRAPH_HOURS: tuple[int, ...] = (6, 24, 72, 168)
#: The longest-link board's windows: its own default (72 h) and the
#: Statistics page's quick ranges.
BOARD_HOURS: tuple[int, ...] = (24, 72, 168, 720)
#: The Statistics page's quick ranges, for the broadcast rates.
BROADCAST_HOURS: tuple[int, ...] = (24, 168, 720)
#: The coverage page's node list.
CHANNEL_NODE_HOURS: tuple[int, ...] = (168,)
#: From this many hours a window is "long", and built less often.
LONG_HOURS = 720

#: The channel key of a build that covers every channel together.
EVERY_CHANNEL = ""


def build_interval(hours: int, settings: Settings | None = None) -> timedelta:
    """How often a window of `hours` is built."""
    settings = settings or get_settings()
    minutes = max(settings.read_models_interval_minutes, 1)
    if hours >= LONG_HOURS:
        minutes *= max(settings.read_models_long_every, 1)
    return timedelta(minutes=minutes)


def is_fresh(built_at: datetime, hours: int, settings: Settings | None = None) -> bool:
    """True while a build is young enough to serve.

    Three build intervals: one missed run, or a slow one, does not send
    every reader to the live computation, and a stopped jobs service is
    noticed within the half hour.
    """
    settings = settings or get_settings()
    if not settings.read_models_enabled:
        return False
    return datetime.now(UTC) - built_at <= 3 * build_interval(hours, settings)


async def _lock(session: AsyncSession, *key: object) -> None:
    """Take the write lock of one build until the transaction ends.

    Two jobs processes can run at once for a moment, during a deploy.
    Delete-then-insert by both would insert the same key twice and fail;
    with the lock the second waits, then deletes the first one's build.
    """
    name = "read_model:" + ":".join(str(part) for part in key)
    await session.execute(select(func.pg_advisory_xact_lock(func.hashtext(name))))


# --- link evidence (graph and longest-link board) -------------------


@dataclass
class StoredLinks:
    """One build of link evidence, as the graph and the board read it."""

    built_at: datetime
    window_start: datetime
    window_end: datetime
    #: Ranked as the graph ranks them: most reports first.
    edges: list["Edge"]
    #: Each node's packets in the window, for the nodes of the edges.
    counts: dict[int, int]


def rank_edges(edges: Iterable["Edge"]) -> list["Edge"]:
    """Most reports first. Equal counts keep the lower node numbers first.

    The tie-break makes the order the same for a stored build and a live
    computation, so the same links survive a row limit either way.
    """
    return sorted(
        edges, key=lambda edge: (-(edge.forward + edge.backward), edge.source, edge.target)
    )


async def write_links(
    session: AsyncSession,
    channel: str,
    hours: int,
    window_start: datetime,
    window_end: datetime,
    edges: Iterable["Edge"],
    counts: dict[int, int],
) -> None:
    """Replace one build of link evidence, and commit."""
    edges = list(edges)
    await _lock(session, "links", channel, hours)
    await session.execute(
        delete(LinkEvidenceRun).where(
            LinkEvidenceRun.channel == channel, LinkEvidenceRun.hours == hours
        )
    )
    await session.execute(
        insert(LinkEvidenceRun).values(
            channel=channel,
            hours=hours,
            built_at=datetime.now(UTC),
            window_start=window_start,
            window_end=window_end,
        )
    )
    links = [
        {
            "channel": channel,
            "hours": hours,
            "source": edge.source,
            "target": edge.target,
            "kind": edge.kind,
            "kinds": sorted(edge.kinds),
            "snr": edge.snr,
            "count": edge.count,
            "confirmed": edge.confirmed,
            "forward": edge.forward,
            "backward": edge.backward,
            "last_seen": edge.time,
        }
        for edge in edges
    ]
    if links:
        await session.execute(insert(LinkEvidenceLink), links)
    ends = {end for edge in edges for end in (edge.source, edge.target)}
    nodes = [
        {"channel": channel, "hours": hours, "node_num": node, "packet_count": counts[node]}
        for node in sorted(ends)
        if counts.get(node)
    ]
    if nodes:
        await session.execute(insert(LinkEvidenceNode), nodes)
    await session.commit()


async def read_links(
    session: AsyncSession, channel: str, hours: int, settings: Settings | None = None
) -> StoredLinks | None:
    """Return the stored link evidence, or None when there is none fresh."""
    from sonoran.api.routes.graph import Edge

    run = (
        await session.execute(
            select(LinkEvidenceRun).where(
                LinkEvidenceRun.channel == channel, LinkEvidenceRun.hours == hours
            )
        )
    ).scalar_one_or_none()
    if run is None or not is_fresh(run.built_at, hours, settings):
        return None
    rows = (
        await session.execute(
            select(LinkEvidenceLink).where(
                LinkEvidenceLink.channel == channel, LinkEvidenceLink.hours == hours
            )
        )
    ).scalars()
    edges = [
        Edge(
            source=row.source,
            target=row.target,
            kind=row.kind,
            snr=row.snr,
            time=row.last_seen,
            count=row.count,
            confirmed=row.confirmed,
            forward=row.forward,
            backward=row.backward,
            kinds=set(row.kinds),
        )
        for row in rows
    ]
    counts = {
        int(node): int(packets)
        for node, packets in (
            await session.execute(
                select(LinkEvidenceNode.node_num, LinkEvidenceNode.packet_count).where(
                    LinkEvidenceNode.channel == channel, LinkEvidenceNode.hours == hours
                )
            )
        ).all()
    }
    return StoredLinks(
        built_at=run.built_at,
        window_start=run.window_start,
        window_end=run.window_end,
        edges=rank_edges(edges),
        counts=counts,
    )


# --- broadcast rates ------------------------------------------------


@dataclass
class StoredBroadcast:
    """One build of the broadcast rates over a rolling window."""

    built_at: datetime
    window_start: datetime
    window_end: datetime
    ranking: "BroadcastRanking"


async def write_broadcast(
    session: AsyncSession,
    hours: int,
    window_start: datetime,
    window_end: datetime,
    ranking: "BroadcastRanking",
) -> None:
    """Replace one build of the broadcast rates, and commit."""
    await _lock(session, "broadcast", hours)
    await session.execute(delete(BroadcastRun).where(BroadcastRun.hours == hours))
    await session.execute(
        insert(BroadcastRun).values(
            hours=hours,
            built_at=datetime.now(UTC),
            window_start=window_start,
            window_end=window_end,
            notable_count=ranking.notable_count,
            power_loop_count=ranking.power_loop_count,
        )
    )
    rows = [
        {
            "hours": hours,
            "node_num": node,
            "rank": rank,
            "packet_count": packets,
            "notable": notable,
            "faster_than_default": faster,
            "families": families,
            "health": health,
        }
        for rank, (node, packets, notable, faster, families, health) in enumerate(ranking.nodes)
    ]
    if rows:
        await session.execute(insert(BroadcastNode), rows)
    await session.commit()


async def read_broadcast(
    session: AsyncSession, hours: int, settings: Settings | None = None
) -> StoredBroadcast | None:
    """Return the stored broadcast rates, or None when there are none fresh."""
    from sonoran.api.routes.stats import BroadcastRanking

    run = (
        await session.execute(select(BroadcastRun).where(BroadcastRun.hours == hours))
    ).scalar_one_or_none()
    if run is None or not is_fresh(run.built_at, hours, settings):
        return None
    rows = (
        await session.execute(
            select(BroadcastNode).where(BroadcastNode.hours == hours).order_by(BroadcastNode.rank)
        )
    ).scalars()
    nodes: list[Any] = [
        (
            row.node_num,
            row.packet_count,
            list(row.notable),
            list(row.faster_than_default),
            row.families,
            row.health,
        )
        for row in rows
    ]
    return StoredBroadcast(
        built_at=run.built_at,
        window_start=run.window_start,
        window_end=run.window_end,
        ranking=BroadcastRanking(
            nodes=nodes,
            notable_count=run.notable_count,
            power_loop_count=run.power_loop_count,
        ),
    )


# --- nodes heard on a channel ---------------------------------------


async def write_channel_nodes(
    session: AsyncSession, channel: str, hours: int, nodes: Iterable[int]
) -> None:
    """Replace one build of the nodes heard on a channel, and commit."""
    await _lock(session, "channel_nodes", channel, hours)
    await session.execute(
        delete(ChannelNodesRun).where(
            ChannelNodesRun.channel == channel, ChannelNodesRun.hours == hours
        )
    )
    await session.execute(
        insert(ChannelNodesRun).values(channel=channel, hours=hours, built_at=datetime.now(UTC))
    )
    rows = [{"channel": channel, "hours": hours, "node_num": node} for node in sorted(set(nodes))]
    if rows:
        await session.execute(insert(ChannelNode), rows)
    await session.commit()


async def has_channel_nodes(
    session: AsyncSession, channel: str, hours: int, settings: Settings | None = None
) -> bool:
    """True when a fresh build of the channel's nodes is stored."""
    built_at = await session.scalar(
        select(ChannelNodesRun.built_at).where(
            ChannelNodesRun.channel == channel, ChannelNodesRun.hours == hours
        )
    )
    return built_at is not None and is_fresh(built_at, hours, settings)


def channel_nodes(channel: str, hours: int) -> Any:
    """A query for the stored nodes of a channel, for an `IN (...)`."""
    return select(ChannelNode.node_num).where(
        ChannelNode.channel == channel, ChannelNode.hours == hours
    )
