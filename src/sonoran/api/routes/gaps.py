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

import base64
import binascii
import json

from fastapi import APIRouter, Depends, HTTPException, Query, Request
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


def page_cursor(stamp: str, after: int) -> str:
    """Return the opaque cursor of the next page of one run.

    It names the run (`stamp`, when the job made it) and the place in
    it (`after`: the rank of a node, or the position of a candidate).
    """
    raw = json.dumps({"run": stamp, "after": after}, separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def read_cursor(cursor: str | None, stamp: str | None) -> int | None:
    """Return the place a cursor names, or None for the first page.

    A cursor that is not one is a bad request (422). A cursor from an
    older run is refused (409): the job rewrites the run every half
    hour, and a page that mixed two runs would list a node twice or
    not at all, with nothing to show it.
    """
    if cursor is None:
        return None
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        held = json.loads(base64.urlsafe_b64decode(padded.encode()))
        run, after = held["run"], held["after"]
    except (binascii.Error, ValueError, KeyError, TypeError) as error:
        raise HTTPException(status_code=422, detail="not a cursor") from error
    if not isinstance(run, str) or not isinstance(after, int) or isinstance(after, bool):
        raise HTTPException(status_code=422, detail="not a cursor")
    if run != stamp:
        raise HTTPException(
            status_code=409,
            detail="the run was rewritten since the first page; start again without a cursor",
        )
    return after


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
    cursor: str | None = Query(default=None, max_length=256),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    """Return the assessed nodes of one preset, worst first, a page at a time.

    The order is set by the job, once, and stored as each row's `rank`,
    so that every reader gets the same one and no page holds a copy of
    the ranking rule. It is `bad_count`, then a fixed severity order
    between the signals, then the packet count. **It is not a score, and
    a row's colour comes from `worst_state` and never from a number.**

    `signal` and `state` filter the stored rows, in SQL. They select;
    they never recompute.

    **Paging is by cursor.** An answer with more rows after it carries
    `next_cursor`; pass it back as `cursor`, with the same filters, for
    the next page. A cursor names its run and is refused (409) once the
    job has written a new one.
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

    stamp = await store.run_stamp(session, preset)
    after = read_cursor(cursor, stamp)
    matched, rows, following = await store.node_rows(session, preset, signal, state, limit, after)
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
        "next_cursor": (
            page_cursor(stamp, following) if stamp is not None and following is not None else None
        ),
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
    cursor: str | None = Query(default=None, max_length=256),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    """Return the places a node could go, best first inside each area, a page at a time.

    Every row carries `method`. `terrain_screen` is a cheap ranking and
    **not a prediction**; `splat` is the engine, and only those rows
    carry `newly_usable`. Nothing here may be read as a promise: the
    caveats travel with the answer and name what a siting suggestion
    cannot know at all.

    `newly_usable` is **null** and never zero for a candidate whose
    state is `unknown`. A candidate standing on ground we hold no
    terrain for has not been judged, and "no benefit" is a different
    answer.

    Paging is by cursor, as for `/api/gaps/nodes`.
    """
    settings: Settings = request.app.state.settings
    preset, reason = await _resolve(session, channel, settings)
    if preset is None:
        return await _no_siting(session, reason or "no_assessment", settings)
    summary = await store.read_siting(session, preset)
    if summary is None:
        return await _no_siting(session, "no_siting_run", settings)

    stamp = await store.siting_stamp(session, preset)
    after = read_cursor(cursor, stamp)
    matched, rows, following = await store.read_candidates(session, preset, area, limit, after)
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
        "next_cursor": (
            page_cursor(stamp, following) if stamp is not None and following is not None else None
        ),
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
