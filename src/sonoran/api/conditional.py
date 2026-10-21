"""Answer "nothing changed" with a 304 for the long-window views (#371).

Many viewers, each with several tabs, ask for the same answers again and
again. The long-window views change only when the jobs service builds
them again, every few minutes, so most of those answers are byte for
byte the one the tab already holds.

Each answer on `PATHS` gets a weak `ETag`, a hash of its body, and
`Cache-Control: private, no-cache`. A browser then asks again with
`If-None-Match`, and while the body is the same the answer is a `304`
with no body: no JSON to send, compress or parse.

- **`no-cache`, not a lifetime.** The browser always asks, so it never
  shows an answer older than the server's. The saving is the body, not
  the request.
- **`private`.** The API sits behind a login, and a shared cache must
  not hold its answers.
- **The hash is of the body before compression.** This runs inside the
  gzip middleware, so the same answer has the same tag compressed or not.
- **Only a 200 is tagged.** An error, or an answer that is already
  compressed, passes through untouched. A 200 is held whole to hash it,
  so a route under `PATHS` must not stream; none does.
"""

import hashlib
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

from starlette.datastructures import Headers, MutableHeaders
from starlette.routing import get_route_path

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

#: The answers that get a tag: the views built by the jobs service, and
#: the Statistics answers beside them. Prefixes of the route path, so
#: `/api/stats` and everything under it.
PATHS: tuple[str, ...] = ("/api/graph", "/api/stats", "/api/map/nodes")

CACHE_CONTROL = "private, no-cache"


def etag_of(body: bytes) -> str:
    """A weak tag for a body: the same bytes always give the same tag."""
    return 'W/"' + hashlib.sha256(body).hexdigest()[:24] + '"'


def matches(if_none_match: str | None, etag: str) -> bool:
    """True when the request already holds this version.

    Compared weakly, as RFC 9110 asks for `If-None-Match`: `W/"x"` and
    `"x"` are the same version.
    """
    if not if_none_match:
        return False

    def bare(tag: str) -> str:
        tag = tag.strip()
        return tag[2:] if tag.startswith("W/") else tag

    wanted = bare(etag)
    return any(tag.strip() == "*" or bare(tag) == wanted for tag in if_none_match.split(","))


class ConditionalGetMiddleware:
    """Tag the answers on `PATHS`, and answer a matching request with 304."""

    def __init__(self, app: ASGIApp, paths: tuple[str, ...] = PATHS) -> None:
        self.app = app
        self.paths = paths

    def _wanted(self, scope: Scope) -> bool:
        return (
            scope["type"] == "http"
            and scope["method"] in ("GET", "HEAD")
            # The route path, without `WEB_BASE_PATH`, as `api/limits.py` reads it.
            and any(get_route_path(scope).startswith(path) for path in self.paths)
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not self._wanted(scope):
            await self.app(scope, receive, send)
            return
        asked = Headers(scope=scope).get("if-none-match")
        start: Message | None = None
        chunks: list[bytes] = []
        passing = False

        async def capture(message: Message) -> None:
            nonlocal start, passing
            if message["type"] == "http.response.start":
                headers = Headers(raw=message["headers"])
                if message["status"] != 200 or "content-encoding" in headers:
                    passing = True
                    await send(message)
                    return
                start = message
                return
            if passing or start is None or message["type"] != "http.response.body":
                await send(message)
                return
            chunks.append(message.get("body", b""))
            if message.get("more_body", False):
                return
            body = b"".join(chunks)
            etag = etag_of(body)
            headers = MutableHeaders(raw=start["headers"])
            headers["etag"] = etag
            headers["cache-control"] = CACHE_CONTROL
            if matches(asked, etag):
                del headers["content-length"]
                if "content-type" in headers:
                    del headers["content-type"]
                await send({**start, "status": 304, "headers": headers.raw})
                await send({"type": "http.response.body", "body": b""})
                return
            await send({**start, "headers": headers.raw})
            await send({"type": "http.response.body", "body": body})

        await self.app(scope, receive, capture)
