"""One short line saying what each packet on a page said.

The firehose listed a packet's type, sender and hops, and nothing it
carried: to learn what a position or a telemetry packet held, a reader
had to open each one. This reads the decoded rows for a whole page of
packets in one query per family, and writes each as a few words.

Only what is stored is shown. A kind with no decoded table, such as
node info or routing, gets no line rather than a guess.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from sonoran.db.models import (
    DeviceMetrics,
    EnvironmentMetrics,
    NeighborMetrics,
    PositionMetrics,
    TextMessage,
    Traceroute,
)
from sonoran.positions import precision_deviation_m

Key = tuple[int, int]

# Decoded rows are written just after their packet. The bound lets each
# hypertable read skip old chunks; the keys decide which rows count.
_SLACK = timedelta(hours=1)
# A message preview, not the message. The packet page holds the whole.
_TEXT_CHARS = 80


def _short(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= _TEXT_CHARS else text[: _TEXT_CHARS - 1] + "…"


def _doubt(bits: int | None) -> str:
    metres = precision_deviation_m(bits)
    if not metres:
        return ""
    return (
        f", within about {metres / 1000:.1f} km"
        if metres >= 1000
        else f", within about {metres:.0f} m"
    )


def _device(row: Any) -> str | None:
    parts = []
    if row.battery_level is not None:
        # Meshtastic reports more than 100 when the node is on external power.
        parts.append(
            "on power" if row.battery_level > 100 else f"battery {row.battery_level:.0f} %"
        )
    if row.voltage is not None:
        parts.append(f"{row.voltage:.2f} V")
    if row.channel_utilization is not None:
        parts.append(f"channel use {row.channel_utilization:.1f} %")
    return ", ".join(parts) or None


def _environment(row: Any) -> str | None:
    parts = []
    if row.temperature is not None:
        parts.append(f"{row.temperature:.1f} C")
    if row.relative_humidity is not None:
        parts.append(f"humidity {row.relative_humidity:.0f} %")
    if row.barometric_pressure is not None:
        parts.append(f"{row.barometric_pressure:.0f} hPa")
    return ", ".join(parts) or None


async def summaries(
    session: AsyncSession, keys: Sequence[Key], since: datetime | None
) -> dict[Key, str]:
    """Return a one line summary for each packet key that has stored content."""
    wanted = sorted(set(keys))
    if not wanted:
        return {}
    lower = None if since is None else since - _SLACK
    found: dict[Key, str] = {}

    def bounded(statement: Any, column: Any) -> Any:
        return statement if lower is None else statement.where(column >= lower)

    rows = await session.execute(
        bounded(
            select(
                TextMessage.from_node_num,
                TextMessage.packet_id,
                TextMessage.body,
                TextMessage.emoji,
            ).where(tuple_(TextMessage.from_node_num, TextMessage.packet_id).in_(wanted)),
            TextMessage.seen_at,
        )
    )
    for row in rows:
        body = _short(row.body or "")
        found[(row.from_node_num, row.packet_id)] = f"reacted {body}" if row.emoji else f"“{body}”"

    rows = await session.execute(
        bounded(
            select(
                PositionMetrics.node_num,
                PositionMetrics.packet_id,
                PositionMetrics.latitude,
                PositionMetrics.longitude,
                PositionMetrics.precision_bits,
            ).where(tuple_(PositionMetrics.node_num, PositionMetrics.packet_id).in_(wanted)),
            PositionMetrics.time,
        )
    )
    for row in rows:
        if row.latitude is None or row.longitude is None:
            continue
        found[(row.node_num, row.packet_id)] = (
            f"{row.latitude:.4f}, {row.longitude:.4f}{_doubt(row.precision_bits)}"
        )

    for model, render in ((DeviceMetrics, _device), (EnvironmentMetrics, _environment)):
        rows = await session.execute(
            bounded(
                select(model).where(tuple_(model.node_num, model.packet_id).in_(wanted)),
                model.time,
            )
        )
        for (item,) in rows:
            line = render(item)
            if line and item.packet_id is not None:
                found[(item.node_num, item.packet_id)] = line

    rows = await session.execute(
        bounded(
            select(NeighborMetrics.node_num, NeighborMetrics.packet_id, func.count().label("n"))
            .where(tuple_(NeighborMetrics.node_num, NeighborMetrics.packet_id).in_(wanted))
            .group_by(NeighborMetrics.node_num, NeighborMetrics.packet_id),
            NeighborMetrics.time,
        )
    )
    for row in rows:
        found[(row.node_num, row.packet_id)] = f"{row.n} neighbour{'s' if row.n != 1 else ''} heard"

    rows = await session.execute(
        bounded(
            select(
                Traceroute.from_node_num,
                Traceroute.packet_id,
                Traceroute.route,
                Traceroute.request_id,
            ).where(tuple_(Traceroute.from_node_num, Traceroute.packet_id).in_(wanted)),
            Traceroute.seen_at,
        )
    )
    for row in rows:
        # A request has not travelled yet, so it has no hops to count.
        if not row.request_id:
            found[(row.from_node_num, row.packet_id)] = "traceroute request"
            continue
        hops = len(row.route or [])
        found[(row.from_node_num, row.packet_id)] = (
            f"traceroute reply, {hops} hop{'s' if hops != 1 else ''} out"
        )

    return found
