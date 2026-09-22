"""Leaderboards that reward what helps the mesh (#60).

A shared-airtime mesh is harmed by the behaviour a packet count
celebrates, so none of these boards counts packets. Each one rewards
something that makes the mesh work better for other people:

- `reachable`: heard over the air in the most of the hours it was awake.
  It rewards uptime and good siting, not chatter.
- `direct_gateways`: heard directly, with no hop, by the most gateways.
  A node many radios can hear is doing infrastructure work.
- `longest_link`: the longest link measured in both directions with a
  healthy signal margin. Measured, never claimed.

The first two read the rows the gaps job already wrote, so they cost no
database work at all and cannot disagree with the gaps page. The third
reads the same link evidence as the graph page, through the same
functions, and is held for a while because it is the expensive one.

Every board states its window, what it measures, and what it cannot
know. A board that does not say what it cannot see is an argument, not
a measurement.
"""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from sonoran.api.cache import TimedCache
from sonoran.api.dependencies import get_session
from sonoran.api.names import format_node_id, name_of, resolve_names
from sonoran.api.routes.gaps import read_assessment
from sonoran.api.routes.graph import (
    TWO_WAY,
    Edge,
    _merge,
    _neighbor_edges,
    _traceroute_edges,
)
from sonoran.api.routes.node_page import exact_positions
from sonoran.config import Settings
from sonoran.gaps import store as gaps_store
from sonoran.gaps.siting import distance_km
from sonoran.radio.presets import preset_for_channel, required_snr_db

router = APIRouter(prefix="/api/stats", tags=["stats"])

# How many rows each board shows.
BOARD_SIZE = 10

# The window the link board reads, and how many reports of each kind it
# reads at most. The answer says when the cap was reached.
LINK_WINDOW_HOURS = 72
LINK_ROW_LIMIT = 10_000

# How long a link board is held. The graph evidence behind it changes
# slowly, and reading three days of it is the heaviest thing here.
LINK_CACHE_SECONDS = 900.0

# The fewest hours awake before the reachable board ranks a node. The
# gaps job has its own floor for the signal; this one keeps a node that
# was awake for one lucky hour off the top of the board.
MIN_AWAKE_HOURS = 24

_link_caches: dict[str, TimedCache[dict[str, object]]] = {}


