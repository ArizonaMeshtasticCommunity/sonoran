"""Read-only chat endpoints."""

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import Select, and_, func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from sonoran.api.channels import classify, group_order
from sonoran.api.dependencies import (
    LIKE_ESCAPE,
    contains,
    get_session,
    require_node_num,
)
from sonoran.api.names import format_node_id, name_of, resolve_names
from sonoran.db.models import Packet, PacketSeen, TextMessage

router = APIRouter(prefix="/api/chat", tags=["chat"])

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
    channel: str | None = None,
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
    """
    statement = select(TextMessage).order_by(TextMessage.seen_at.desc()).limit(limit)
    statement = _apply_filters(statement, channel, from_node, since, before)
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
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    """Return every detected channel with its recent messages.

    Each channel carries its group. The group is the LoRa modem preset
    when the channel uses a default preset name. The chat page draws one
    section for each channel, below the heading of its group.
    """
    since = datetime.now(UTC) - timedelta(hours=hours)
    core = tuple(request.app.state.settings.core_channels)
    counts = (
        await session.execute(
            select(
                TextMessage.channel,
                func.count().label("count"),
                func.max(TextMessage.seen_at).label("last_seen"),
            )
            .where(TextMessage.seen_at >= since)
            .group_by(TextMessage.channel)
            .order_by(func.count().desc())
        )
    ).all()

    sections = []
    for row in counts:
        rows = list(
            (
                await session.scalars(
                    select(TextMessage)
                    .where(
                        TextMessage.channel.is_(None)
                        if row.channel is None
                        else TextMessage.channel == row.channel,
                        TextMessage.seen_at >= since,
                        TextMessage.emoji.is_(False),
                    )
                    .order_by(TextMessage.seen_at.desc())
                    .limit(per_channel)
                )
            ).all()
        )
        sections.append(
            classify(row.channel, core)
            | {
                "count": row.count,
                "last_seen": row.last_seen,
                "messages": await _as_messages(session, rows),
            }
        )
    sections.sort(key=lambda item: (group_order(str(item["group"])), -int(item["count"])))
    return {"window_hours": hours, "sections": sections}


@router.get("/tagged")
async def tagged(
    tag: str = DEFAULT_TAG,
    weeks: int = Query(default=8, ge=1, le=104),
    limit: int = Query(default=500, ge=1, le=2000),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    """Return messages that carry one hashtag, grouped by week.

    The weekly mesh network check-in uses the `#meshnet` tag. A week
    starts on Monday in UTC.
    """
    word = _require_tag(tag)
    since = _week_start(datetime.now(UTC)) - timedelta(weeks=weeks - 1)
    rows = list(
        (
            await session.scalars(
                select(TextMessage)
                .where(
                    # `_TAG` allows an underscore, which is a LIKE
                    # wildcard: `#foo_bar` matched `#fooXbar`.
                    TextMessage.body.ilike(contains(f"#{word}"), escape=LIKE_ESCAPE),
                    TextMessage.seen_at >= since,
                    TextMessage.emoji.is_(False),
                )
                .order_by(TextMessage.seen_at.desc())
                .limit(limit)
            )
        ).all()
    )
    messages = await _as_messages(session, rows)

    buckets: dict[datetime, list[dict[str, object]]] = {}
    for row, message in zip(rows, messages, strict=True):
        buckets.setdefault(_week_start(row.seen_at), []).append(message)

    return {
        "tag": f"#{word}",
        "weeks": [
            {
                "week_start": start,
                "week_end": start + timedelta(days=7),
                "message_count": len(items),
                "check_in_count": len({item["from_node"] for item in items}),
                "messages": items,
            }
            for start, items in sorted(buckets.items(), reverse=True)
        ],
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
