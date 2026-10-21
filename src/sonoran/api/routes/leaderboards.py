"""Leaderboards that reward what helps the mesh (#60).

A shared-airtime mesh is harmed by the behaviour a packet count
celebrates, so none of these boards counts packets. Each one rewards
something that makes the mesh work better for other people:

- `reachable`: the share of traceroutes sent to it that it answered
  (#293). It asks whether traffic sent TO a node arrives and comes back,
  which is what "reachable" means on a mesh. Being awake is not enough.
- `direct_gateways`: heard directly, with no hop, by the most gateways.
  A node many radios can hear is doing infrastructure work.
- `longest_link`: the longest link measured in both directions with a
  healthy signal margin. Measured, never claimed.

The first two read the counts the gaps job already wrote, so they
compute nothing and cannot disagree with the gaps page. The ranking is
one `ORDER BY ... LIMIT` on the stored rows (#351), with the names read
live from `node`. They follow the Statistics range (#294): the job
writes their counts for 24 h, 7 d and 30 d, and `_gaps_window` picks the
one the page asked for. A custom range has no run, and those boards then
say they hold another window.

The third reads the same link evidence as the graph page, through the
same functions, and is held for a while because it is the expensive one.

Every board states its window, what it measures, and what it cannot
know. A board that does not say what it cannot see is an argument, not
a measurement.
"""

from datetime import UTC, datetime, timedelta
from math import sqrt

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from sonoran import read_models
from sonoran.api.cache import KeyedCache
from sonoran.api.dependencies import get_session
from sonoran.api.names import format_node_id, name_of, resolve_names
from sonoran.api.routes.graph import (
    TWO_WAY,
    Edge,
    _key,
    _merge,
    _neighbor_edges,
    _traceroute_edges,
)
from sonoran.api.routes.node_page import exact_positions
from sonoran.api.window import Window, optional_window
from sonoran.config import Settings
from sonoran.gaps import boards as gaps_boards
from sonoran.gaps import store as gaps_store
from sonoran.gaps.siting import distance_km
from sonoran.radio.presets import modelled, preset_for_channel, required_snr_db
from sonoran.read_models import read_links

router = APIRouter(prefix="/api/stats", tags=["stats"])

# How many rows each board shows.
BOARD_SIZE = 10

# The window the link board reads.
#
# There is no row cap any more. There was one, of 10,000 of each kind,
# and 72 h of MediumFast already held 9,577 neighbour and 9,332
# traceroute rows -- 96% of it. Crossing that would have started
# demoting links off the board for having too little evidence, when
# the evidence was there and simply had not been read. See the note in
# `graph.mesh_graph` and AGENTS.md 9.19; reading the whole window is
# 24 ms at 168 h on production, so the cap bought nothing.
LINK_WINDOW_HOURS = 72

# How long a link board is held. The graph evidence behind it changes
# slowly, and reading three days of it is the heaviest thing here.
LINK_CACHE_SECONDS = 900.0

# The fewest traceroutes, and the fewest distinct nodes sending them,
# before the reachable board ranks a node (#293). Below ten, one lost
# answer moves a share by more than ten points. One sender is one
# vantage point: its own path to the node would decide the whole score.
MIN_TRACES = 10
MIN_SENDERS = 2

# The z score of a two-sided 95 percent interval. The reachable board
# ranks by the low end of the Wilson interval, so that 95 of 100 ranks
# above 10 of 10: the second is the better share and the weaker evidence.
WILSON_Z = 1.96

#: One link board for each preset and window. Keyed and capped: the
#: preset is already normalised below, and the window comes from the
#: Statistics range (#294), so a caller varying it cannot grow this
#: without limit.
_link_caches: KeyedCache[dict[str, object]] = KeyedCache(capacity=32)


