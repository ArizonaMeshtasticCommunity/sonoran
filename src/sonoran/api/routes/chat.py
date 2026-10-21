"""Read-only chat endpoints."""

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import ColumnElement, Select, and_, any_, case, func, literal, select, tuple_
from sqlalchemy.dialects.postgresql import array
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from sonoran.api.channels import classify, group_order
from sonoran.api.dependencies import (
    LIKE_ESCAPE,
    contains,
    get_session,
    require_node_num,
)
from sonoran.api.names import format_node_id, name_of, resolve_names
from sonoran.api.preset_scope import Presets, preset_filter, require_presets
from sonoran.db.models import Packet, PacketSeen, TextMessage
from sonoran.radio.presets import PRESETS

router = APIRouter(prefix="/api/chat", tags=["chat"])

# The channel names that name a preset. An untagged message on any other
# channel is read as the deployment's default preset (#313).
PRESET_NAMES = [preset.name for preset in PRESETS]

# The tag of the weekly mesh network check-in.
DEFAULT_TAG = "meshnet"
_TAG = re.compile(r"^[A-Za-z0-9_]{1,32}$")


def _require_tag(value: str) -> str:
    """Return a safe hashtag word, without the leading hash sign."""
    tag = value.lstrip("#")
    if not _TAG.match(tag):
        raise HTTPException(status_code=422, detail="invalid tag")
    return tag


@dataclass
class Reaction:
    """One emoji on one message, with everyone who sent it.

    Each sender keeps its own packet, so a tapback can be opened and
    read like any other packet.
    """

    emoji: str
    last_seen: datetime
    senders: list[dict[str, object]] = field(default_factory=list)

    def as_json(self) -> dict[str, object]:
        """Return the public form of this reaction."""
        return {
            "emoji": self.emoji,
            "count": len(self.senders),
            "senders": self.senders,
            # The plain name list keeps older callers working.
            "from": [str(sender["display_name"]) for sender in self.senders],
            "last_seen": self.last_seen,
        }


def _week_start(when: datetime) -> datetime:
    """Return the UTC Monday that starts the week of one time."""
    day = when.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    return day - timedelta(days=day.weekday())


_WEEK = timedelta(days=7)

#: How far before the display window the streak read looks.
#:
#: A streak is longer than the window a reader happens to have chosen.
#: Somebody looking at 4 weeks still wants to be told that a node is on
#: a run of 30, so the aggregate reads further back than the page shows.
#:
#: It is a fixed extra rather than "everything", because the read has to
#: be bounded by something and the honest way to bound a claim is to say
#: where the evidence stops. A run that reaches the oldest week this read
#: could see is reported with `streak_at_least`, and the page draws it as
#: "30+ weeks" -- a lower bound, not a measurement.
STREAK_LOOKBACK_WEEKS = 52


#
# --- What a streak is -------------------------------------------------
#
# A streak is a factual claim about somebody's participation, so the
# rules are written here rather than left to be inferred from the
# arithmetic. `docs/design/2026-09-26-ux-overhaul.md` §6.3 is the item;
# its stated risk is that getting this wrong "is worse here than on any
# other page in the brief, because it is about people rather than
# radios."
#
# 1. A **week** is Monday 00:00 UTC to the following Monday 00:00 UTC,
#    exclusive at the end. `_week_start` is the only definition of it in
#    this module, and the aggregate below funnels every row through it
#    rather than trusting SQL's own week arithmetic to agree.
#
# 2. A node **checked in** in week W when at least one stored message of
#    its own, in week W, carries the tag. Two messages in the same week
#    are one check-in: the unit is the week, not the message. Three
#    messages on the Tuesday are a check-in for that week and say
#    nothing whatever about the next one.
#
# 3. A **streak as of week W** is the number of consecutive weeks,
#    ending at W and counting W itself, in which the node checked in. It
#    is only ever reported next to a week the node did check in, so the
#    smallest streak that exists is 1. There is no streak of 0: a node
#    that did not check in has no streak to state, which is a different
#    sentence from a streak of zero and must never be rendered as one.
#
# 4. A **gap** ends a streak. Nothing bridges a missing week -- not a
#    message in the week after, not two messages in the week before.
#    The next check-in begins a new run at 1.
#
# 5. The **current week is in progress**, and this is the case the whole
#    design turns on. Until Monday 00:00 UTC comes round again, the
#    current week has not finished, so:
#
#    - A node that has already checked in this week counts this week.
#      The check-in happened; there is nothing provisional about it.
#    - A node that has NOT yet checked in this week has NOT broken
#      anything. Its run through last week is intact and still open. It
#      is reported as pending, never as broken, and the count is the run
#      through last week -- it is NOT given a speculative extra week for
#      a check-in that has not happened.
#
#    So an in-progress week neither breaks a streak nor is counted
#    before it is earned. Both halves of that matter: an earlier draft
#    that simply walked back from "this week" reported every single node
#    as having a broken streak every Monday morning.
#
# 6. **Absence is reported as absence, never as a verdict.** A node that
#    checked in last week and not this one is listed, because that is
#    what the page is for, but the field is named for what was observed
#    (`not_seen`) and the page says "no message found". A node may have
#    been off, out of range, or its message may not have been stored.
#
# 7. **Nothing to compute from is not a row of zeroes.** When no tagged
#    message exists in the whole lookback and the ingest is not keeping
#    message bodies at all, `streaks` is null and the page says so. A
#    page that cannot see is not a page reporting silence.
#


