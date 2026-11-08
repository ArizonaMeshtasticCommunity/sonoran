"""Read-only packet endpoints."""

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import ColumnElement, and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from sonoran.api.dependencies import get_session, require_node_num
from sonoran.api.names import name_of, resolve_names
from sonoran.api.packet_summary import summaries, text_of
from sonoran.api.preset_scope import preset_filter, require_presets
from sonoran.db.models import (
    AirQualityMetrics,
    DeviceMetrics,
    EnvironmentMetrics,
    MeshPacketMetrics,
    NeighborMetrics,
    Node,
    Packet,
    PacketSeen,
    PositionMetrics,
    PowerMetrics,
    TextMessage,
)
from sonoran.meshtastic import portnums_pb2

router = APIRouter(prefix="/api/packets", tags=["packets"])

# How far before a packet's first sighting its metrics rows are read. The
# bound lets the hypertable read skip old chunks. It does not decide which
# rows count: every row is keyed on the packet itself.
_METRICS_SLACK = timedelta(hours=1)


def _node_id(value: int | None) -> str:
    """Format a node number for a JSON response."""
    return "^all" if value is None else f"!{value:08x}"


def _same_packet(packet: type[Packet], seen: type[PacketSeen]) -> ColumnElement[bool]:
    """Match a packet to its observations by the deduplication key.

    The ingest role has no SELECT right, so it cannot read back the
    generated `packet.id` and cannot store it on the observation. The
    two rows are joined by (`from_node_num`, `packet_id`) instead, which
    is the documented deduplication key.
    """
    return and_(
        seen.from_node_num == packet.from_node_num,
        seen.packet_id == packet.packet_id,
    )


def _packet_item(
    packet: Packet,
    seen_count: int,
    names: dict[int, dict[str, str | None]] | None = None,
) -> dict[str, object]:
    """Map a packet row to its public summary."""
    try:
        portnum = portnums_pb2.PortNum.Name(packet.portnum)  # type: ignore[attr-defined]
    except ValueError:
        portnum = str(packet.portnum)
    names = names or {}
    return {
        "packet_key": f"{packet.from_node_num}:{packet.packet_id}",
        "from_node": _node_id(packet.from_node_num),
        "from_name": name_of(names, packet.from_node_num),
        "to_node": _node_id(packet.to_node_num),
        "to_name": name_of(names, packet.to_node_num),
        "portnum": portnum,
        "channel": packet.channel,
        "hop_start": packet.hop_start,
        "hop_limit": packet.hop_limit,
        "first_seen_at": packet.first_seen_at,
        "seen_count": seen_count,
    }


def _parse_portnum(value: str) -> int:
    """Parse a numeric or protobuf port-number name."""
    if value.isdecimal():
        return int(value)
    try:
        return portnums_pb2.PortNum.Value(value)  # type: ignore[attr-defined]
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="invalid portnum") from exc