@router.get("/leaderboards")
async def leaderboards(
    request: Request,
    channel: str | None = None,
    span: Window | None = Depends(optional_window),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    """Return the boards for one modem preset.

    One preset at a time, as everywhere else: a node on one preset
    cannot hear a node on another (AGENTS.md 9.7). Without `channel` the
    first preset the gaps job assessed is used.

    A window (`hours`, or `since` and `until`) moves the link board to
    it (#294). The two boards read from the gaps job follow it when the
    job wrote that window, which it does for the page's quick ranges.
    Every board states its window and `follows_window`, so the page can
    say which boards follow its range and which do not.
    """
    settings: Settings = request.app.state.settings
    presets = await _assessed_presets(session, settings)
    asked = channel if channel is not None else (presets[0] if presets else None)
    modem = preset_for_channel(asked)
    if asked is None or modem is None:
        return {
            "available": False,
            "reason": "not_a_preset" if asked else "no_assessment",
            "presets": presets,
            "boards": [],
        }
    # The resolved preset, never the caller's spelling of it.
    #
    # `preset_for_channel` normalises by stripping every non-alphanumeric
    # character, so `l.o.n.g.f.a.s.t` and `--LoNg----FaSt--` both resolve
    # to LongFast -- and both used to be echoed back verbatim as
    # `preset` and used as the key of a module-global cache that is
    # never evicted. So a caller could mint unbounded cache entries, and
    # miss the 900-second hold on every one of them, which is exactly
    # the expensive read that hold exists for.
    preset = modem.name
    document = await gaps_store.read_summary(session, preset)
    held, window, follows = await _gaps_window(session, settings, preset, document, span)

    if document is None:
        answers: list[dict[str, object]] | None = []
        rows: list[dict[str, object]] = []
    else:
        answers = await gaps_store.trace_answers(session, preset, held)
        rows = await gaps_store.top_direct(session, preset, held, BOARD_SIZE)
    boards: list[dict[str, object]] = [
        _reachable_board(answers, window, follows),
        _direct_board(rows, window, follows),
    ]
    boards.append(
        await _link_caches.get(
            f"{preset}:{span.key if span else ''}",
            LINK_CACHE_SECONDS,
            lambda: _link_board(session, preset, settings.gaps_margin_bad_db, span),
        )
    )
    return {
        "available": True,
        "preset": preset,
        "presets": presets,
        "assessed": document is not None,
        "boards": boards,
    }


async def _assessed_presets(session: AsyncSession, settings: Settings) -> list[str]:
    """Return the assessed presets, the deployment's own one first.

    The ordering moved to `gaps_store.assessed_presets` so the gaps page
    can share it: it had this fix and the gaps page did not, which is
    exactly the drift a second copy of a sort produces.
    """
    return [str(item["preset"]) for item in await gaps_store.assessed_presets(session, settings)]


async def _gaps_window(
    session: AsyncSession,
    settings: Settings,
    preset: str,
    document: dict[str, object] | None,
    span: Window | None,
) -> tuple[int | None, object, bool]:
    """Return the gaps run the two boards rank, its window, and whether it is the range.

    The run is None for the assessment, or the window a page asked for,
    for a board run (#294). In order:

    1. No assessment: nothing, as before. A board run never stands in
       for a preset the job did not assess.
    2. A quick range the assessment holds: the assessment. That is 7 d
       by default.
    3. A quick range with a board run: that run.
    4. Anything else -- a custom range, an `hours` that is not a quick
       range, a run the job has not written yet: the assessment, and
       `follows` is false so the page says "not the page range".

    `follows` is true only when the window held is the window asked
    for. A 30 d run that retention cut to 14 days does not follow.
    """
    own = document.get("window_hours") if document else None
    if document is None:
        return None, own, False
    asked = _quick_range(span)
    if asked is None:
        return None, own, False
    if own == gaps_boards.window_hours(settings, asked):
        return None, own, own == asked
    held = await gaps_store.read_board_summary(session, preset, asked)
    if held is None:
        return None, own, False
    window = held.get("window_hours")
    return asked, window, window == asked


def _quick_range(span: Window | None) -> int | None:
    """Return the page's quick range a window is, or None.

    Only a rolling window ends now, so only `hours` can match. The key is
    the request's own words, `h168` for `hours=168`.
    """
    if span is None:
        return None
    for hours in gaps_boards.BOARD_WINDOW_HOURS:
        if span.key == f"h{hours}":
            return hours
    return None


def _count(row: dict[str, object], key: str) -> int:
    value = row.get(key)
    return value if isinstance(value, int) else 0


def _node(row: dict[str, object]) -> dict[str, object]:
    return {"node_id": row.get("node_id"), "display_name": row.get("display_name")}


def wilson_lower(answered: int, asked: int, z: float = WILSON_Z) -> float:
    """Return the low end of the Wilson score interval for a share.

    It is the share, pulled down by how little evidence there is. Ten of
    ten gives 0.72 and ninety-five of a hundred gives 0.89.
    """
    if asked <= 0:
        return 0.0
    share = answered / asked
    z2 = z * z
    centre = share + z2 / (2 * asked)
    spread = z * sqrt(share * (1 - share) / asked + z2 / (4 * asked * asked))
    return max(0.0, (centre - spread) / (1 + z2 / asked))


def _reachable_board(
    answers: list[dict[str, object]] | None, window: object, follows: bool = False
) -> dict[str, object]:
    """The share of traceroutes sent to a node that it answered (#293).

    The whole of this board's measure lives here, for every window. The
    gaps job writes every node that was traced, with its traceroutes,
    its answers and its distinct senders, and this applies the floor, so
    the board can say how many it left out.

    Ranked by the low end of the Wilson interval, then the share, then
    the number of traceroutes. The value shown is the plain share.
    """
    ranked = []
    left_out = 0
    for row in answers or []:
        asked = _count(row, "requests")
        if asked <= 0:
            continue
        if asked < MIN_TRACES or _count(row, "senders") < MIN_SENDERS:
            left_out += 1
            continue
        answered = min(_count(row, "answered"), asked)
        ranked.append((wilson_lower(answered, asked), answered / asked, asked, answered, row))
    ranked.sort(key=lambda item: (-item[0], -item[1], -item[2], str(item[4].get("node_id"))))

    measure = (
        "The share of traceroutes sent to it by other nodes that it answered. Ranked "
        "so that a share from more traceroutes counts for more."
    )
    if answers is None:
        measure += " The gaps job has not counted traceroute answers for this window yet."
    elif left_out:
        measure += (
            f" {left_out} traced {'node is' if left_out == 1 else 'nodes are'} not ranked: "
            f"fewer than {MIN_TRACES} traceroutes, or fewer than {MIN_SENDERS} senders."
        )
    return {
        "key": "reachable",
        "title": "Most reliably answers traceroutes",
        "measure": measure,
        "window_hours": window,
        "follows_window": follows,
        "not_ranked": left_out,
        "cannot_know": (
            "Only traceroutes and answers that a gateway uploaded are seen. An answer no "
            "gateway heard counts as unanswered, so unanswered means unanswered as far as we "
            "can tell. A node that nobody traceroutes is not on this board, and people choose "
            "which nodes they trace. A traceroute from the last 15 minutes is not counted yet. "
            f"A node with fewer than {MIN_TRACES} traceroutes, or fewer than {MIN_SENDERS} "
            "nodes sending them, is not ranked."
        ),
        "rows": [
            _node(row)
            | {
                "value": round(share * 100, 1),
                "unit": "%",
                "detail": (
                    f"{answered} of {asked} answered, {_count(row, 'senders')} "
                    f"{'sender' if _count(row, 'senders') == 1 else 'senders'}"
                ),
            }
            for _, share, asked, answered, row in ranked[:BOARD_SIZE]
        ],
    }


def _direct_board(
    rows: list[dict[str, object]], window: object, follows: bool = False
) -> dict[str, object]:
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
        "follows_window": follows,
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


async def _link_board(
    session: AsyncSession, preset: str, margin_db: float, window: Window | None = None
) -> dict[str, object]:
    """The longest links measured both ways with a healthy margin.

    The link evidence is the graph page's, read through the graph's own
    functions, so a link on this board is one the graph draws solid.
    Without a window it reads the last `LINK_WINDOW_HOURS`.
    """
    # A preset with no modelled sensitivity (#362) has no required SNR,
    # so no link on it can be shown to clear a margin. It used to be read
    # as 0 dB, which is a margin made up for it.
    modem = modelled(preset_for_channel(preset))
    required = required_snr_db(modem) if modem else None
    if window is None:
        since = datetime.now(UTC) - timedelta(hours=LINK_WINDOW_HOURS)
        until = None
        window_hours: float = LINK_WINDOW_HOURS
    else:
        since, until, window_hours = window.start, window.end, round(window.hours, 2)

    # The jobs service's build when one is fresh for this window (#371).
    # Reading 30 days of link evidence here took 11.6 s. Positions,
    # distances and names below are read now either way.
    rolling = LINK_WINDOW_HOURS if window is None else _rolling_hours(window)
    stored = None
    if rolling in read_models.BOARD_HOURS:
        stored = await read_links(session, preset, rolling)
    built_at = datetime.now(UTC) if stored is None else stored.built_at
    if stored is not None:
        edges = {_key(edge.source, edge.target): edge for edge in stored.edges}
    else:
        edges = await _traceroute_edges(session, since, preset, until)
        neighbours = await _neighbor_edges(session, since, preset, until)
        for edge in neighbours.values():
            _merge(edges, edge)

    strong: list[Edge] = [
        edge
        for edge in edges.values()
        if required is not None
        and edge.strength == TWO_WAY
        and edge.snr is not None
        and edge.snr - required >= margin_db
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
        "window_hours": window_hours,
        # Says that this board follows the range the page asked for.
        "follows_window": window is not None,
        # When the links were measured: a stored build is a few minutes old.
        "built_at": built_at,
        "cannot_know": (
            "Both ends need an exact position, and a link needs reports in both directions, "
            "so a real long link that only one side reports is missing."
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


def _rolling_hours(window: Window) -> int | None:
    """The hours of a rolling window (`hours=N`), or None for a fixed range."""
    key = window.key
    if key.startswith("h") and key[1:].isdigit():
        return int(key[1:])
    return None