def _streak_as_of(weeks: frozenset[datetime], at: datetime, floor: datetime) -> tuple[int, bool]:
    """Return the run of consecutive check-in weeks ending at `at`.

    Rules 3, 4 and 5 above. `floor` is the oldest week the read could
    see; a run that reaches it is a lower bound rather than a
    measurement, which the second element reports.

    Returns `(0, False)` when the node did not check in during `at`,
    because there is no run ending there. Callers only ask about weeks
    the node was present in, and the zero is a programming answer rather
    than something rendered: see rule 3.
    """
    if at not in weeks:
        return (0, False)
    length = 0
    cursor = at
    while cursor in weeks:
        length += 1
        cursor -= _WEEK
    # The walk stopped because `cursor` is absent. If it stepped off the
    # bottom of what was read, the absence is our blindness rather than
    # the node's silence.
    return (length, cursor < floor)


def _check_in_weeks(
    buckets: dict[tuple[int, datetime], dict[str, object]],
) -> dict[int, frozenset[datetime]]:
    """Return, per node, the set of weeks it checked in (rule 2)."""
    weeks: dict[int, set[datetime]] = {}
    for node, week in buckets:
        weeks.setdefault(node, set()).add(week)
    return {node: frozenset(found) for node, found in weeks.items()}


def _streaks_assessed(
    buckets: dict[tuple[int, datetime], dict[str, object]], keeping_text: bool
) -> bool:
    """Whether anything about streaks could be worked out at all (rule 7).

    A separate function because it is the difference between "nobody
    checked in" and "this page cannot see", and those must never be
    allowed to read the same. Message bodies can be switched off at the
    ingest (`store_text_messages`), and with them off there will never be
    a tagged message to find -- so an empty list is a fact about the
    configuration, not about the community.

    Found rows settle it whichever way the setting is now: the evidence
    exists and the runs computed from it are real. The setting only
    decides what an ABSENCE of rows means.
    """
    return bool(buckets) or keeping_text


async def _reactions_for(
    session: AsyncSession, rows: list[TextMessage]
) -> dict[int, list[dict[str, object]]]:
    """Return tapback reactions, grouped by the packet they react to.

    The Meshtastic phone apps send a tapback as a text message with the
    `emoji` flag set and `reply_id` holding the packet ID of the message
    being reacted to. The body is the emoji itself.

    Reactions are grouped by emoji, so three thumbs up read as one chip
    with a count of three rather than three separate rows.
    """
    parents = {row.packet_id for row in rows if row.packet_id is not None}
    if not parents:
        return {}
    reactions = list(
        (
            await session.scalars(
                select(TextMessage)
                .where(TextMessage.emoji.is_(True), TextMessage.reply_id.in_(parents))
                .order_by(TextMessage.seen_at.asc())
            )
        ).all()
    )
    if not reactions:
        return {}
    names = await resolve_names(session, [row.from_node_num for row in reactions])

    grouped: dict[int, dict[str, Reaction]] = {}
    for row in reactions:
        if row.reply_id is None:
            continue
        by_emoji = grouped.setdefault(row.reply_id, {})
        entry = by_emoji.get(row.body)
        if entry is None:
            by_emoji[row.body] = Reaction(emoji=row.body, last_seen=row.seen_at)
            entry = by_emoji[row.body]
        entry.senders.append(
            {
                "node_id": format_node_id(row.from_node_num),
                "display_name": name_of(names, row.from_node_num),
                "packet_id": row.packet_id,
                "seen_at": row.seen_at,
            }
        )
        entry.last_seen = max(entry.last_seen, row.seen_at)
    return {
        parent: [entry.as_json() for entry in items.values()] for parent, items in grouped.items()
    }