@router.get("")
async def list_packets(
    portnum: str | None = None,
    from_node: str | None = Query(default=None, alias="from"),
    to_node: str | None = Query(default=None, alias="to"),
    channel: str | None = None,
    preset: str | None = None,
    since: datetime | None = None,
    before: datetime | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    summary: bool = False,
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, object]]:
    """Return packets newest first.

    Set `summary=true` to add a one line `summary` of what each packet
    said, read from the decoded tables. See `api/packet_summary.py`.

    Set `preset` to keep the packets carried on one modem preset, or on
    any of several (`preset=MediumFast,LongFast`). It works beside
    `channel`. See `api/preset_scope.py`.
    """
    wanted = require_presets(preset)
    # Pick the page first, count second.
    #
    # This used to group the whole join before applying the limit, so
    # the limit could not push down and the planner read every chunk of
    # `packet` on every request -- 724k rows, five sequential scans, and
    # a 14 MB sort spilled to disk, for a hundred rows. Measured at
    # 629 ms, with `packet_first_seen_at_idx` never used.
    #
    # Choosing the page in its own statement lets the index do the
    # ordering, so only the rows that will be returned are ever joined
    # to `packet_seen`. Measured at 19.8 ms, and the sort fits in
    # memory. Same answer either way.
    #
    # This is the shape `map.py` already uses for the same reason; see
    # the note there about a correlated read.
    picked = (
        select(Packet.id.label("pk"), Packet.first_seen_at.label("at"))
        .order_by(Packet.first_seen_at.desc())
        .limit(limit)
    )
    if portnum is not None:
        picked = picked.where(Packet.portnum == _parse_portnum(portnum))
    if from_node:
        picked = picked.where(Packet.from_node_num == require_node_num(from_node))
    if to_node:
        picked = picked.where(Packet.to_node_num == require_node_num(to_node))
    if channel:
        picked = picked.where(Packet.channel == channel)
    if wanted is not None:
        # The same newest-first scan of the time index as `channel`: the
        # filter is checked on each row the scan reaches. See the PR for
        # why there is no index on the tag.
        picked = picked.where(preset_filter(Packet.modem_preset, Packet.channel, wanted))
    if since:
        picked = picked.where(Packet.first_seen_at >= since)
    if before:
        picked = picked.where(Packet.first_seen_at < before)
    page = picked.cte("page")

    # Counted for each row of the page, never as a join.
    #
    # The CTE above does not fence anything: PostgreSQL inlines it, and
    # with the count as a LEFT JOIN it was free to join every packet to
    # every observation first and apply the page last. On 2026-09-30 it
    # did exactly that: a parallel hash of all 7.7M `packet_seen` rows,
    # which overflowed the database container's 64 MB `/dev/shm`, and
    # the firehose answered 500 on every load. A correlated count is at
    # most `limit` index probes on `ix_packet_seen_natural_key`,
    # whatever the planner thinks of the tables. Same answer: zero for a
    # packet nobody uploaded, as the LEFT JOIN gave.
    #
    # The page is joined back on its time as well as its id, so each
    # lookup reads one chunk of `packet` rather than every one.
    seen_count = (
        select(func.count())
        .select_from(PacketSeen)
        .where(_same_packet(Packet, PacketSeen))
        .correlate(Packet)
        .scalar_subquery()
        .label("seen_count")
    )
    statement = (
        select(Packet, seen_count)
        .join(page, and_(page.c.pk == Packet.id, page.c.at == Packet.first_seen_at))
        .order_by(Packet.first_seen_at.desc())
    )
    rows = (await session.execute(statement)).all()
    names = await resolve_names(
        session, [num for packet, _ in rows for num in (packet.from_node_num, packet.to_node_num)]
    )
    items = [_packet_item(packet, seen_count, names) for packet, seen_count in rows]
    if summary and rows:
        lines = await summaries(
            session,
            [(packet.from_node_num, packet.packet_id) for packet, _ in rows],
            min(packet.first_seen_at for packet, _ in rows),
        )
        for item, (packet, _) in zip(items, rows, strict=True):
            parts = lines.get((packet.from_node_num, packet.packet_id))
            item["summary"] = text_of(parts)
            # The same line with each measurement as a number and its SI
            # unit, so the browser can write it in the reader's units.
            item["summary_parts"] = parts
    return items


def _values(model: Any, row: object) -> dict[str, object]:
    """Return the stored columns of one decoded row."""
    skip = {"id", "packet_pk", "packet_id", "node_num", "from_node_num"}
    return {
        column.name: getattr(row, column.name)
        for column in model.__table__.columns
        if column.name not in skip and getattr(row, column.name) is not None
    }


