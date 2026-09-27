"""Read-only mesh graph endpoints.

The graph page draws the nodes of one channel and the links between
them. A link comes from a neighbor report or from a traceroute hop. The
response is ready to draw. The browser does no join.

One graph holds one channel. A LoRa modem preset is a different radio
configuration, so a node on LongFast cannot hear a node on MediumFast.
Drawing them together would show links that cannot exist.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import cast

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import and_, func, or_, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from sonoran.api.cache import KeyedCache
from sonoran.api.channels import CORE_TIER, UNKNOWN_CHANNEL, channel_filter, classify
from sonoran.api.dependencies import get_session, require_node_num
from sonoran.api.names import BROADCAST_NODE_NUM, format_node_id, name_of, resolve_names
from sonoran.api.traces import (
    SNR_SCALE,
    UNKNOWN_SNR,
    TraceRow,
    evidenced_hops,
    forward_path,
    is_reply,
    return_path,
)
from sonoran.db.models import NeighborMetrics, Node, Packet, PacketSeen, Traceroute
from sonoran.positions import clean

router = APIRouter(prefix="/api/graph", tags=["graph"])

NEIGHBOR_KIND = "neighbor"
TRACEROUTE_KIND = "traceroute"

# How much evidence a link needs before the graph trusts it. See #73.
#
# How many of a link's reports the link page lists. The COUNT it shows
# is of the whole window; this only bounds the list.
LINK_REPORTS_SHOWN = 50

# Below MIN_SAMPLES_TO_JUDGE reports in total, the graph says nothing
# about a link: it happened, and there is too little evidence to call it
# anything. Past that a link is two-way when packets crossed it at least
# TWO_WAY_MIN_SAMPLES times in each direction, and one-way when one
# direction falls short of that.
#
# That first state used to be called WEAK, and calling it that was the
# defect in #149 -- #87 mirrored. There, `unknown` was rendered as a
# shade of `ok` and a node nothing had heard read Good. Here the same
# confusion ran the other way: a link seen twice was reported as a
# property of the LINK ("Weak link: few packets crossed it") when it is
# a property of our EVIDENCE. The legend said so outright -- "Weak:
# under 10 packets seen" -- while the label called the link weak.
#
# It is not a rare corner. Measured against the deployed instance:
# 90.0% of links at 24 h, 97.0% at 6 h. Two thousand links told every
# reader the mesh was worse than anybody knows it to be.
# The graph pages ask for at most 7 days, and so does this API.
#
# The ceiling was 720 h while the only selector that drives these three
# endpoints offers 6 h, 24 h, 3 days and 7 days. Measured against the
# deployed instance, the cost is driven by the window and barely at all
# by the row limit:
#
#     hours=24  limit=2000    1.7 s
#     hours=168 limit=2000    3.3 s
#     hours=168 limit=10000   4.0 s
#     hours=720 limit=2000    9.2 s
#     hours=720 limit=10000  10.1 s
#
# So 720 h bought nothing any page could ask for and left a ten-second
# anonymous request on a one-core box. This is a deliberate narrowing of
# a public surface: a caller who hand-wrote `hours=720` now gets a 422
# rather than a slow answer. A 30-day graph is a feature with a
# different shape -- prepared, not computed while somebody waits -- not
# a query parameter.
#
# BUT NOT BY RETURNING 422. This is a public endpoint on a community
# deployment, and somebody's script with `hours=720` in it is not doing
# anything wrong -- it was inside the documented range yesterday.
# Breaking it to protect our own box is the wrong trade when a softer
# one exists.
#
# So the parameter still ACCEPTS up to 720 and the window is clamped to
# 168 inside, and the response says so: `window_hours` already carries
# the window actually used, and `window_clamped` names the one that was
# asked for. An existing caller keeps getting data -- a narrower slice
# than it asked for -- and can see that it did.
GRAPH_MAX_HOURS = 168
GRAPH_CEILING_HOURS = 720


def clamp_hours(hours: int) -> tuple[int, int | None]:
    """Return the window to use, and the one asked for if it was cut."""
    if hours <= GRAPH_MAX_HOURS:
        return hours, None
    return GRAPH_MAX_HOURS, hours


# NOT scaled by the window, and #149 asked whether it should be.
#
# The complaint is real: a fixed count means the label partly reports
# the window the reader chose. Measured on the deployed instance, with
# the threshold fixed at 10, the share of links with too little
# evidence falls as the window widens --
#
#     6 h    97.0%        24 h    90.0%        168 h    69.5%
#
# -- so the same link changes category by changing the selector.
#
# The obvious fix is to make the threshold a RATE: ten reports per
# 24 hours, scaled. **Measured, that is worse.** Same instance, same
# links, threshold scaled to 3 / 10 / 70:
#
#     6 h    79.4%        24 h    90.0%        168 h    96.4%
#
# It does not remove the window dependence, it inverts it and widens
# the spread from 27 points to 17 in the other direction. The reason is
# that the link POPULATION grows with the window too -- 1,219 links at
# 6 h against 4,964 at 168 h, and most of what the longer window adds
# is links seen once in a week. Demanding proportionally more evidence
# from a population that got proportionally sparser moves the number
# without fixing the meaning.
#
# So the threshold stays fixed and honest about being fixed. Making it
# window-invariant needs a different definition of a link's strength --
# something per unit time, or a confidence rather than a count -- which
# is a product decision recorded on #149, not a constant to retune.
MIN_SAMPLES_TO_JUDGE = 10
TWO_WAY_MIN_SAMPLES = 3

# Too little evidence to say anything. Named for what it is rather than
# for what a reader might assume -- see #149 and the note above.
UNKNOWN = "unknown"
ONE_WAY = "one_way"
TWO_WAY = "two_way"

__all__ = ["SNR_SCALE", "UNKNOWN_SNR", "router"]


@dataclass
class Edge:
    """One link between two nodes.

    `source` and `target` give the direction the first report saw the
    packet travel: `target` heard `source`. Later reports can run
    either way, and `forward` and `backward` count them, from the
    point of view of the first.

    A neighbor report and a traceroute hop are the same kind of
    evidence, one packet heard across the link, so they count alike.
    Neither outranks the other (#73).
    """

    source: int
    target: int
    kind: str
    snr: float | None
    time: datetime
    count: int = 1
    # Whether anything that completed evidences this link. A neighbor
    # report always does: a node names a neighbour it hears itself. A
    # traceroute does when it is a reply, because the request reached
    # the far end and came back.
    #
    # A request that was never answered is the other case. The broker
    # saw it in flight, so the hops it had already made are real and
    # measured. Nothing confirmed the round trip, so the evidence runs
    # one way. Such links are true but weaker, and a page may want to
    # tell them apart.
    confirmed: bool = True
    forward: int = 1
    backward: int = 0
    kinds: set[str] = field(default_factory=set)
    # Every SNR measured on this link in the window, so `snr` can be a
    # summary rather than whichever hop happened to be measured last.
    # See `snr_summary` below for why that mattered.
    samples: list[float] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.kinds.add(self.kind)
        if self.snr is not None:
            self.samples.append(self.snr)

    @property
    def snr_summary(self) -> float | None:
        """The link's SNR: the MEDIAN of what was measured, not the newest.

        This used to be the newest reading, and every other one was
        thrown away. On one real link that meant the graph reported
        **-6.75 dB** while the fifty samples behind it ran from -16.0
        to -0.25, with the next four at -12.75, -13.0, -8.75 and -5.0.
        The number a reader saw was whichever hop happened to be
        measured last.

        The median rather than the mean or the maximum:

        * The MEAN is dragged by the outliers that a shared radio
          channel produces constantly -- one hop through a temporary
          obstruction, one burst of interference.
        * The MAXIMUM is what `/api/graph/link` reports as `best_snr`,
          and it answers a different question: how good can this link
          get. For "how good is this link", the best case of fifty is
          optimistic by construction.
        * The MEDIAN is the typical condition, and it is what somebody
          deciding whether a link carries actually wants.

        `best_snr` on the per-link endpoint is unchanged and still a
        maximum. The two now differ deliberately, and each says which
        it is.

        **How much this actually moves, measured rather than assumed.**
        18 real links with 10 or more readings, newest against median:

            12 of 18   differ by 0.5 dB or less
             4 of 18   differ by 1.75 to 4.50 dB
             max       4.50 dB

        So the typical correction is small, and the case that prompted
        this -- one link reading -6.75 dB against a -16.0 to -0.25
        spread -- is the tail rather than the rule. It is still worth
        doing: 3 dB is the difference between a link that carries and
        one that does not, four links in eighteen move by more than
        that or close to it, and a median cannot be moved at all by
        which hop happened to be measured last. But nobody should
        expect the graph to look different.
        """
        if not self.samples:
            return None
        ordered = sorted(self.samples)
        middle = len(ordered) // 2
        if len(ordered) % 2:
            return ordered[middle]
        return (ordered[middle - 1] + ordered[middle]) / 2

    @property
    def strength(self) -> str:
        """Return how well the evidence supports this link."""
        if self.forward + self.backward < MIN_SAMPLES_TO_JUDGE:
            return UNKNOWN
        if min(self.forward, self.backward) < TWO_WAY_MIN_SAMPLES:
            return ONE_WAY
        return TWO_WAY

    def as_json(self) -> dict[str, object]:
        """Return the public form of this link."""
        return {
            "source": format_node_id(self.source),
            "target": format_node_id(self.target),
            "kind": self.kind,
            "snr": self.snr_summary,
            "count": self.count,
            "confirmed": self.confirmed,
            "kinds": sorted(self.kinds),
            "each_way": [self.forward, self.backward],
            "strength": self.strength,
            "time": self.time,
        }


EdgeMap = dict[tuple[int, int], Edge]


def _key(a: int, b: int) -> tuple[int, int]:
    """Return one key for a link, in either direction."""
    return (a, b) if a <= b else (b, a)


def _is_node(value: int) -> bool:
    """Return true when a value names a real node.

    The broadcast address is a destination, not a radio. A traceroute
    addressed to everyone would otherwise draw a node called Everyone
    that every path connects to.
    """
    return bool(value) and value != BROADCAST_NODE_NUM


def _add(edges: EdgeMap, edge: Edge) -> None:
    """Add a link, or count one more sighting of a known link.

    A measured SNR always beats no SNR. Many reports carry no value for
    the last hop, so keeping only the first report would leave a link
    unmeasured even when a later report measured it. Between two
    measured values the newer one wins.

    Confirmation works the same way round. One report that completed is
    enough, so a link seen first by an unanswered request and later by a
    reply counts as confirmed.
    """
    if not (_is_node(edge.source) and _is_node(edge.target)):
        return
    key = _key(edge.source, edge.target)
    known = edges.get(key)
    if known is None:
        edges[key] = edge
        return
    known.count += 1
    if edge.source == known.source:
        known.forward += 1
    else:
        known.backward += 1
    known.kinds.add(edge.kind)
    known.confirmed = known.confirmed or edge.confirmed
    if edge.snr is not None:
        known.samples.append(edge.snr)
    # Kept in step with the summary so there is no second, staler
    # answer to "what is this link's SNR". The existing tests read
    # `.snr` directly and are right to -- one value, one meaning.
    known.snr = known.snr_summary
    known.time = max(known.time, edge.time)


def _merge(edges: EdgeMap, edge: Edge) -> None:
    """Fold one already counted link into another map of links."""
    if not (_is_node(edge.source) and _is_node(edge.target)):
        return
    key = _key(edge.source, edge.target)
    known = edges.get(key)
    if known is None:
        edges[key] = edge
        return
    same = edge.source == known.source
    known.count += edge.count
    known.forward += edge.forward if same else edge.backward
    known.backward += edge.backward if same else edge.forward
    known.kinds |= edge.kinds
    known.confirmed = known.confirmed or edge.confirmed
    known.samples.extend(edge.samples)
    known.snr = known.snr_summary
    known.time = max(known.time, edge.time)


async def _neighbor_edges(
    session: AsyncSession, since: datetime, channel: str | None, until: datetime | None = None
) -> EdgeMap:
    """Return the links that recent neighbor reports show on one channel.

    A node names the neighbours it hears, so the packet each report
    measures travelled from the neighbour to the node that reports it.
    `until` ends the window before now, for the Statistics range (#294).
    """
    # The whole window, not a page of it. See `mesh_graph` for why.
    statement = select(NeighborMetrics).where(
        NeighborMetrics.time >= since, channel_filter(NeighborMetrics.channel, channel)
    )
    if until is not None:
        statement = statement.where(NeighborMetrics.time < until)
    rows = (await session.scalars(statement)).all()
    edges: EdgeMap = {}
    for row in rows:
        if row.node_num == row.neighbor_node_num:
            continue
        _add(
            edges,
            Edge(
                source=row.neighbor_node_num,
                target=row.node_num,
                kind=NEIGHBOR_KIND,
                snr=row.snr,
                time=row.time,
            ),
        )
    return edges


def _trace_links(row: TraceRow) -> list[tuple[int, int, float | None, int, int]]:
    """Return the links one traceroute proves.

    Each item holds the two ends, the reading, the position of the hop,
    and how many hops the whole path claims.

    A reply carries its way back as well, and each hop of it is a packet
    heard in the other direction. Those follow the outward hops, with
    their own positions along the return path.

    The graph and the link page both read a row through this one
    function. They used to hold a copy each, and the copies disagreed:
    the graph drew links that the link page could then find no evidence
    for. See `sonoran.api.traces` for the three rules that apply.
    """
    links: list[tuple[int, int, float | None, int, int]] = []
    for path, readings in (
        (forward_path(row), row.snr_towards),
        (return_path(row), row.snr_back),
    ):
        if len(path) < 2:
            continue
        hops, _ = evidenced_hops(path, list(readings or []))
        claimed = len(path) - 1
        links.extend(
            (source, target, snr, index + 1, claimed)
            for index, (source, target, snr) in enumerate(hops)
            if source != target
        )
    return links


async def _traceroute_edges(
    session: AsyncSession, since: datetime, channel: str | None, until: datetime | None = None
) -> EdgeMap:
    """Return the links that recent traceroutes show.

    There is one link between each pair of hops that follow each other,
    for as far along the path as the report reached. `until` ends the
    window before now, for the Statistics range (#294).
    """
    # The whole window, not a page of it. See `mesh_graph` for why.
    statement = select(Traceroute).where(
        Traceroute.seen_at >= since, channel_filter(Traceroute.channel, channel)
    )
    if until is not None:
        statement = statement.where(Traceroute.seen_at < until)
    rows = (await session.scalars(statement)).all()
    edges: EdgeMap = {}
    for row in rows:
        confirmed = is_reply(row)
        for source, target, snr, _position, _claimed in _trace_links(row):
            _add(
                edges,
                Edge(
                    source=source,
                    target=target,
                    kind=TRACEROUTE_KIND,
                    snr=snr,
                    time=row.seen_at,
                    confirmed=confirmed,
                ),
            )
    return edges


async def _packet_counts(session: AsyncSession, since: datetime) -> dict[int, int]:
    """Return the packet count of each node in the window."""
    rows = await session.execute(
        select(Packet.from_node_num, func.count().label("count"))
        .where(Packet.first_seen_at >= since)
        .group_by(Packet.from_node_num)
    )
    return {node_num: count for node_num, count in rows.all()}


def _node_json(
    node_num: int,
    node: Node | None,
    name: str,
    packet_count: int,
) -> dict[str, object]:
    """Return the public form of one graph node.

    The position comes with it so the page can lay the graph out over
    the ground it really sits on. A mesh is a geographic thing: the two
    clusters a reader picks out of the web are Phoenix and Tucson, and
    a layout that starts from nowhere hides that. Only about six nodes
    in ten report a position, so a client has to seed the rest itself.
    """
    lat, lon = clean(
        None if node is None else node.last_lat,
        None if node is None else node.last_lon,
    )
    return {
        "node_id": format_node_id(node_num),
        "node_num": node_num,
        "display_name": name,
        "short_name": None if node is None else node.short_name,
        "role": None if node is None else node.role,
        "hw_model": None if node is None else node.hw_model,
        "is_mqtt_gateway": bool(node is not None and node.is_mqtt_gateway),
        "lat": lat,
        "lon": lon,
        "has_position": lat is not None,
        "last_heard": None if node is None else node.last_heard,
        "packet_count": packet_count,
        "known": node is not None,
    }


async def _channel_link_counts(session: AsyncSession, since: datetime) -> dict[str | None, int]:
    """Return how many link reports each channel has in the window."""
    counts: dict[str | None, int] = {}
    neighbor_rows = await session.execute(
        select(NeighborMetrics.channel, func.count().label("total"))
        .where(NeighborMetrics.time >= since)
        .group_by(NeighborMetrics.channel)
    )
    traceroute_rows = await session.execute(
        select(Traceroute.channel, func.count().label("total"))
        .where(Traceroute.seen_at >= since)
        .group_by(Traceroute.channel)
    )
    for rows in (neighbor_rows, traceroute_rows):
        for channel, total in rows.all():
            counts[channel] = counts.get(channel, 0) + total
    return counts


async def _channel_packet_counts(session: AsyncSession, since: datetime) -> dict[str | None, int]:
    """Return how many observations each channel has in the window.

    A channel can carry plenty of traffic and still evidence no link: a
    chat or weather channel produces no neighbor report and no
    traceroute. Counting packets as well means such a channel still
    appears in the pickers, so the live traffic layer can be pointed at
    it.
    """
    rows = await session.execute(
        select(PacketSeen.channel, func.count().label("total"))
        .where(PacketSeen.seen_at >= since)
        .group_by(PacketSeen.channel)
    )
    return {channel: total for channel, total in rows.all()}


@router.get("/channels")
async def graph_channels(
    request: Request,
    hours: int = Query(default=24, ge=1, le=GRAPH_CEILING_HOURS),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    """Return every channel that has mesh links in the window.

    The graph page draws one graph for each of these channels. The
    busiest channel comes first, so the page can select it by default.

    Each channel carries a `tier`. A `core` channel is a modem preset or
    one of the channels this deployment claims as its own; everything
    else is `extra`. The pickers show the two apart, so the mesh proper
    is not buried among the special interest channels.

    Core channels sort before extra ones, so the default selection is
    always a channel the mesh really runs on.

    Links with no channel always sort last, whatever their count. They
    are not a real channel. They were stored before revision 0007 added
    the column, so one graph of them mixes every preset together. A
    large backlog of them must never become the default tab.
    """
    hours, clamped = clamp_hours(hours)
    since = datetime.now(UTC) - timedelta(hours=hours)
    links = await _channel_link_counts(session, since)
    packets = await _channel_packet_counts(session, since)
    core = tuple(request.app.state.settings.core_channels)

    ordered = sorted(
        set(links) | set(packets),
        key=lambda name: (
            name is None,
            classify(name, core)["tier"] != CORE_TIER,
            -(links.get(name, 0) + packets.get(name, 0)),
        ),
    )
    channels: list[dict[str, object]] = []
    for name in ordered:
        record: dict[str, object] = dict(classify(name, core))
        if not name:
            record["channel"] = UNKNOWN_CHANNEL
            record["label"] = "Before channel tracking"
            record["group"] = "Unknown"
            record["mixed_presets"] = True
        channels.append(
            record
            | {
                "link_report_count": links.get(name, 0),
                "packet_count": packets.get(name, 0),
            }
        )
    body: dict[str, object] = {"window_hours": hours, "channels": channels}
    return body | {"window_clamped": clamped} if clamped else body


def _mentions(node: int) -> ColumnElement[bool]:
    """Return the filter that selects the traceroutes naming one node.

    A node appears as an end of the trace or as a hop inside its route,
    either way: a reply's way back is evidence too (#73).

    This filter has to exist. Without it the query took the newest rows
    and hoped the link was among them, while the graph read four times
    as many. A mesh that logs two thousand traceroutes a day then drew
    plenty of links whose evidence lay outside the smaller window, and
    clicking one showed an empty page. Selecting by node instead of by
    recency means the row limit can no longer hide a link from itself.
    """
    return or_(
        Traceroute.from_node_num == node,
        Traceroute.to_node_num == node,
        Traceroute.route.cast(JSONB).contains([node]),
        Traceroute.route_back.cast(JSONB).contains([node]),
    )


async def _link_reports(
    session: AsyncSession, a: int, b: int, since: datetime, channel: str | None
) -> list[dict[str, object]]:
    """Return the reports that evidence one link, newest first.

    A neighbor report names both nodes directly. A traceroute evidences
    a link when the two nodes follow each other in its path.
    """
    neighbours = (
        await session.scalars(
            select(NeighborMetrics)
            .where(
                NeighborMetrics.time >= since,
                channel_filter(NeighborMetrics.channel, channel),
                or_(
                    and_(NeighborMetrics.node_num == a, NeighborMetrics.neighbor_node_num == b),
                    and_(NeighborMetrics.node_num == b, NeighborMetrics.neighbor_node_num == a),
                ),
            )
            .order_by(NeighborMetrics.time.desc())
            .limit(50)
        )
    ).all()

    reports: list[dict[str, object]] = [
        {
            "kind": NEIGHBOR_KIND,
            "reported_by": format_node_id(row.node_num),
            "packet_id": row.packet_id,
            "channel": row.channel,
            "snr": row.snr,
            "time": row.time,
        }
        for row in neighbours
    ]

    traces = (
        await session.scalars(
            select(Traceroute)
            .where(
                Traceroute.seen_at >= since,
                channel_filter(Traceroute.channel, channel),
                _mentions(a),
                _mentions(b),
            )
            .order_by(Traceroute.seen_at.desc())
            .limit(500)
        )
    ).all()
    for row in traces:
        for source, target, snr, position, claimed in _trace_links(row):
            if {source, target} != {a, b}:
                continue
            reports.append(
                {
                    "kind": TRACEROUTE_KIND,
                    "reported_by": format_node_id(row.from_node_num),
                    "packet_id": row.packet_id,
                    "channel": row.channel,
                    "snr": snr,
                    "hop": position,
                    "path_length": claimed,
                    "time": row.seen_at,
                }
            )
    reports.sort(key=lambda item: cast(datetime, item["time"]), reverse=True)
    return reports


@router.get("/link")
async def graph_link(
    a: str,
    b: str,
    hours: int = Query(default=24, ge=1, le=GRAPH_CEILING_HOURS),
    channel: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    """Return the evidence behind one link on the graph.

    Every report names the packet that carried it, so the packet itself
    can be opened from here.
    """
    first, second = require_node_num(a), require_node_num(b)
    hours, clamped = clamp_hours(hours)
    since = datetime.now(UTC) - timedelta(hours=hours)
    reports = await _link_reports(session, first, second, since, channel)
    # The whole window is counted and measured; only the list is cut.
    shown = reports[:LINK_REPORTS_SHOWN]
    names = await resolve_names(session, (first, second))
    measured = [
        value
        for report in reports
        if isinstance(value := report["snr"], int | float) and not isinstance(value, bool)
    ]
    return {
        "a": {"node_id": format_node_id(first), "display_name": name_of(names, first)},
        "b": {"node_id": format_node_id(second), "display_name": name_of(names, second)},
        "window_hours": hours,
        **({"window_clamped": clamped} if clamped else {}),
        # The count is of the window; the list is the newest slice of it.
        #
        # This used to report `len(reports)` AFTER the list had been cut
        # to 50, so a link with 71 reports told the reader it had 50 --
        # and the graph edge for the same window and channel said 71.
        # Somebody clicking a link to check a number got a different
        # number. `best_snr` was a maximum over the truncated 50 too.
        "report_count": len(reports),
        "reports_shown": len(shown),
        "best_snr": max(measured) if measured else None,
        "reports": shown,
    }


# One hold per (hours, limit, channel), with a ceiling on how many.
#
# The graph page costs 1.7 s at its default and 4.0 s at its widest, and
# every reader who opens it pays that again. The hold collapses repeat
# loads; the single-flight lock inside it collapses the more expensive
# case, which is several readers opening the same page in the same
# second on a one-core box.
#
# `KeyedCache` rather than a dict of `TimedCache`, because the key is
# built from the query string: an unbounded dict here is the #160 bug in
# the one place whose job is to protect the box. 64 entries covers every
# combination the selector can produce (4 windows x the channels on this
# mesh) many times over.
_graph_cache: KeyedCache[dict[str, object]] = KeyedCache(capacity=64)


@router.get("")
async def mesh_graph(
    request: Request,
    hours: int = Query(default=24, ge=1, le=GRAPH_CEILING_HOURS),
    limit: int = Query(default=2000, ge=1, le=10000),
    channel: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    """Return the mesh of one channel as nodes and links.

    Neighbor reports and traceroute hops between the same two nodes add
    up to one link. Each link says how strong its evidence is: `weak`
    with few reports at all, `one_way` when packets crossed it mostly in
    one direction, and `two_way` when they crossed it both ways.

    The `channel` parameter selects the preset. Without it the response
    holds every channel together. Nodes of different presets cannot hear
    each other, so a page must ask for one channel at a time.
    """
    # Every parameter that changes the answer is in the key.
    #
    # A key that misses one serves a different question's answer, which
    # is the worst thing a cache can do and the quietest --
    # `test_graph_cache_key.py` builds this key by reading the
    # signature, so a parameter added later fails a test instead of
    # being silently ignored.
    hours, clamped = clamp_hours(hours)
    key = graph_cache_key(hours=hours, limit=limit, channel=channel)
    body = await _graph_cache.get(
        key,
        request.app.state.settings.stats_cache_seconds,
        lambda: _mesh_graph(session, hours, limit, channel),
    )
    # Said in the body rather than only in a comment, so a caller that
    # asked for more can tell it did not get it. Not cached with the
    # answer: the same 168 h result serves both a request for 168 and a
    # clamped request for 720, and only the latter should say so.
    return body | {"window_clamped": clamped} if clamped else body


def graph_cache_key(*, hours: int, limit: int, channel: str | None) -> str:
    """The cache key for one graph request.

    Written out rather than built from `locals()` so that adding a
    parameter to `mesh_graph` without adding it here is a visible
    omission, and so the test that compares the two has something to
    compare.
    """
    return f"{hours}|{limit}|{channel or ''}"


async def _mesh_graph(
    session: AsyncSession, hours: int, limit: int, channel: str | None
) -> dict[str, object]:
    """The work behind `/api/graph`. Cached by its caller."""
    since = datetime.now(UTC) - timedelta(hours=hours)
    edges = await _traceroute_edges(session, since, channel)
    for edge in (await _neighbor_edges(session, since, channel)).values():
        _merge(edges, edge)

    # The limit picks which links are DRAWN. It does not decide what
    # the evidence was.
    #
    # It used to cut the rows before they were counted, so `strength`
    # and `each_way` described whatever survived truncation. Measured
    # on a 24 h MediumFast window, the default of 2000 discarded 38% of
    # the neighbour rows and 32% of the traceroute rows, and 103 of
    # 1776 shared links changed strength when it was raised -- 53 of
    # them from `weak`, which the page draws dotted and calls "too
    # rarely to say it is usable", to `two_way`. AGENTS.md 9.19:
    # a row limit must never decide what evidence exists.
    #
    # Reading the whole window is affordable. Measured on production:
    # 4 ms at the 24 h default, 24 ms at 168 h, 201 ms at the 720 h
    # maximum. The cap was not buying speed, it was buying wrong
    # answers.
    #
    # Ranked by evidence so a truncated picture keeps the best attested
    # links, and `links_truncated` says when that happened, because a
    # partial graph that does not admit it is worse than a small one.
    ranked = sorted(edges.values(), key=lambda edge: edge.forward + edge.backward, reverse=True)
    truncated = len(ranked) > limit
    shown = ranked[:limit]

    node_nums: set[int] = set()
    for edge in shown:
        node_nums.update((edge.source, edge.target))

    rows = (await session.scalars(select(Node).where(Node.node_num.in_(node_nums)))).all()
    known = {row.node_num: row for row in rows}
    names = await resolve_names(session, node_nums)
    counts = await _packet_counts(session, since)

    nodes = [
        _node_json(num, known.get(num), name_of(names, num), counts.get(num, 0))
        for num in sorted(node_nums)
    ]
    links = [edge.as_json() for edge in shown]
    return {
        "window_hours": hours,
        "channel": channel,
        "node_count": len(nodes),
        "link_count": len(links),
        # What was measured, against what is drawn.
        "links_found": len(ranked),
        "links_truncated": truncated,
        "nodes": nodes,
        "links": links,
    }