async def _reply_parents(
    session: AsyncSession, rows: list[TextMessage]
) -> dict[int, dict[str, object]]:
    """Return the message each reply points at, by packet ID.

    A reply is an ordinary text message that carries `reply_id`. The
    parent may sit outside the requested window, so it is looked up
    directly rather than taken from the page.
    """
    wanted = {row.reply_id for row in rows if row.reply_id is not None and not row.emoji}
    if not wanted:
        return {}
    parents = list(
        (
            await session.scalars(
                select(TextMessage).where(
                    TextMessage.packet_id.in_(wanted), TextMessage.emoji.is_(False)
                )
            )
        ).all()
    )
    names = await resolve_names(session, [row.from_node_num for row in parents])
    return {
        row.packet_id: {
            "packet_id": row.packet_id,
            "from_node": format_node_id(row.from_node_num),
            "from_name": name_of(names, row.from_node_num),
            "body": row.body,
            "seen_at": row.seen_at,
        }
        for row in parents
        if row.packet_id is not None
    }


# How far before the oldest message the observation read looks. A
# gateway stamps nothing we order on, and an upload can land a little
# after the text row, so the bound is loose on purpose. It exists so the
# hypertable read can skip old chunks, not to decide which rows count.
_METRICS_SLACK = timedelta(hours=1)


async def _metrics_for(
    session: AsyncSession, rows: list[TextMessage]
) -> dict[tuple[int, int], dict[str, object]]:
    """Return what the packet record says about how each message travelled.

    Keyed by (`from_node_num`, `packet_id`), the identity of a packet
    (`AGENTS.md` 9.1). Every figure follows the rules in `AGENTS.md`
    9.5 and 9.5.1:

    - `gateway_count` counts distinct gateways, never uploads.
    - A gateway that is the sender uploaded its own voice. It is never
      a direct observation and never counts as a gateway that heard it.
    - A signal reading is offered only from a direct observation. A
      relayed upload's SNR belongs to the last hop, not to the sender.

    `fewest_hops` is the fewest relays any gateway saw the packet use.
    `want_ack` says an acknowledgement was asked for. Whether one came
    back is not recorded, so no field claims it.
    """
    wanted = {(row.from_node_num, row.packet_id) for row in rows if row.packet_id is not None}
    if not wanted:
        return {}
    since = min(row.seen_at for row in rows) - _METRICS_SLACK
    keys = (
        select(
            Packet.from_node_num.label("from_node_num"),
            Packet.packet_id.label("packet_id"),
            func.max(Packet.hop_start).label("hop_start"),
            func.bool_or(Packet.want_ack).label("want_ack"),
        )
        .where(
            tuple_(Packet.from_node_num, Packet.packet_id).in_(sorted(wanted)),
            Packet.first_seen_at >= since,
        )
        .group_by(Packet.from_node_num, Packet.packet_id)
        .cte("chat_keys")
    )
    other = PacketSeen.gateway_node_num != PacketSeen.from_node_num
    direct = and_(other, PacketSeen.hop_limit == keys.c.hop_start)
    statement = (
        select(
            keys.c.from_node_num,
            keys.c.packet_id,
            keys.c.hop_start,
            keys.c.want_ack,
            func.count(func.distinct(PacketSeen.gateway_node_num))
            .filter(other)
            .label("gateway_count"),
            func.count(func.distinct(PacketSeen.gateway_node_num))
            .filter(direct)
            .label("direct_gateways"),
            func.max(PacketSeen.hop_limit).filter(other).label("best_hop_limit"),
            func.max(PacketSeen.rx_snr).filter(direct).label("best_direct_snr"),
            func.max(PacketSeen.rx_rssi).filter(direct).label("best_direct_rssi"),
        )
        .select_from(keys)
        .outerjoin(
            PacketSeen,
            and_(
                PacketSeen.from_node_num == keys.c.from_node_num,
                PacketSeen.packet_id == keys.c.packet_id,
                PacketSeen.seen_at >= since,
            ),
        )
        .group_by(keys.c.from_node_num, keys.c.packet_id, keys.c.hop_start, keys.c.want_ack)
    )
    found: dict[tuple[int, int], dict[str, object]] = {}
    for row in (await session.execute(statement)).all():
        fewest = (
            None
            if row.hop_start is None or row.best_hop_limit is None
            else max(0, int(row.hop_start) - int(row.best_hop_limit))
        )
        found[(int(row.from_node_num), int(row.packet_id))] = {
            "gateway_count": int(row.gateway_count or 0),
            "direct_gateways": int(row.direct_gateways or 0),
            "fewest_hops": fewest,
            "best_direct_snr": None if row.best_direct_snr is None else float(row.best_direct_snr),
            "best_direct_rssi": None if row.best_direct_rssi is None else int(row.best_direct_rssi),
            "want_ack": bool(row.want_ack),
        }
    return found


