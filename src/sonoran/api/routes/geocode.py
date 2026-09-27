"""Turn a typed address into a coordinate, for the planner's site box.

**This is the one endpoint on this API that talks to a third party on a
reader's behalf, and the only one that carries words a reader typed.**
Everything about it below is shaped by that. Read the whole file before
changing any of it.

Why a proxy at all. `docs/design/2026-09-26-ux-overhaul.md` 6.5 asks for
an address search on the planner, and the dashboard's
Content-Security-Policy is `connect-src 'self'` plus one named host for
the firmware release check. A geocoder called from the browser would need
a third origin in that header, and it would also hand the reader's IP
address and their typed address to that geocoder directly. A proxy here
needs no CSP change at all and the geocoder sees this server, not the
reader.

What it deliberately is not:

- **Not an open geocoder.** The query is bounded to the deployment's own
  home region and answers outside it are dropped, in the same way
  `routes/terrain.py` refuses a tile outside its region so that endpoint
  cannot be a general proxy for the tile source.
- **Not a queue.** Two limits, described at `_spend` and `_politely`.
  The first stops one caller spending the budget; the second keeps this
  server inside the upstream's usage policy.
- **Not in the log.** A GET puts the address in the request line, which
  uvicorn's access log writes out, and httpx writes the outbound URL at
  INFO. `sonoran.logging.redact_access_query` takes the first off and
  `quieten_http_client` takes the second off; `api/app.py` calls both,
  next to each other. The API is GET-only by architecture (`AGENTS.md`
  4), so redaction is the answer rather than a POST body. Both were
  verified against a real lookup on a running instance, and the second
  one existed only because that measurement contradicted the comment
  written before it.

The residue, said plainly because it cannot be removed here: the address
is a key in a bounded in-memory cache for an hour, and the upstream sees
it. Nothing writes it to disk and nothing logs it.
"""

import asyncio
import logging
import time
from collections import OrderedDict, deque

import httpx
from fastapi import APIRouter, HTTPException, Query, Request

from sonoran.api.cache import KeyedCache
from sonoran.config import Settings

logger = logging.getLogger(__name__)

# httpx logs the whole outbound URL, with the address in it, at INFO.
# `sonoran.logging.quieten_http_client` raises that logger's floor, and
# `api/app.py` calls it beside the access-log redaction so the two
# mitigations live together. Measured before it was believed: the comment
# here said DEBUG, and the first live lookup printed the address at INFO.

router = APIRouter(prefix="/api/geocode", tags=["geocode"])

# The longest address this will forward.
#
# Long enough for "1234 East Camelback Road, Phoenix, Arizona" and short
# enough that a pasted paragraph is refused here rather than sent on.
QUERY_LIMIT = 120

# The shortest. Two characters is already a real place name ("Ajo" is
# three); one is a keystroke on the way to something else and would
# spend a rate-limit slot on nothing.
QUERY_FLOOR = 2

# How many answers to offer. A geocoder will happily return fifty.
RESULT_LIMIT = 5

# How long an answer is held, and how many.
#
# The upstream usage policy asks for caching rather than repeat queries,
# and a reader who mistypes and retypes the same street produces exactly
# those. `KeyedCache` is bounded and single-flight, so somebody varying
# the query pays for every request and the memory stays capped (#160).
CACHE_SECONDS = 3600.0
CACHE_ENTRIES = 128
_answers: KeyedCache[list[dict[str, object]]] = KeyedCache(capacity=CACHE_ENTRIES)

# What one client may ask for, and over what window.
#
# Ten lookups a minute is more than anybody typing an address needs and
# far less than a script wants. It is per client address, so one reader
# cannot spend the whole deployment's politeness budget below.
CLIENT_BUDGET = 10
CLIENT_WINDOW_SECONDS = 60.0

