"""A request budget for each caller of the JSON API.

The API is read-only and sits behind the login portal, so the risk is
not a write. It is somebody pulling the whole database out through it,
one page at a time, with a script. A person reading the dashboard never
comes near these numbers. A script that copies everything does.

**The limit must not be felt by a reader.** Each budget is a token
bucket. The burst is what a reader spends at once: one page of the
dashboard asks for about 10 to 25 answers, and the live views poll
once in 15 seconds. The refill is the sustained rate. Both are far
above any page, several tabs included, and a caller over the budget is
told when to come back (429 with `Retry-After`), not refused for long.

**Who a caller is.** The portal (Authelia, through Caddy) names the
signed-in user in `Remote-User`, and Caddy replaces that header on
every request it forwards. So one reader is one budget, whatever
address they come from. A request with no user is keyed on its client
address, which `FORWARDED_ALLOW_IPS` makes the real one (see
`docs/API.md`).

**Tiles are counted apart.** The coverage map and the planner fetch
map tiles in hundreds when a reader pans or zooms. They are cheap,
immutable and cached by the browser, so they have their own, much
larger budget, and a map view never spends the budget of the rest.
"""

from __future__ import annotations

import logging
import math
import time
from collections import OrderedDict
from dataclasses import dataclass

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.routing import get_route_path
from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger(__name__)

# The paths that fetch tiles in bulk. They use the tile budget.
TILE_PREFIXES = ("/api/coverage/tiles/", "/api/embed/tiles/", "/api/terrain/page/")

# How many callers are remembered at once.
#
# The same ceiling as the geocoder's (`routes/geocode.py`): the table
# grows once per caller, and an address is something a caller can
# choose. Oldest-first eviction keeps it bounded, and a forgotten caller
# starts again with a full bucket, which is the safe direction.
TABLE_LIMIT = 4096

# One warning per caller per this many seconds, so a script that
# hammers the API cannot fill the log.
WARN_EVERY_SECONDS = 60.0


@dataclass(frozen=True)
class Budget:
    """A token bucket: `burst` at once, then `per_second`."""

    burst: float
    per_second: float


class Buckets:
    """The token buckets of every caller for one budget."""

    def __init__(self, budget: Budget, limit: int = TABLE_LIMIT) -> None:
        self.budget = budget
        self.limit = limit
        self._held: OrderedDict[str, tuple[float, float]] = OrderedDict()

    def take(self, who: str, now: float) -> float:
        """Spend one token. Return 0, or the seconds until one is free."""
        tokens, then = self._held.get(who, (self.budget.burst, now))
        tokens = min(self.budget.burst, tokens + (now - then) * self.budget.per_second)
        wait = 0.0
        if tokens >= 1.0:
            tokens -= 1.0
        else:
            wait = (1.0 - tokens) / self.budget.per_second
        self._held[who] = (tokens, now)
        # Moved to the end even on a refusal, as in the geocoder: the
        # caller over its budget is the last one to be forgotten, or
        # eviction becomes the way around the limit.
        self._held.move_to_end(who)
        while len(self._held) > self.limit:
            self._held.popitem(last=False)
        return wait

    def clear(self) -> None:
        self._held.clear()


def caller(scope: Scope) -> str:
    """The key of a request's budget: the portal user, else the address."""
    user = Headers(scope=scope).get("remote-user", "").strip()
    if user:
        return f"user:{user}"
    client = scope.get("client")
    return f"ip:{client[0]}" if client else "ip:unknown"


class RateLimitMiddleware:
    """Refuse an API request over its caller's budget with a 429.

    Only `/api/` is counted. The page, the static files and `/health`
    are never limited: they are what shows the reader that they must
    wait, and the health check is what keeps the container alive.
    """

    def __init__(self, app: ASGIApp, *, general: Budget, tiles: Budget) -> None:
        self.app = app
        self.general = Buckets(general)
        self.tiles = Buckets(tiles)
        self._warned: OrderedDict[str, float] = OrderedDict()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # The routed path, so a `WEB_BASE_PATH` prefix does not hide
        # `/api/` from the check (see `SecurityHeadersMiddleware`).
        path = get_route_path(scope) if scope["type"] == "http" else ""
        if not path.startswith("/api/"):
            await self.app(scope, receive, send)
            return
        who = caller(scope)
        buckets = self.tiles if path.startswith(TILE_PREFIXES) else self.general
        now = time.monotonic()
        wait = buckets.take(who, now)
        if not wait:
            await self.app(scope, receive, send)
            return
        self._warn(who, path, now)
        response = JSONResponse(
            {"detail": "too many requests; wait a moment and try again"},
            status_code=429,
            headers={"Retry-After": str(max(1, math.ceil(wait)))},
        )
        await response(scope, receive, send)

    def _warn(self, who: str, path: str, now: float) -> None:
        last = self._warned.get(who)
        if last is not None and now - last < WARN_EVERY_SECONDS:
            return
        self._warned[who] = now
        self._warned.move_to_end(who)
        while len(self._warned) > TABLE_LIMIT:
            self._warned.popitem(last=False)
        logger.warning("rate limit: %s is over its budget (at %s)", who, path)
