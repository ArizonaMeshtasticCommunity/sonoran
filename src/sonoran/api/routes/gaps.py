"""Read-only coverage gap endpoints.

**These routes read the rows the gaps job wrote and nothing else.**
They compute no signal (#351). A request that ran the gap queries would
be heavier than the one `docs/ISSUES.md` 2.9 already warns about, and
the map refreshes that one every 15 seconds. What they do run is a
select by key, with the filters and the limit in SQL.

`available: false` is a working state, not an error, exactly as
`/api/coverage` treats a missing run. The page then says the assessment
has not been made yet.

**Nothing here may ever reach the public embed.** A list of weak nodes
with positions is a list of houses with a reason to visit them, and it
is a worse leak than the one `AGENTS.md` 9.25 already guards against.
There is no route under `/api/embed` for any of this, and
`test_the_embed_can_never_see_the_gaps_feature` enumerates the embed
router to keep it that way.
"""

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from sonoran.api.dependencies import get_session
from sonoran.config import Settings
from sonoran.gaps import store
from sonoran.gaps.signals import BAD, OK, SIGNAL_UNIT_LABELS, UNKNOWN, signal_key
from sonoran.gaps.siting import SITING_CAVEATS
from sonoran.radio.presets import preset_for_channel

router = APIRouter(prefix="/api/gaps", tags=["gaps"])

# The filter values a request may ask for.
STATES = (BAD, OK, UNKNOWN)


async def _presets(session: AsyncSession, settings: Settings) -> list[dict[str, object]]:
    """Return the presets that have an assessment, for the picker.

    Ordered by `store.assessed_presets`, so the deployment's own preset
    is first in the picker as well as selected.
    """
    return await store.assessed_presets(session, settings)


async def _resolve(
    session: AsyncSession, channel: str | None, settings: Settings
) -> tuple[str | None, str | None]:
    """Return the preset to serve, and the reason when there is none.

    A channel that names no modem preset is refused rather than guessed
    at. Weather and PKI ride on top of a preset and do not name one, and
    putting such traffic on the wrong preset would describe a radio
    setting nobody is using. See `AGENTS.md` 9.7.
    """
    if channel is None:
        # `_presets` puts `settings.default_preset` first when it was
        # assessed (#177), so the first entry IS the deployment's preset
        # rather than whichever one sorted first alphabetically. This
        # used to take the index in its written order, which is channel
        # NAME order -- "LongFast" above "MediumFast" -- so the page
        # opened on a preset this mesh does not run.
        listed = await _presets(session, settings)
        if not listed:
            return None, "no_assessment"
        first = listed[0].get("preset")
        return (first, None) if isinstance(first, str) else (None, "no_assessment")
    preset = preset_for_channel(channel)
    if preset is None:
        return None, "not_a_preset"
    return preset.name, None


async def _unavailable(session: AsyncSession, reason: str, settings: Settings) -> dict[str, object]:
    """Return the working "there is nothing to show" answer."""
    return {
        "available": False,
        "reason": reason,
        "presets": await _presets(session, settings),
        "signals": {},
        "nodes": [],
    }