def _named_neighbours(
    values: list[dict[str, object]], names: dict[int, dict[str, str | None]]
) -> list[dict[str, object]]:
    """Add the ID and the readable name of each reported neighbour.

    A neighbour report names the nodes it heard by number only, because
    that is all `neighbor_metrics` stores. The packet page therefore
    printed `!0a51a002` in the table of reported neighbours, while the
    gateway table higher up the same page printed "Usery Pass Relay" for
    the very same node (#240).

    The name is joined here and not in the browser. The browser holds no
    node table, so it would need one request per neighbour to build the
    same answer, and the gateway rows on this page are already named
    server side by `resolve_names`. One more query for the whole list is
    the cheaper half of that comparison.

    `name_of` falls back to the ID form for a node this dashboard has
    never seen a node-info packet from, so `neighbor_name` is always a
    string worth printing and the browser needs no fallback of its own.
    `neighbor_node_num` stays, because the raw panel shows the row as the
    database holds it.
    """
    labelled: list[dict[str, object]] = []
    for row in values:
        num = row.get("neighbor_node_num")
        if not isinstance(num, int):
            # Unreachable today: the column is NOT NULL, and `_values`
            # only drops a None. It is here because the alternative is a
            # KeyError that takes out the whole page, and a row with no
            # name still reads.
            labelled.append(row)
            continue
        labelled.append(row | {"neighbor_id": _node_id(num), "neighbor_name": name_of(names, num)})
    return labelled


async def _decoded_payload(session: AsyncSession, packet: Packet) -> dict[str, object] | None:
    """Return the decoded payload of one packet.

    The packet table stores the raw bytes only. Every decoded value goes
    to the table of its family, keyed by the node and the packet ID. This
    reads it back so a packet page can show what the packet carried.
    """
    # Each family stores its decoded values in its own table. Telemetry
    # splits further, so several tables are tried for one port number.
    candidates: list[tuple[str, Any, Any]] = []
    if packet.portnum == portnums_pb2.TEXT_MESSAGE_APP:  # type: ignore[attr-defined]
        candidates = [("text", TextMessage, TextMessage.from_node_num)]
    elif packet.portnum == portnums_pb2.POSITION_APP:  # type: ignore[attr-defined]
        candidates = [("position", PositionMetrics, PositionMetrics.node_num)]
    elif packet.portnum == portnums_pb2.NEIGHBORINFO_APP:  # type: ignore[attr-defined]
        candidates = [("neighbors", NeighborMetrics, NeighborMetrics.node_num)]
    elif packet.portnum == portnums_pb2.TELEMETRY_APP:  # type: ignore[attr-defined]
        candidates = [
            ("device", DeviceMetrics, DeviceMetrics.node_num),
            ("environment", EnvironmentMetrics, EnvironmentMetrics.node_num),
            ("air_quality", AirQualityMetrics, AirQualityMetrics.node_num),
            ("power", PowerMetrics, PowerMetrics.node_num),
        ]

    for kind, model, node_column in candidates:
        rows = list(
            (
                await session.scalars(
                    select(model).where(
                        node_column == packet.from_node_num,
                        model.packet_id == packet.packet_id,
                    )
                )
            ).all()
        )
        if not rows:
            continue
        values = [_values(model, row) for row in rows]
        if kind == "neighbors":
            # The only decoded family whose rows point at another node.
            names = await resolve_names(session, [row.neighbor_node_num for row in rows])
            values = _named_neighbours(values, names)
        return {"kind": kind, "values": values}
    return None