async def _as_messages(
    session: AsyncSession, rows: list[TextMessage], *, metrics: bool = False
) -> list[dict[str, object]]:
    """Map message rows to the public form, with names resolved.

    Tapback reactions are attached to the message they react to. They
    are not returned as messages of their own, because a lone emoji in
    the timeline carries no meaning.
    """
    names = await resolve_names(
        session, [num for row in rows for num in (row.from_node_num, row.to_node_num)]
    )
    reactions = await _reactions_for(session, rows)
    parents = await _reply_parents(session, rows)
    travelled = await _metrics_for(session, rows) if metrics else {}
    messages: list[dict[str, object]] = []
    for row in rows:
        message: dict[str, object] = {
            "id": row.id,
            "packet_id": row.packet_id,
            "from_node": format_node_id(row.from_node_num),
            "from_name": name_of(names, row.from_node_num),
            "to_node": format_node_id(row.to_node_num),
            "to_name": name_of(names, row.to_node_num),
            "body": row.body,
            "channel": row.channel,
            "seen_at": row.seen_at,
            "reply_id": row.reply_id,
            "emoji": row.emoji,
            "reply_to": None if row.reply_id is None else parents.get(row.reply_id),
            "reactions": [] if row.packet_id is None else reactions.get(row.packet_id, []),
        }
        if metrics:
            # Null when the message has no packet row, which is a fact
            # about the record, not a message that nobody heard.
            message["metrics"] = (
                None if row.packet_id is None else travelled.get((row.from_node_num, row.packet_id))
            )
        messages.append(message)
    return messages


def _on_preset(
    statement: Select[Any],
    preset: Presets | None,
    since: datetime | None,
    default_preset: str,
) -> Select[Any]:
    """Keep the messages carried on one modem preset (#313).

    A message has no preset of its own. Its packet does, so each message
    reads its packet's tag. The read names the packet's partition column
    as well as its natural key: ingest stores the message with the
    packet's own `first_seen_at` as its `seen_at`, so the three columns
    are the whole of `uq_packet_dedup` and find one row at most. A
    message with no packet row, or a packet written before the tag,
    falls back to its topic channel. See `api/preset_scope.py`.

    **An untagged message on a topic channel belongs to the default
    preset.** That is where the chat page put every topic channel before
    #313 (`channelsFor` in `preset.js`). Without this, an old `azmsh` or
    `Weather` message compares `'azmsh' = 'MediumFast'`, and every one of
    them leaves the page on deploy. A channel named after a preset is
    still read as that preset. The names come from `PRESETS`, so a mesh
    on any of the nine presets is covered.

    **A correlated read, never a join.** The same lesson as the count in
    `routes/packets.py`: a join leaves the planner free to hash every
    chunk of `packet` before the LIMIT applies, and `packet` is the
    largest table there is. A correlated read is one probe of the unique
    index for each message the scan reaches, whatever the planner
    thinks of the tables. The feed reads newest first and stops at its
    limit, and the overview reads one week of messages, which is a few
    thousand rows on this mesh.

    `since` is the caller's own lower bound on `seen_at`. Repeated on
    the packet side, it lets each probe skip the older chunks. It drops
    no match, because a match has the same time on both sides.
    """
    if preset is None:
        return statement
    same = [
        Packet.from_node_num == TextMessage.from_node_num,
        Packet.packet_id == TextMessage.packet_id,
        Packet.first_seen_at == TextMessage.seen_at,
    ]
    if since is not None:
        same.append(Packet.first_seen_at >= since)
    tag = select(Packet.modem_preset).where(*same).correlate(TextMessage).scalar_subquery()
    untagged = case(
        (TextMessage.channel == any_(array(PRESET_NAMES)), TextMessage.channel),
        else_=literal(default_preset),
    )
    return statement.where(preset_filter(tag, untagged, preset))


def _apply_filters(
    statement: Select[tuple[TextMessage]],
    channel: str | None,
    from_node: str | None,
    since: datetime | None,
    before: datetime | None,
) -> Select[tuple[TextMessage]]:
    """Apply the documented chat filters to a statement."""
    if channel:
        statement = statement.where(TextMessage.channel == channel)
    if from_node:
        # A malformed node ID is a bad request, not a server fault.
        # `parse_node_id` raises ValueError, which reaches the client as
        # a 500 unless it is caught here.
        statement = statement.where(TextMessage.from_node_num == require_node_num(from_node))
    if since:
        statement = statement.where(TextMessage.seen_at >= since)
    if before:
        statement = statement.where(TextMessage.seen_at < before)
    return statement