# How many clients are remembered at once.
#
# **The ceiling is the point.** A dict keyed on the caller's address
# grows once per address seen, and the caller chooses the address on a
# network that allows spoofing. Oldest-first eviction keeps it bounded;
# an evicted client gets a fresh budget, which is the honest trade -- the
# politeness limit below still holds the outbound rate whatever this
# table forgets.
CLIENT_TABLE_LIMIT = 1024
_spent: OrderedDict[str, deque[float]] = OrderedDict()

# The upstream's own rule, and the reason this is not just a per-client
# limit: Nominatim's usage policy allows at most one request a second
# from one source, whoever asked for it.
UPSTREAM_INTERVAL_SECONDS = 1.0

# The longest a request will wait for its turn at that rate.
#
# Without a ceiling, ten simultaneous callers make the tenth wait ten
# seconds holding a connection, which is how a polite limit turns into a
# denial of service against this API. Past this, the caller is told to
# come back instead.
UPSTREAM_MAX_WAIT_SECONDS = 2.0

_upstream_lock: asyncio.Lock | None = None
_upstream_lock_loop: asyncio.AbstractEventLoop | None = None
_upstream_last = 0.0


def reset_limits() -> None:
    """Forget every budget and every held answer. For tests, between cases."""
    global _upstream_last
    _spent.clear()
    _answers.clear()
    _upstream_last = 0.0


def _client(request: Request) -> str:
    """The caller, for the budget. Unknown callers share one bucket."""
    return request.client.host if request.client else "unknown"


def _spend(who: str, now: float) -> bool:
    """Take one from this client's budget. False when it is empty."""
    seen = _spent.get(who)
    if seen is None:
        seen = deque()
        _spent[who] = seen
    # Anything older than the window no longer counts against them.
    while seen and now - seen[0] > CLIENT_WINDOW_SECONDS:
        seen.popleft()
    if len(seen) >= CLIENT_BUDGET:
        # Moved to the end even on a refusal: a client hammering the
        # endpoint is the last one whose record should be evicted, or the
        # eviction itself becomes the way around the limit.
        _spent.move_to_end(who)
        return False
    seen.append(now)
    _spent.move_to_end(who)
    while len(_spent) > CLIENT_TABLE_LIMIT:
        _spent.popitem(last=False)
    return True


def _loop_lock() -> asyncio.Lock:
    """The outbound lock, made on the loop that is running now.

    Same shape as `api/cache.py`: a lock built at import time belongs to
    whichever loop existed then, and a test suite that runs each case on
    its own loop would find a lock bound to a closed one.
    """
    global _upstream_lock, _upstream_lock_loop
    running = asyncio.get_running_loop()
    if _upstream_lock is None or _upstream_lock_loop is not running:
        _upstream_lock = asyncio.Lock()
        _upstream_lock_loop = running
    return _upstream_lock


async def _politely() -> None:
    """Wait for this process's turn to call the upstream.

    Raises 429 rather than waiting longer than `UPSTREAM_MAX_WAIT_SECONDS`.
    """
    global _upstream_last
    async with _loop_lock():
        wait = UPSTREAM_INTERVAL_SECONDS - (time.monotonic() - _upstream_last)
        if wait > UPSTREAM_MAX_WAIT_SECONDS:
            raise HTTPException(
                status_code=429,
                detail="too many address lookups at once; try again in a moment",
            )
        if wait > 0:
            await asyncio.sleep(wait)
        _upstream_last = time.monotonic()


def _clean(query: str) -> str:
    """The address as it will be sent, or raise 422.

    Control characters are refused rather than stripped. A query holding
    one is not a typed address, and quietly repairing input is how a
    validator ends up disagreeing with what it validated.
    """
    text = query.strip()
    if len(text) < QUERY_FLOOR:
        raise HTTPException(status_code=422, detail="give at least two characters to search for")
    if any(character < " " or character == "\x7f" for character in text):
        raise HTTPException(status_code=422, detail="that is not an address")
    return text


def _region(settings: Settings) -> tuple[float, float, float, float]:
    """The box answers must fall inside: south, west, north, east.

    The deployment's own home region, which is also what the live map
    opens on (#195). No geography is written into this file: another mesh
    sets its four numbers and this endpoint follows them.
    """
    return (
        settings.map_home_south,
        settings.map_home_west,
        settings.map_home_north,
        settings.map_home_east,
    )