@router.get("/{from_node}/{packet_id}")
async def get_packet(
    from_node: str,
    packet_id: int,
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    """Return one packet and its MQTT observations."""
    try:
        from_num = require_node_num(from_node)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    packet = await session.scalar(
        select(Packet)
        .where(Packet.from_node_num == from_num, Packet.packet_id == packet_id)
        .order_by(Packet.first_seen_at.desc())
    )
    if packet is None:
        raise HTTPException(status_code=404, detail="packet not found")
    observations = (
        await session.scalars(
            select(PacketSeen)
            .options(undefer(PacketSeen.relay_node))
            .where(
                PacketSeen.from_node_num == packet.from_node_num,
                PacketSeen.packet_id == packet.packet_id,
            )
            .order_by(PacketSeen.seen_at.asc())
        )
    ).all()
    names = await resolve_names(
        session,
        [
            packet.from_node_num,
            packet.to_node_num,
            *(item.gateway_node_num for item in observations),
        ],
    )
    # The nodes each upload's relay byte may name (AGENTS.md 9.20): the
    # gateway's direct neighbours, the nodes it uploaded at 0 hops. That is
    # the firmware's own scope for a relay byte (NodeDB::resolveLastByte).
    relay_bytes = sorted({item.relay_node for item in observations if item.relay_node})
    # The firmware sends 0xff for a node whose last byte is 0 (NodeDB.h:431).
    low_bytes = [*relay_bytes, 0] if 0xFF in relay_bytes else relay_bytes
    neighbours: dict[int, list[tuple[int, str | None, datetime | None, str | None]]] = {}
    if relay_bytes:
        gateways = sorted({item.gateway_node_num for item in observations})
        rows = (
            await session.execute(
                select(
                    PacketSeen.gateway_node_num,
                    PacketSeen.from_node_num,
                    func.max(PacketSeen.seen_at),
                )
                .where(
                    PacketSeen.gateway_node_num.in_(gateways),
                    PacketSeen.seen_at >= packet.first_seen_at - RELAY_WINDOW,
                    PacketSeen.seen_at <= packet.first_seen_at + RELAY_WINDOW,
                    PacketSeen.hop_start > 0,
                    PacketSeen.hop_start == PacketSeen.hop_limit,
                    PacketSeen.gateway_node_num != PacketSeen.from_node_num,
                    PacketSeen.from_node_num.op("&")(0xFF).in_(low_bytes),
                )
                .group_by(PacketSeen.gateway_node_num, PacketSeen.from_node_num)
            )
        ).all()
        nums = sorted({row[1] for row in rows})
        roles = dict(
            (await session.execute(select(Node.node_num, Node.role).where(Node.node_num.in_(nums))))
            .tuples()
            .all()
        )
        relay_names = await resolve_names(session, nums)
        for gateway, num, heard in rows:
            neighbours.setdefault(gateway, []).append(
                (num, name_of(relay_names, num), heard, roles.get(num))
            )
    # Whether the packet was sealed with the recipient's public key (PKI)
    # rather than the channel key. Ingest keeps it per upload in
    # `mesh_packet_metrics`, so it is read from there. None when no row
    # recorded it, which is not the same as false.
    pki_encrypted = await session.scalar(
        select(func.bool_or(MeshPacketMetrics.pki_encrypted)).where(
            MeshPacketMetrics.from_node_num == packet.from_node_num,
            MeshPacketMetrics.packet_id == packet.packet_id,
            MeshPacketMetrics.time >= packet.first_seen_at - _METRICS_SLACK,
        )
    )
    return {
        "packet": _packet_item(packet, len(observations), names)
        | {
            "decoded": await _decoded_payload(session, packet),
            "payload_json": packet.payload_json,
            "want_ack": packet.want_ack,
            "pki_encrypted": pki_encrypted,
            "priority": packet.priority,
            "rx_time": packet.rx_time,
            "raw_bytes_length": None if packet.raw_bytes is None else len(packet.raw_bytes),
        },
        "gateway_count": len({item.gateway_node_num for item in observations}),
        "observations": [
            {
                "gateway": _node_id(item.gateway_node_num),
                "gateway_name": name_of(names, item.gateway_node_num),
                "mqtt_topic": item.mqtt_topic,
                "channel": item.channel,
                "rx_rssi": item.rx_rssi,
                "rx_snr": item.rx_snr,
                "hop_limit": item.hop_limit,
                # A packet that used no hop reached this gateway direct,
                # so its signal reading describes that radio link.
                "hops_taken": (
                    None
                    if packet.hop_start is None or item.hop_limit is None
                    else packet.hop_start - item.hop_limit
                ),
                # The sender is often its own gateway, so it uploads the
                # packet it just sent. That is a node reporting its own
                # voice, not a radio link, and it must never count as a
                # direct observation. Every such row has hop_start equal
                # to hop_limit, so the hop rule alone calls it direct and
                # then offers its reading as the sender's own link.
                # A copy that came back to the sender after a relay used
                # hops, so it is a reception like any other gateway's
                # (beta-sonoran#410).
                "self_reported": (
                    item.gateway_node_num == packet.from_node_num
                    and (
                        packet.hop_start is None
                        or item.hop_limit is None
                        or packet.hop_start == item.hop_limit
                    )
                ),
                "direct": (
                    packet.hop_start is not None
                    and packet.hop_start == item.hop_limit
                    and item.gateway_node_num != packet.from_node_num
                ),
                "seen_at": item.seen_at,
                # One byte, resolved among this gateway's direct neighbours
                # (AGENTS.md 9.20).
                "relayed_by": relay_candidates(
                    item.relay_node,
                    item.gateway_node_num,
                    neighbours,
                    sender=packet.from_node_num,
                    sender_name=name_of(names, packet.from_node_num),
                    hops_taken=(
                        None
                        if packet.hop_start is None or item.hop_limit is None
                        else packet.hop_start - item.hop_limit
                    ),
                ),
            }
            for item in observations
        ],
    }


# A gateway's direct neighbours are the nodes it uploaded at 0 hops within
# a day of the packet. The firmware keeps a neighbour for 2 hours
# (NEXTHOP_NEIGHBOR_FRESH_SECS, MeshTypes.h:51), but Sonoran sees a
# neighbour only when it sends its own traffic, and many nodes send every
# few hours. Live, 2026-10-18, 12,645 relayed uploads: one candidate for
# 79.9 %, none for 6.7 %, at most 6.
RELAY_WINDOW = timedelta(days=1)


def last_byte(num: int) -> int:
    """The relay byte the firmware sends for a node (getLastByteOfNodeNum, NodeDB.h:431)."""
    return num & 0xFF or 0xFF


# Roles that never rebroadcast (FloodingRouter::isRebroadcaster,
# FloodingRouter.cpp:154-158, firmware v2.8.1). A node with
# rebroadcast_mode NONE never does either, but NodeInfo does not say so.
NEVER_RELAYS = frozenset({"CLIENT_MUTE"})


def relay_candidates(
    byte: int | None,
    gateway: int,
    neighbours: Mapping[int, Sequence[tuple[int, str | None, datetime | None, str | None]]],
    *,
    sender: int,
    hops_taken: int | None,
    sender_name: str | None = None,
) -> dict[str, object] | None:
    """The nodes a relay byte may name for one upload, newest first. None without a byte.

    The radio header carries one byte (RadioInterface.h:54). Every send
    writes the sender's own byte first, and each rebroadcast overwrites it
    with the relayer's (FloodingRouter.cpp:22, NextHopRouter.cpp:116). The
    gateway heard that relayer directly, and the firmware itself resolves
    a byte among direct neighbours only (NodeDB::resolveLastByte,
    NodeDB.cpp:4179-4182). So the candidates are `neighbours[gateway]`:
    (node_num, display name, last direct upload, role) for each node the
    gateway uploaded at 0 hops within RELAY_WINDOW of the packet.

    - no hop: the byte is the sender's, and the sender is the answer
      (`exact`). The first hop always lowers the hop limit
      (Router::shouldDecrementHopLimit, Router.cpp:256-258);
    - a hop or more: never the sender (a node does not relay its own
      packet) and never a node that does not rebroadcast;
    - hops unknown: the sender may be the byte; another muted node not.
    """
    if byte is None:
        return None
    if hops_taken == 0 and last_byte(sender) == byte:
        return {
            "byte": f"{byte:02x}",
            "exact": True,
            "candidates": [
                {"node_id": _node_id(sender), "display_name": sender_name or _node_id(sender)}
            ],
        }

    def possible(num: int, role: str | None) -> bool:
        if num == sender:
            return not hops_taken
        return role not in NEVER_RELAYS

    found = sorted(
        (
            (num, name, heard)
            for num, name, heard, role in neighbours.get(gateway, ())
            if last_byte(num) == byte and heard is not None and possible(num, role)
        ),
        key=lambda row: row[2],
        reverse=True,
    )
    return {
        "byte": f"{byte:02x}",
        "exact": False,
        "candidates": [
            {"node_id": _node_id(num), "display_name": name or _node_id(num)}
            for num, name, _ in found
        ],
    }
