"""One short line saying what each packet on a page said.

The firehose listed a packet's type, sender and hops, and nothing it
carried: to learn what a position or a telemetry packet held, a reader
had to open each one. This reads the decoded rows for a whole page of
packets in one query per family, and writes each as a few words.

Only what is stored is shown. A kind with no decoded table, such as
node info or routing, gets no line rather than a guess.

A line is built as parts: plain text, and measurements kept as a number
with its SI unit. The API stays in SI and never converts (see
`web/static/units.js`), so the browser renders each measurement in the
reader's units from `summary_parts`. `summary` is the same line joined in
SI, for any other reader of the API (#291).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any, TypedDict

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


class Measure(TypedDict):
    """A number with its SI unit, for the browser to convert."""

    value: float
    unit: str


Part = str | Measure

# Decoded rows are written just after their packet. The bound lets each
# hypertable read skip old chunks; the keys decide which rows count.
_SLACK = timedelta(hours=1)
# A message preview, not the message. The packet page holds the whole.
_TEXT_CHARS = 80


def _short(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= _TEXT_CHARS else text[: _TEXT_CHARS - 1] + "…"


def _measure(value: float, unit: str, digits: int) -> Measure:
    return Measure(value=round(float(value), digits), unit=unit)


def _doubt(bits: int | None) -> list[Part]:
    metres = precision_deviation_m(bits)
    if not metres:
        return []
    return [", within about ", _measure(metres, "m", 0)]


def _join(parts: list[Part]) -> str:
    """Write a line in SI, for a reader that does not convert."""
    return "".join(
        part if isinstance(part, str) else f"{part['value']:g} {part['unit']}" for part in parts
    )


def _listed(items: list[list[Part]]) -> list[Part] | None:
    """Join several clauses with commas, or None when there are none."""
    if not items:
        return None
    parts: list[Part] = []
    for index, item in enumerate(items):
        if index:
            parts.append(", ")
        parts.extend(item)
    return parts


def _device(row: Any) -> list[Part] | None:
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
    return _listed([[part] for part in parts])


def _environment(row: Any) -> list[Part] | None:
    # A temperature and a pressure are measurements the reader may want in
    # Fahrenheit and inches of mercury, so each stays a number and a unit.
    # This used to write "21.5 C", in Celsius for everybody and without
    # the degree sign.
    items: list[list[Part]] = []
    if row.temperature is not None:
        items.append([_measure(row.temperature, "°C", 1)])
    if row.relative_humidity is not None:
        items.append([f"humidity {row.relative_humidity:.0f} %"])
    if row.barometric_pressure is not None:
        items.append([_measure(row.barometric_pressure, "hPa", 1)])
    return _listed(items)


async def summaries(
    session: AsyncSession, keys: Sequence[Key], since: datetime | None
) -> dict[Key, list[Part]]:
    """Return a one line summary for each packet key that has stored content.

    Each line is a list of parts. `text_of` writes one in SI.
    """
    wanted = sorted(set(keys))
    if not wanted:
        return {}
    lower = None if since is None else since - _SLACK
    found: dict[Key, list[Part]] = {}

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
        found[(row.from_node_num, row.packet_id)] = [
            f"reacted {body}" if row.emoji else f"“{body}”"
        ]

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
        found[(row.node_num, row.packet_id)] = [
            f"{row.latitude:.4f}, {row.longitude:.4f}",
            *_doubt(row.precision_bits),
        ]

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
        found[(row.node_num, row.packet_id)] = [
            f"{row.n} neighbor{'s' if row.n != 1 else ''} heard"
        ]

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
            found[(row.from_node_num, row.packet_id)] = ["traceroute request"]
            continue
        hops = len(row.route or [])
        found[(row.from_node_num, row.packet_id)] = [
            f"traceroute reply, {hops} hop{'s' if hops != 1 else ''} out"
        ]

    return found


def text_of(parts: list[Part] | None) -> str | None:
    """Write a summary in SI, for readers of the API that do not convert."""
    return None if parts is None else _join(parts)