@router.get("")
async def chat(
    request: Request,
    channel: str | None = None,
    preset: str | None = None,
    from_node: str | None = Query(default=None, alias="from"),
    q: str | None = None,
    since: datetime | None = None,
    before: datetime | None = None,
    reactions: bool = False,
    metrics: bool = False,
    limit: int = Query(default=100, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, object]]:
    """Return text messages newest first.

    Tapback reactions are attached to the message they react to, so they
    do not appear as messages here. Set `reactions=true` to list them as
    ordinary rows instead.

    Set `metrics=true` to add how each message travelled: gateways that
    heard it, how many heard it direct, the fewest hops, the best direct
    signal, and whether an acknowledgement was asked for. See
    `_metrics_for`.

    Set `preset` to keep the messages carried on one modem preset, or on
    any of several (`preset=MediumFast,LongFast`). It works beside
    `channel`. See `api/preset_scope.py`.
    """
    wanted = require_presets(preset)
    statement = select(TextMessage).order_by(TextMessage.seen_at.desc()).limit(limit)
    statement = _apply_filters(statement, channel, from_node, since, before)
    statement = _on_preset(statement, wanted, since, str(request.app.state.settings.default_preset))
    if not reactions:
        statement = statement.where(TextMessage.emoji.is_(False))
    if q:
        statement = statement.where(TextMessage.body.ilike(contains(q), escape=LIKE_ESCAPE))
    rows = list((await session.scalars(statement)).all())
    return await _as_messages(session, rows, metrics=metrics)


@router.get("/channels")
async def channels(session: AsyncSession = Depends(get_session)) -> list[dict[str, object]]:
    """Return channels with stored text-message counts."""
    statement = select(TextMessage.channel, func.count().label("count")).group_by(
        TextMessage.channel
    )
    return [
        {"channel": channel, "count": count}
        for channel, count in (await session.execute(statement)).all()
    ]