def _inside(latitude: float, longitude: float, box: tuple[float, float, float, float]) -> bool:
    south, west, north, east = box
    return south <= latitude <= north and west <= longitude <= east


def _place(found: object, box: tuple[float, float, float, float]) -> dict[str, object] | None:
    """One upstream answer, as this API reports it, or None to drop it.

    Everything is read defensively. The shape comes from somebody else's
    service, and `float("")` raises while `float(None)` raises a
    different exception -- so both go through the same guard rather than
    through `Number(x)`'s JavaScript habit of turning nothing into 0.
    """
    if not isinstance(found, dict):
        return None
    name = found.get("display_name")
    if not isinstance(name, str) or not name.strip():
        return None
    try:
        latitude = float(found["lat"])
        longitude = float(found["lon"])
    except (KeyError, TypeError, ValueError):
        return None
    if not _inside(latitude, longitude, box):
        return None
    return {"name": name.strip()[:160], "lat": latitude, "lon": longitude}


async def _ask_upstream(
    settings: Settings, text: str, box: tuple[float, float, float, float]
) -> list[dict[str, object]]:
    """Ask the configured geocoder, and return only answers in the region."""
    south, west, north, east = box
    await _politely()
    timeout = httpx.Timeout(settings.geocode_timeout_seconds)
    parameters = {
        "q": text,
        "format": "jsonv2",
        "limit": str(RESULT_LIMIT),
        # `bounded=1` makes the viewbox a filter and not a preference, so
        # the upstream does the narrowing too and this endpoint is not a
        # world geocoder with a filter bolted on the end.
        "viewbox": f"{west},{south},{east},{north}",
        "bounded": "1",
        "addressdetails": "0",
    }
    headers = {
        # The upstream policy requires an identifying agent and refuses a
        # generic one. It carries no reader and no address.
        "User-Agent": settings.geocode_user_agent,
        "Accept": "application/json",
    }
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        response = await client.get(settings.geocode_url, params=parameters, headers=headers)
    if response.status_code != 200:
        # The status, never the query. See the module docstring.
        logger.warning("the geocoder answered %d", response.status_code)
        raise HTTPException(status_code=502, detail="the address service did not answer")
    body = response.json()
    if not isinstance(body, list):
        raise HTTPException(status_code=502, detail="the address service did not answer")
    places = [made for item in body if (made := _place(item, box)) is not None]
    return places[:RESULT_LIMIT]


@router.get("")
async def geocode(
    request: Request,
    q: str = Query(min_length=1, max_length=QUERY_LIMIT),
) -> dict[str, object]:
    """Return the places in this region that an address could mean.

    An empty `places` list is an answer and not a failure: the address is
    not in this region, or the upstream knows nothing about it. The
    planner says so rather than leaving the reader waiting.
    """
    settings: Settings = request.app.state.settings
    if not settings.geocode_url.strip():
        # Off by configuration. 404 rather than 501, because to a caller
        # this endpoint does not exist on this deployment. The dashboard
        # is told the same thing through `window.SONORAN.geocode` and
        # never draws the control, so reaching here means somebody asked
        # by hand.
        raise HTTPException(status_code=404, detail="address search is not configured here")

    text = _clean(q)
    if not _spend(_client(request), time.monotonic()):
        raise HTTPException(
            status_code=429, detail="too many address lookups; wait a minute and try again"
        )

    box = _region(settings)
    try:
        places = await _answers.get(
            text.casefold(), CACHE_SECONDS, lambda: _ask_upstream(settings, text, box)
        )
    except httpx.HTTPError as error:
        # The error, never the URL: httpx puts the request URL in the
        # string form of most of its exceptions.
        logger.warning("the geocoder could not be reached: %s", type(error).__name__)
        raise HTTPException(
            status_code=502, detail="the address service could not be reached"
        ) from error
    return {"places": places}