@router.get("")
async def gaps_summary(
    request: Request,
    channel: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    """Return the counts for one preset, and what they cannot tell you.

    Every signal carries three counts: `bad`, `ok` and `unknown`. The
    `unknown` count is part of the answer and is never hidden. A node
    that reports nothing may be switched off rather than in trouble, and
    this is where that is said out loud.

    `hours` is not a parameter. The window is whatever the job measured
    and it is echoed back as `window_hours`, because the job holds one
    window and a request cannot ask for another without recomputing.
    """
    settings: Settings = request.app.state.settings
    preset, reason = await _resolve(session, channel, settings)
    if preset is None:
        return await _unavailable(session, reason or "no_assessment", settings)
    # Everything except the node rows, which have their own endpoint, and
    # the leaderboard's traceroute counts (#293), which this page never
    # reads. Both are in their own tables, so the summary holds neither.
    summary = await store.read_summary(session, preset)
    if summary is None:
        return await _unavailable(session, "no_assessment", settings)
    thresholds = summary.get("thresholds")
    return {
        **summary,
        "presets": await _presets(session, settings),
        # What each column's number is measured in, and what each column
        # means for a newcomer (#265). Both are definitions, so they come
        # from `gaps/signals.py` as it is now rather than from the run,
        # and an assessment written before they existed still gets a key.
        # The unit of each VALUE is different: it rides on the signal in
        # the row, because it belongs to the number the job wrote.
        "signal_units": dict(SIGNAL_UNIT_LABELS),
        "signal_key": signal_key(thresholds if isinstance(thresholds, dict) else {}),
    }


@router.get("/nodes")
async def gaps_nodes(
    request: Request,
    channel: str | None = None,
    signal: str | None = None,
    state: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    """Return the assessed nodes of one preset, worst first.

    The order is set by the job, once, and stored as each row's `rank`,
    so that every reader gets the same one and no page holds a copy of
    the ranking rule. It is `bad_count`, then a fixed severity order
    between the signals, then the packet count. **It is not a score, and
    a row's colour comes from `worst_state` and never from a number.**

    `signal` and `state` filter the stored rows, in SQL. They select;
    they never recompute.
    """
    settings: Settings = request.app.state.settings
    preset, reason = await _resolve(session, channel, settings)
    if preset is None:
        return await _unavailable(session, reason or "no_assessment", settings)
    summary = await store.read_summary(session, preset)
    if summary is None:
        return await _unavailable(session, "no_assessment", settings)

    order = summary.get("signal_order")
    known = [name for name in order if isinstance(name, str)] if isinstance(order, list) else []

    if signal is not None and signal not in known:
        return {
            "available": False,
            "reason": "not_a_signal",
            "preset": preset,
            "signal_order": known,
            "nodes": [],
        }
    if state is not None and state not in STATES:
        return {
            "available": False,
            "reason": "not_a_state",
            "preset": preset,
            "states": list(STATES),
            "nodes": [],
        }

    matched, rows = await store.node_rows(session, preset, signal, state, limit)
    return {
        "available": True,
        "preset": preset,
        "window_hours": summary.get("window_hours"),
        "generated_at": summary.get("generated_at"),
        "gateways_active": summary.get("gateways_active"),
        "signal_order": known,
        "signal_labels": summary.get("signal_labels", {}),
        "matched_count": matched,
        "limit": limit,
        "nodes": rows,
    }


@router.get("/areas")
async def gaps_areas(
    request: Request,
    channel: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    """Return the neighbourhoods that hold the struggling nodes.

    **This half is a measurement and the candidates are a prediction.**
    They are served from one answer because they were computed together,
    and the page must never draw them in the same colour.

    An area is a group of at least `GAPS_MIN_CLUSTER` places that want
    help, joined by single linkage. A group of one or two is not an
    area; it is a node, and `/api/gaps/nodes` already holds it.

    `available: false` is a working state. The siting half runs inside
    the coverage cycle, so a deployment that has never finished a
    coverage run has no answer yet.
    """
    settings: Settings = request.app.state.settings
    preset, reason = await _resolve(session, channel, settings)
    if preset is None:
        return await _no_siting(session, reason or "no_assessment", settings)
    summary = await store.read_siting(session, preset)
    if summary is None:
        return await _no_siting(session, "no_siting_run", settings)
    return summary | {"presets": await _presets(session, settings)}


@router.get("/candidates")
async def gaps_candidates(
    request: Request,
    channel: str | None = None,
    area: int | None = Query(default=None, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    """Return the places a node could go, best first inside each area.

    Every row carries `method`. `terrain_screen` is a cheap ranking and
    **not a prediction**; `splat` is the engine, and only those rows
    carry `newly_usable`. Nothing here may be read as a promise: the
    caveats travel with the answer and name what a siting suggestion
    cannot know at all.

    `newly_usable` is **null** and never zero for a candidate whose
    state is `unknown`. A candidate standing on ground we hold no
    terrain for has not been judged, and "no benefit" is a different
    answer.
    """
    settings: Settings = request.app.state.settings
    preset, reason = await _resolve(session, channel, settings)
    if preset is None:
        return await _no_siting(session, reason or "no_assessment", settings)
    summary = await store.read_siting(session, preset)
    if summary is None:
        return await _no_siting(session, "no_siting_run", settings)

    matched, rows = await store.read_candidates(session, preset, area, limit)
    return {
        "available": True,
        "preset": preset,
        "area": area,
        "generated_at": summary.get("generated_at"),
        "assumed_radio": summary.get("assumed_radio"),
        "coverage": summary.get("coverage"),
        "caveats": summary.get("caveats", []),
        "matched_count": matched,
        "limit": limit,
        "candidates": rows,
    }


async def _no_siting(session: AsyncSession, reason: str, settings: Settings) -> dict[str, object]:
    """Return the working "no siting answer yet" response.

    The caveats are served even when there is nothing to site, because
    they are what the feature cannot know and that does not depend on
    whether it has run.
    """
    return {
        "available": False,
        "reason": reason,
        "presets": await _presets(session, settings),
        "areas": [],
        "candidates": [],
        "caveats": [{"key": key, "text": text} for key, text in SITING_CAVEATS],
    }