@router.get("/overview")
async def overview(
    request: Request,
    hours: int = Query(default=168, ge=1, le=8760),
    per_channel: int = Query(default=25, ge=1, le=200),
    preset: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    """Return every detected channel with its recent messages.

    Each channel carries its group. The group is the LoRa modem preset
    when the channel uses a default preset name. The chat page draws one
    section for each channel, below the heading of its group.

    Set `preset` to keep the messages carried on one modem preset. A
    topic channel such as `azmsh` then lists only its messages on that
    preset, and a channel with none on it has no section (#313).
    """
    wanted = require_presets(preset)
    since = datetime.now(UTC) - timedelta(hours=hours)
    core = tuple(request.app.state.settings.core_channels)
    default = str(request.app.state.settings.default_preset)
    # `count` counts messages the way `/api/chat` lists them: tapbacks
    # left out (#297). It counted every row, so MediumFast said "Open all
    # 1,252 messages" over a channel page that ends at 663 -- the other
    # 589 were reactions, which the page attaches to their message rather
    # than listing. The tapbacks are still counted, separately, and the
    # GROUP BY still reads every row, so a channel of nothing but
    # tapbacks keeps its section with a count of 0.
    message_count = func.count().filter(TextMessage.emoji.is_(False))
    counts = (
        await session.execute(
            _on_preset(
                select(
                    TextMessage.channel,
                    message_count.label("count"),
                    func.count().filter(TextMessage.emoji.is_(True)).label("reactions"),
                    func.max(TextMessage.seen_at).label("last_seen"),
                ),
                wanted,
                since,
                default,
            )
            .where(TextMessage.seen_at >= since)
            .group_by(TextMessage.channel)
            .order_by(message_count.desc())
        )
    ).all()

    # One query for every channel's newest messages, not one per
    # channel.
    #
    # Channel names arrive from MQTT, so the number of times that loop
    # ran was decided by the mesh rather than by us -- and each pass
    # cost four queries, because `_as_messages` issues three of its own
    # for names, reactions and reply parents. Ten channels was 41
    # round trips and about two seconds.
    #
    # ROW_NUMBER partitioned by channel does the per-channel limit in
    # the database. PARTITION BY groups NULLs together, which is the
    # same thing the `IS NULL` branch above used to do for messages
    # that arrived with no channel.
    ranked = (
        _on_preset(
            select(
                TextMessage,
                func.row_number()
                .over(partition_by=TextMessage.channel, order_by=TextMessage.seen_at.desc())
                .label("rank"),
            ),
            wanted,
            since,
            default,
        )
        .where(TextMessage.seen_at >= since, TextMessage.emoji.is_(False))
        .subquery()
    )
    newest = aliased(TextMessage, ranked)
    rows = list(
        (
            await session.scalars(
                select(newest)
                .where(ranked.c.rank <= per_channel)
                # Both columns must come off the subquery. Ordering by
                # `TextMessage.seen_at` here compiles to
                # `ORDER BY text_message.seen_at`, and `text_message` is
                # not in the outer FROM -- Postgres either refuses it or
                # joins the base table in again.
                .order_by(ranked.c.channel, ranked.c.seen_at.desc())
            )
        ).all()
    )

    # And one name/reaction/parent resolution for all of them together.
    resolved = await _as_messages(session, rows)
    by_channel: dict[str | None, list[dict[str, object]]] = {}
    for message in resolved:
        by_channel.setdefault(cast("str | None", message["channel"]), []).append(message)

    sections = []
    for row in counts:
        sections.append(
            classify(row.channel, core)
            | {
                "count": row.count,
                "reactions": row.reactions,
                "last_seen": row.last_seen,
                # A channel whose every message in the window is a
                # tapback has a count but no messages. It kept its
                # section before and keeps it now.
                "messages": by_channel.get(row.channel, []),
            }
        )
    sections.sort(key=lambda item: (group_order(str(item["group"])), -int(item["count"])))
    return {"window_hours": hours, "sections": sections}


def _check_in_filter(word: str, channel: str) -> tuple[ColumnElement[bool], ...]:
    """Return what makes a stored message a check-in (#262).

    One definition, used by BOTH reads in `tagged`: the message list
    and the 52-week aggregate the streaks are counted from. They used to
    carry two copies of the same three conditions, and a copy is where
    a scope gets added to one read and forgotten on the other -- which
    here would mean a page that shows MediumFast messages beside streaks
    counted across every channel, and no way for a reader to tell.

    **The channel is part of the definition, and it is applied here, on
    the server.** The weekly net runs on MediumFast (Will: "For the
    whole weekly check-in it should only be for the MediumFast
    channel"). Filtering in the browser would hide the other channels'
    messages and leave their weeks inside every streak, because the
    streak is an aggregate the browser never sees the rows of. A node
    that posted `#meshnet` on LongFast one week and MediumFast the next
    would read "2 weeks" beside a list that showed it once.

    Exact equality, not the case-folded match `classify` uses for
    grouping: the channel name is what the MQTT topic carried, and
    `trivia` and `Trivia` on this mesh are two different channels with
    two different sets of people on them.
    """
    return (
        TextMessage.channel == channel,
        # `_TAG` allows an underscore, which is a LIKE wildcard:
        # `#foo_bar` matched `#fooXbar`.
        TextMessage.body.ilike(contains(f"#{word}"), escape=LIKE_ESCAPE),
        TextMessage.emoji.is_(False),
    )


async def _weekly_check_ins(
    session: AsyncSession, word: str, floor: datetime, channel: str
) -> dict[tuple[int, datetime], dict[str, object]]:
    """Return one entry per node per week it carried the tag.

    An aggregate rather than a read of the messages, for two reasons.

    **It is bounded by nodes times weeks, not by messages.** The streak
    read goes a year back (`STREAK_LOOKBACK_WEEKS`), and a list of
    messages over a year has no ceiling that is ours to set. A limit on
    it would silently shorten a streak, which is the one thing this
    endpoint must not do -- AGENTS.md 9.19: a row limit must not decide
    what the page says exists.

    **It keeps one definition of a week.** SQL does the grouping, but
    the week each group belongs to is worked out by `_week_start` from
    the group's own earliest message, so the boundary a reader sees
    comes from the same function everywhere in this module. Postgres'
    `date_trunc('week', ...)` is the ISO week and starts on Monday, the
    same as `_week_start`, and `AT TIME ZONE 'UTC'` makes it the same
    Monday; grouping on it and then re-keying in Python means that even
    if that ever stopped being true, two SQL groups would merge into one
    of our weeks rather than a week landing in the wrong place.
    """
    # `timezone('UTC', <timestamptz>)` is `AT TIME ZONE 'UTC'`: it
    # converts to UTC and drops the zone, so `date_trunc` cannot be
    # steered by whatever the session's TimeZone happens to be.
    week = func.date_trunc("week", func.timezone("UTC", TextMessage.seen_at))
    statement = (
        select(
            TextMessage.from_node_num.label("node"),
            func.count().label("messages"),
            func.min(TextMessage.seen_at).label("first_seen"),
            func.max(TextMessage.seen_at).label("last_seen"),
        )
        .where(*_check_in_filter(word, channel), TextMessage.seen_at >= floor)
        .group_by(TextMessage.from_node_num, week)
    )
    found: dict[tuple[int, datetime], dict[str, object]] = {}
    for row in (await session.execute(statement)).all():
        key = (int(row.node), _week_start(row.first_seen))
        held = found.get(key)
        if held is None:
            found[key] = {
                "messages": int(row.messages),
                "first_seen": row.first_seen,
                "last_seen": row.last_seen,
            }
            continue
        # Only reachable if SQL's week and ours ever disagreed. Merging
        # is the safe answer: a week gains messages it really holds.
        held["messages"] = int(cast("int", held["messages"])) + int(row.messages)
        held["first_seen"] = min(cast("datetime", held["first_seen"]), row.first_seen)
        held["last_seen"] = max(cast("datetime", held["last_seen"]), row.last_seen)
    return found


def _message_streak(
    weeks: frozenset[datetime] | None, week: datetime, floor: datetime
) -> dict[str, object]:
    """Return the streak a sender was on when one message was posted (#262).

    The page draws the streak as a pill beside the name on each message,
    so each message carries the run as of ITS week -- not the sender's
    run today. A message from four weeks ago beside today's number would
    say "12 weeks" about a week in which the run was 8.

    The run comes from the same aggregate and the same `_streak_as_of`
    as the roster, so a pill and the roster can never disagree. A
    message whose sender and week are somehow not in the aggregate gets
    `None`, which the page words as "Streak not known" -- never a 0,
    because rule 3 says a check-in's run is at least 1 and a zero here
    would be a missing figure drawn as a real one.
    """
    if not weeks or week not in weeks:
        return {"streak_weeks": None, "streak_at_least": False, "first_ever": False}
    length, at_least = _streak_as_of(weeks, week, floor)
    return {
        "streak_weeks": length,
        "streak_at_least": at_least,
        "first_ever": min(weeks) == week,
    }


def _week_roster(
    *,
    week: datetime,
    buckets: dict[tuple[int, datetime], dict[str, object]],
    by_node: dict[int, frozenset[datetime]],
    names: dict[int, dict[str, str | None]],
    floor: datetime,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """Return who checked in during one week, and who did not.

    The second list holds the nodes that checked in the week *before*
    this one and not during it -- the narrowest rule that answers the
    question the page asks, and the only one that does not slander
    somebody who stopped taking part months ago.

    Both lists are named for what was observed. `not_seen` is not
    `missed`: rule 6. The word on the page is "no message found".
    """
    previous = week - _WEEK
    checked_in: list[dict[str, object]] = []
    not_seen: list[dict[str, object]] = []
    for node, weeks in by_node.items():
        entry = buckets.get((node, week))
        if entry is not None:
            length, at_least = _streak_as_of(weeks, week, floor)
            checked_in.append(
                {
                    "node_id": format_node_id(node),
                    "display_name": name_of(names, node),
                    "message_count": entry["messages"],
                    "first_seen": entry["first_seen"],
                    "last_seen": entry["last_seen"],
                    "streak_weeks": length,
                    "streak_at_least": at_least,
                    # The node's first check-in anywhere in the read. A
                    # run of one is either a beginning or a restart, and
                    # the page says which rather than making the reader
                    # guess from a lonely "1".
                    "first_ever": min(weeks) == week,
                }
            )
        elif previous in weeks:
            length, at_least = _streak_as_of(weeks, previous, floor)
            not_seen.append(
                {
                    "node_id": format_node_id(node),
                    "display_name": name_of(names, node),
                    "streak_weeks": length,
                    "streak_at_least": at_least,
                }
            )

    # Longest run first, then by name, so the page's order is stable
    # between polls rather than following whatever the aggregate happened
    # to return.
    def order(item: dict[str, object]) -> tuple[int, str]:
        return (-cast("int", item["streak_weeks"]), str(item["display_name"]))

    checked_in.sort(key=order)
    not_seen.sort(key=order)
    return (checked_in, not_seen)


@router.get("/tagged")
async def tagged(
    request: Request,
    tag: str = DEFAULT_TAG,
    weeks: int = Query(default=8, ge=1, le=104),
    limit: int = Query(default=500, ge=1, le=2000),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    """Return messages that carry one hashtag, grouped by week, with streaks.

    The weekly mesh network check-in uses the `#meshnet` tag, on the
    deployment's primary preset channel (`default_preset`, MediumFast
    here) and on no other: see `_check_in_filter`. A week starts on
    Monday in UTC.

    Every week in the display window is returned, including one nobody
    checked in, because a gap is the point of the page and a week that is
    simply absent from the list reads as a week that never happened.
    Weeks before the oldest tagged message this read could find are left
    out: there is no evidence about them either way, and drawing them
    empty would assert silence where the record merely starts later.

    What a streak means, and what an unfinished week does to it, is
    written out above `_streak_as_of`. Read it before changing anything
    here: every field below is a claim about a person's participation.
    """
    word = _require_tag(tag)
    # The net's channel is the deployment's primary preset (#262). A
    # setting rather than the literal "MediumFast" for the reason
    # `default_preset` is one: another mesh running its net on LongFast
    # should not have to patch this route to get a page at all.
    channel = str(request.app.state.settings.default_preset)
    now = datetime.now(UTC)
    current_week = _week_start(now)
    since = current_week - timedelta(weeks=weeks - 1)
    floor = current_week - timedelta(weeks=weeks - 1 + STREAK_LOOKBACK_WEEKS)

    rows = list(
        (
            await session.scalars(
                select(TextMessage)
                .where(*_check_in_filter(word, channel), TextMessage.seen_at >= since)
                .order_by(TextMessage.seen_at.desc())
                .limit(limit)
            )
        ).all()
    )
    messages = await _as_messages(session, rows)

    buckets = await _weekly_check_ins(session, word, floor, channel)
    by_node = _check_in_weeks(buckets)

    shown: dict[datetime, list[dict[str, object]]] = {}
    for row, message in zip(rows, messages, strict=True):
        week_of = _week_start(row.seen_at)
        message.update(_message_streak(by_node.get(row.from_node_num), week_of, floor))
        shown.setdefault(week_of, []).append(message)
    names = await resolve_names(session, list(by_node))

    keeping_text = bool(request.app.state.settings.store_text_messages)
    # Rule 7: nothing to compute from is not a row of zeroes.
    assessed = _streaks_assessed(buckets, keeping_text)

    earliest = min((week for _, week in buckets), default=None)
    listed: list[datetime] = []
    week = current_week
    while week >= since:
        if earliest is not None and week >= earliest:
            listed.append(week)
        week -= _WEEK

    out: list[dict[str, object]] = []
    for week in listed:
        checked_in, not_seen = _week_roster(
            week=week, buckets=buckets, by_node=by_node, names=names, floor=floor
        )
        items = shown.get(week, [])
        counted = sum(
            int(cast("int", entry["messages"]))
            for (_, bucket_week), entry in buckets.items()
            if bucket_week == week
        )
        out.append(
            {
                "week_start": week,
                "week_end": week + _WEEK,
                # This week has not finished. Rule 5: nothing here is a
                # verdict on it, and the page must say so before it draws
                # an absence.
                "in_progress": week == current_week,
                "message_count": counted,
                "check_in_count": len(checked_in),
                "check_ins": checked_in,
                "not_seen": not_seen,
                # `message_count` is measured by the aggregate and
                # `messages` is capped by `limit`, so the two disagree on
                # a busy week. The page needs to know which number is the
                # fact rather than infer it from a list length.
                "messages_shown": len(items),
                "messages": items,
            }
        )

    return {
        "tag": f"#{word}",
        # Which channel the check-ins were read from, so the page says
        # so from the answer rather than from its own assumption.
        "channel": channel,
        "window_weeks": weeks,
        # Whether the ingest is keeping message bodies at all. With it
        # off there will never be a check-in to find, and an empty page
        # is a fact about the configuration rather than about the mesh.
        "text_storage": keeping_text,
        "streaks": (
            {
                "lookback_weeks": weeks - 1 + STREAK_LOOKBACK_WEEKS,
                # The oldest week this read could see. A streak that
                # reaches it carries `streak_at_least`, and the page
                # draws that as "12+" rather than "12".
                "floor_week": floor,
                "current_week": current_week,
            }
            if assessed
            else None
        ),
        "weeks": out,
    }


@router.get("/conversation/{from_node}/{packet_id}")
async def conversation(
    from_node: str,
    packet_id: int,
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    """Return a stored message and its replies.

    A message is addressed the way a packet is, by the node that sent it
    and the packet ID, because a packet ID is only unique per sender.
    `text_message` is indexed on exactly that pair.

    This used to match on `packet_pk`, which is never written, so it
    could not find a message at all.
    """
    from_num = require_node_num(from_node)
    message = await session.scalar(
        select(TextMessage)
        .where(
            TextMessage.from_node_num == from_num,
            TextMessage.packet_id == packet_id,
        )
        .order_by(TextMessage.seen_at.desc())
    )
    if message is None:
        raise HTTPException(status_code=404, detail="message not found")
    # A reply names its parent by packet ID alone: that is all the
    # Meshtastic field carries, so a reply cannot be constrained to this
    # sender. `_reactions_for` reads them the same way.
    replies = list(
        (
            await session.scalars(
                select(TextMessage)
                .where(TextMessage.reply_id == packet_id, TextMessage.emoji.is_(False))
                .order_by(TextMessage.seen_at.asc())
            )
        ).all()
    )
    both = await _as_messages(session, [message, *replies])
    return {"message": both[0], "replies": both[1:]}
