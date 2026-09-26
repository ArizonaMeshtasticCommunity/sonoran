"""Read-only coverage gap endpoints.

**These routes read the artefact the gaps job wrote and nothing else.**
They open no database session and they compute no signal. A request that
ran the gap queries would be heavier than the one `docs/ISSUES.md` 2.9
already warns about, and the map refreshes that one every 15 seconds.

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

import time
from collections.abc import Callable
from pathlib import Path

from fastapi import APIRouter, Query, Request

from sonoran.config import Settings
from sonoran.gaps import store
from sonoran.gaps.signals import BAD, OK, UNKNOWN
from sonoran.gaps.siting import SITING_CAVEATS
from sonoran.radio.presets import preset_for_channel

router = APIRouter(prefix="/api/gaps", tags=["gaps"])

# How long a served answer is held in the process.
#
# The artefact is rewritten every `GAPS_INTERVAL_MINUTES`, which is 30
# by default, so a short cache costs no freshness worth having and saves
# reading and parsing a file on every request. This is the convention
# `api/routes/embed.py` uses. `/api/coverage` reads its manifest from
# disk on every request with no cache at all; that is not the example to
# follow.
#
# JSON endpoints in this project set no `Cache-Control` and no `ETag`.
CACHE_SECONDS = 30.0

# The filter values a request may ask for.
STATES = (BAD, OK, UNKNOWN)

# key -> (when it was read, what the file looked like, the document)
#
# The key is the preset for the per node assessment and `siting:` plus
# the preset for the siting answer. The two files are written by
# different jobs on different clocks, so they are held apart.
_cache: dict[str, tuple[float, tuple[int, int], dict[str, object]]] = {}


def _read_siting(settings: Settings, preset: str) -> dict[str, object] | None:
    """Return one preset's siting answer, cached the same way.

    The siting answer is rewritten once a coverage cycle, which is every
    six hours by default, so the file check does nearly all of the work
    and the timer does almost none.
    """
    return _read_file(
        f"siting:{preset}",
        store.siting_path(settings, preset),
        lambda: store.read_siting(settings, preset),
    )


def _read(settings: Settings, preset: str) -> dict[str, object] | None:
    """Return one preset's assessment, from the cache when it is still true.

    The cache holds the **parsed** document, which is the expensive part,
    and checks the file on every request, which is not. A cache that
    trusted a timer alone would go on serving an assessment after the
    file was removed, and would serve a stale one for up to
    `CACHE_SECONDS` after the job rewrote it. Both are a cache answering
    a question about the world from memory, which is the thing a cache
    must not do here: this endpoint's whole contract is that it reports
    what is on disk.

    `st_mtime_ns` and `st_size` together change whenever the job writes,
    because the job writes to a temporary name and renames over the old
    file. A rename gives a new inode and a new timestamp.
    """
    return _read_file(
        preset,
        store.preset_path(settings, preset),
        lambda: store.read_preset(settings, preset),
    )


def read_assessment(settings: Settings, preset: str) -> dict[str, object] | None:
    """Return one preset's assessment for another route to read.

    The node page reads the same rows through the same cache, so the
    two pages cannot hold different copies of one node's findings.
    """
    return _read(settings, preset)


def _read_file(
    key: str,
    path: Path | None,
    load: Callable[[], dict[str, object] | None],
) -> dict[str, object] | None:
    """Return one artefact, from the cache when the cache is still true."""
    if path is None:
        return None
    try:
        stat = path.stat()
    except OSError:
        # Gone, or unreadable. Say so at once rather than from memory.
        _cache.pop(key, None)
        return None

    mark = (stat.st_mtime_ns, stat.st_size)
    now = time.monotonic()
    held = _cache.get(key)
    if held is not None and held[1] == mark and now - held[0] < CACHE_SECONDS:
        return held[2]

    document = load()
    if document is None:
        _cache.pop(key, None)
        return None
    _cache[key] = (now, mark, document)
    return document


def _presets(settings: Settings) -> list[dict[str, object]]:
    """Return the presets that have an assessment, for the picker.

    Ordered by `store.assessed_presets`, so the deployment's own preset
    is first in the picker as well as selected.
    """
    return store.assessed_presets(settings)


def _resolve(channel: str | None, settings: Settings) -> tuple[str | None, str | None]:
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
        listed = _presets(settings)
        if not listed:
            return None, "no_assessment"
        first = listed[0].get("preset")
        return (first, None) if isinstance(first, str) else (None, "no_assessment")
    preset = preset_for_channel(channel)
    if preset is None:
        return None, "not_a_preset"
    return preset.name, None


def _unavailable(reason: str, settings: Settings) -> dict[str, object]:
    """Return the working "there is nothing to show" answer."""
    return {
        "available": False,
        "reason": reason,
        "presets": _presets(settings),
        "signals": {},
        "nodes": [],
    }


@router.get("")
async def gaps_summary(
    request: Request,
    channel: str | None = None,
) -> dict[str, object]:
    """Return the counts for one preset, and what they cannot tell you.

    Every signal carries three counts: `bad`, `ok` and `unknown`. The
    `unknown` count is part of the answer and is never hidden. A node
    that reports nothing may be switched off rather than in trouble, and
    this is where that is said out loud.

    `hours` is not a parameter. The window is whatever the job measured
    and it is echoed back as `window_hours`, because the artefact holds
    one window and a request cannot ask for another without recomputing.
    """
    settings: Settings = request.app.state.settings
    preset, reason = _resolve(channel, settings)
    if preset is None:
        return _unavailable(reason or "no_assessment", settings)
    document = _read(settings, preset)
    if document is None:
        return _unavailable("no_assessment", settings)

    # Everything except the node rows, which have their own endpoint.
    summary = {key: value for key, value in document.items() if key != "nodes"}
    return {**summary, "presets": _presets(settings)}


@router.get("/nodes")
async def gaps_nodes(
    request: Request,
    channel: str | None = None,
    signal: str | None = None,
    state: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
) -> dict[str, object]:
    """Return the assessed nodes of one preset, worst first.

    The order is set by the job, once, so that every reader gets the
    same one and no page holds a copy of the ranking rule. It is
    `bad_count`, then a fixed severity order between the signals, then
    the packet count. **It is not a score, and a row's colour comes from
    `worst_state` and never from a number.**

    `signal` and `state` filter the precomputed list. They select; they
    never recompute.
    """
    settings: Settings = request.app.state.settings
    preset, reason = _resolve(channel, settings)
    if preset is None:
        return _unavailable(reason or "no_assessment", settings)
    document = _read(settings, preset)
    if document is None:
        return _unavailable("no_assessment", settings)

    listed = document.get("nodes")
    rows = [row for row in listed if isinstance(row, dict)] if isinstance(listed, list) else []
    order = document.get("signal_order")
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

    if signal is not None or state is not None:
        rows = [row for row in rows if _matches(row, signal, state)]

    return {
        "available": True,
        "preset": preset,
        "window_hours": document.get("window_hours"),
        "generated_at": document.get("generated_at"),
        "gateways_active": document.get("gateways_active"),
        "signal_order": known,
        "signal_labels": document.get("signal_labels", {}),
        "matched_count": len(rows),
        "limit": limit,
        "nodes": rows[:limit],
    }


@router.get("/areas")
async def gaps_areas(
    request: Request,
    channel: str | None = None,
) -> dict[str, object]:
    """Return the neighbourhoods that hold the struggling nodes.

    **This half is a measurement and the candidates are a prediction.**
    They are served from one file because they were computed together,
    and the page must never draw them in the same colour.

    An area is a group of at least `GAPS_MIN_CLUSTER` places that want
    help, joined by single linkage. A group of one or two is not an
    area; it is a node, and `/api/gaps/nodes` already holds it.

    `available: false` is a working state. The siting half runs inside
    the coverage cycle, so a deployment that has never finished a
    coverage run has no answer yet.
    """
    settings: Settings = request.app.state.settings
    preset, reason = _resolve(channel, settings)
    if preset is None:
        return _no_siting(reason or "no_assessment", settings)
    document = _read_siting(settings, preset)
    if document is None:
        return _no_siting("no_siting_run", settings)
    return {key: value for key, value in document.items() if key not in ("candidates",)} | {
        "presets": _presets(settings)
    }


@router.get("/candidates")
async def gaps_candidates(
    request: Request,
    channel: str | None = None,
    area: int | None = Query(default=None, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
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
    preset, reason = _resolve(channel, settings)
    if preset is None:
        return _no_siting(reason or "no_assessment", settings)
    document = _read_siting(settings, preset)
    if document is None:
        return _no_siting("no_siting_run", settings)

    listed = document.get("candidates")
    rows = [row for row in listed if isinstance(row, dict)] if isinstance(listed, list) else []
    if area is not None:
        rows = [row for row in rows if row.get("area") == area]
    return {
        "available": True,
        "preset": preset,
        "area": area,
        "generated_at": document.get("generated_at"),
        "assumed_radio": document.get("assumed_radio"),
        "coverage": document.get("coverage"),
        "caveats": document.get("caveats", []),
        "matched_count": len(rows),
        "limit": limit,
        "candidates": rows[:limit],
    }


def _no_siting(reason: str, settings: Settings) -> dict[str, object]:
    """Return the working "no siting answer yet" response.

    The caveats are served even when there is nothing to site, because
    they are what the feature cannot know and that does not depend on
    whether it has run.
    """
    return {
        "available": False,
        "reason": reason,
        "presets": _presets(settings),
        "areas": [],
        "candidates": [],
        "caveats": [{"key": key, "text": text} for key, text in SITING_CAVEATS],
    }


def _matches(row: dict[str, object], signal: str | None, state: str | None) -> bool:
    """Return true when one row passes the signal and state filters.

    With a signal and no state, any state of that signal matches. With a
    state and no signal, a row matches when **any** signal holds that
    state, which is how "show me the unknowns" is asked for.
    """
    holder = row.get("signals")
    if not isinstance(holder, dict):
        return False
    if signal is not None:
        found = holder.get(signal)
        if not isinstance(found, dict):
            return False
        return state is None or found.get("state") == state
    return any(isinstance(found, dict) and found.get("state") == state for found in holder.values())