@router.get("/leaderboards")
async def leaderboards(
    request: Request,
    channel: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    """Return the boards for one modem preset.

    One preset at a time, as everywhere else: a node on one preset
    cannot hear a node on another (AGENTS.md 9.7). Without `channel` the
    first preset the gaps job assessed is used.
    """
    settings: Settings = request.app.state.settings
    presets = _assessed_presets(settings)
    preset = channel if channel is not None else (presets[0] if presets else None)
    if preset is None or preset_for_channel(preset) is None:
        return {
            "available": False,
            "reason": "not_a_preset" if preset else "no_assessment",
            "presets": presets,
            "boards": [],
        }
    document = read_assessment(settings, preset)
    rows = _rows(document)
    window = document.get("window_hours") if document else None

    boards: list[dict[str, object]] = [
        _reachable_board(rows, window),
        _direct_board(rows, window),
    ]
    cache = _link_caches.setdefault(preset, TimedCache())
    boards.append(
        await cache.get(
            LINK_CACHE_SECONDS, lambda: _link_board(session, preset, settings.gaps_margin_bad_db)
        )
    )
    return {
        "available": True,
        "preset": preset,
        "presets": presets,
        "assessed": document is not None,
        "boards": boards,
    }


def _assessed_presets(settings: Settings) -> list[str]:
    """Return the assessed presets, the one with the most nodes first.

    The busiest preset is where most of the mesh is, so it is the
    default. The index lists presets in a fixed order, which put a
    quieter preset first.
    """
    index = gaps_store.read_index(settings)
    listed = index.get("presets") if index else None
    items = [
        item
        for item in (listed if isinstance(listed, list) else [])
        if isinstance(item, dict) and isinstance(item.get("preset"), str)
    ]
    items.sort(key=lambda item: -_count(item, "node_count"))
    return [str(item["preset"]) for item in items]


def _rows(document: dict[str, object] | None) -> list[dict[str, object]]:
    listed = document.get("nodes") if document else None
    return [row for row in listed if isinstance(row, dict)] if isinstance(listed, list) else []


def _count(row: dict[str, object], key: str) -> int:
    value = row.get(key)
    return value if isinstance(value, int) else 0


def _node(row: dict[str, object]) -> dict[str, object]:
    return {"node_id": row.get("node_id"), "display_name": row.get("display_name")}


def _reachable_board(rows: list[dict[str, object]], window: object) -> dict[str, object]:
    """Heard over the air in the most of the hours it was awake."""
    ranked = []
    for row in rows:
        awake = _count(row, "active_hours")
        if awake < MIN_AWAKE_HOURS:
            continue
        heard = _count(row, "rf_hours")
        ranked.append((heard / awake, awake, row))
    ranked.sort(key=lambda item: (-item[0], -item[1], str(item[2].get("node_id"))))
    return {
        "key": "reachable",
        "title": "Most consistently reachable",
        "measure": "The share of the hours it was awake in which something on the air heard it.",
        "window_hours": window,
        "cannot_know": (
            "Only gateways report, so an hour in which only other nodes heard it counts as "
            f"not heard. A node awake for fewer than {MIN_AWAKE_HOURS} hours is not ranked."
        ),
        "rows": [
            _node(row)
            | {
                "value": round(ratio * 100, 1),
                "unit": "%",
                "detail": f"{_count(row, 'rf_hours')} of {awake} hours",
            }
            for ratio, awake, row in ranked[:BOARD_SIZE]
        ],
    }


def _direct_board(rows: list[dict[str, object]], window: object) -> dict[str, object]:
    """Heard directly by the most gateways."""
    ranked = [row for row in rows if _count(row, "direct_gateways") > 0]
    ranked.sort(key=lambda row: (-_count(row, "direct_gateways"), str(row.get("node_id"))))
    return {
        "key": "direct_gateways",
        "title": "Heard directly by the most gateways",
        "measure": (
            "Distinct gateways that heard it with no hop used, never counting its own upload."
        ),
        "window_hours": window,
        "cannot_know": (
            "Only gateways are counted. A node that many ordinary nodes hear, and few "
            "gateways, does real work that this board cannot see."
        ),
        "rows": [
            _node(row)
            | {
                "value": _count(row, "direct_gateways"),
                "unit": "gateway" if _count(row, "direct_gateways") == 1 else "gateways",
                "detail": f"{_count(row, 'packets')} packets",
            }
            for row in ranked[:BOARD_SIZE]
        ],
    }


async def _link_board(session: AsyncSession, preset: str, margin_db: float) -> dict[str, object]:
    """The longest links measured both ways with a healthy margin.

    The link evidence is the graph page's, read through the graph's own
    functions, so a link on this board is one the graph draws solid.
    """
    modem = preset_for_channel(preset)
    required = required_snr_db(modem) if modem else 0.0
    since = datetime.now(UTC) - timedelta(hours=LINK_WINDOW_HOURS)
    edges = await _traceroute_edges(session, since, LINK_ROW_LIMIT, preset)
    neighbours = await _neighbor_edges(session, since, LINK_ROW_LIMIT, preset)
    for edge in neighbours.values():
        _merge(edges, edge)

    strong: list[Edge] = [
        edge
        for edge in edges.values()
        if edge.strength == TWO_WAY and edge.snr is not None and edge.snr - required >= margin_db
    ]
    ends = {end for edge in strong for end in (edge.source, edge.target)}
    positions = await exact_positions(session, ends)
    placed: list[tuple[float, Edge]] = []
    for edge in strong:
        one, two = positions.get(edge.source), positions.get(edge.target)
        if one is None or two is None:
            continue
        placed.append((float(distance_km(one[0], one[1], two[0], two[1])), edge))
    placed.sort(key=lambda item: -item[0])
    top = placed[:BOARD_SIZE]
    names = await resolve_names(
        session, {end for _, edge in top for end in (edge.source, edge.target)}
    )
    return {
        "key": "longest_link",
        "title": "Longest reliable link",
        "measure": (
            f"Distance between two nodes that heard each other both ways, with a signal at "
            f"least {margin_db:g} dB above what {preset} needs."
        ),
        "window_hours": LINK_WINDOW_HOURS,
        "cannot_know": (
            "Both ends need an exact position, and a link needs reports in both directions, "
            "so a real long link that only one side reports is missing. "
            f"At most the newest {LINK_ROW_LIMIT} reports of each kind are read."
        ),
        "rows": [
            {
                "node_id": format_node_id(edge.source),
                "display_name": name_of(names, edge.source),
                "other_id": format_node_id(edge.target),
                "other_name": name_of(names, edge.target),
                "value": round(distance, 1),
                "unit": "km",
                "detail": f"{edge.snr:.1f} dB, {edge.forward} and {edge.backward} reports each way",
            }
            for distance, edge in top
        ],
    }
