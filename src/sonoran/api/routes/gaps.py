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

from fastapi import APIRouter, Query, Request

from sonoran.config import Settings
from sonoran.gaps import store
from sonoran.gaps.signals import BAD, OK, UNKNOWN
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

# preset -> (when it was read, what the file looked like, the document)
_cache: dict[str, tuple[float, tuple[int, int], dict[str, object]]] = {}


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
    path = store.preset_path(settings, preset)
    if path is None:
        return None
    try:
        stat = path.stat()
    except OSError:
        # Gone, or unreadable. Say so at once rather than from memory.
        _cache.pop(preset, None)
        return None

    mark = (stat.st_mtime_ns, stat.st_size)
    now = time.monotonic()
    held = _cache.get(preset)
    if held is not None and held[1] == mark and now - held[0] < CACHE_SECONDS:
        return held[2]

    document = store.read_preset(settings, preset)
    if document is None:
        _cache.pop(preset, None)
        return None
    _cache[preset] = (now, mark, document)
    return document


def _presets(settings: Settings) -> list[dict[str, object]]:
    """Return the presets that have an assessment, for the picker."""
    index = store.read_index(settings)
    if index is None:
        return []
    listed = index.get("presets")
    return [item for item in listed if isinstance(item, dict)] if isinstance(listed, list) else []


def _resolve(channel: str | None, settings: Settings) -> tuple[str | None, str | None]:
    """Return the preset to serve, and the reason when there is none.

    A channel that names no modem preset is refused rather than guessed
    at. Weather and PKI ride on top of a preset and do not name one, and
    putting such traffic on the wrong preset would describe a radio
    setting nobody is using. See `AGENTS.md` 9.7.
    """
    if channel is None:
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
