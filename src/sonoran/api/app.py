"""The FastAPI application factory.

The API is read-only. It registers GET routes only.
It connects to the database with the SELECT-only role.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from hashlib import sha256
from pathlib import Path
from secrets import token_urlsafe
from urllib.parse import parse_qs

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.middleware.gzip import GZipMiddleware
from starlette.requests import Request
from starlette.responses import HTMLResponse, Response
from starlette.routing import get_route_path
from starlette.types import Scope

from sonoran import __version__
from sonoran.api.conditional import ConditionalGetMiddleware
from sonoran.api.html import as_script_json
from sonoran.api.limits import Budget, RateLimitMiddleware
from sonoran.api.routes.chat import router as chat_router
from sonoran.api.routes.climate import router as climate_router
from sonoran.api.routes.coverage import router as coverage_router
from sonoran.api.routes.embed import router as embed_router
from sonoran.api.routes.gaps import router as gaps_router
from sonoran.api.routes.geocode import router as geocode_router
from sonoran.api.routes.graph import router as graph_router
from sonoran.api.routes.leaderboards import router as leaderboards_router
from sonoran.api.routes.map import router as map_router
from sonoran.api.routes.node_page import router as node_page_router
from sonoran.api.routes.nodes import router as nodes_router
from sonoran.api.routes.packets import router as packets_router
from sonoran.api.routes.radio import router as radio_router
from sonoran.api.routes.rf import router as rf_router
from sonoran.api.routes.stats import router as stats_router
from sonoran.api.routes.terrain import router as terrain_router
from sonoran.api.routes.traceroutes import router as traceroutes_router
from sonoran.config import Settings, get_settings
from sonoran.db.session import make_engine, make_session_factory
from sonoran.embed.sanitise import frame_ancestors, safe_origin
from sonoran.logging import (
    configure_logging,
    get_logger,
    quieten_http_client,
    redact_access_query,
)
from sonoran.radio.overrides import load_overrides

logger = get_logger(__name__)

STATIC_DIR = Path(__file__).parent.parent / "web" / "static"


def _asset_version() -> str:
    """Return a content version for the files used by the dashboard."""
    digest = sha256()
    for path in sorted(item for item in STATIC_DIR.rglob("*") if item.is_file()):
        digest.update(path.relative_to(STATIC_DIR).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()[:12]


def _origin(url: str, *, setting: str = "") -> str | None:
    """Return the scheme and host of a configured URL, or None.

    One line of real work, and the line is `safe_origin`. This function
    used to do the check itself — `f"{scheme}://{netloc}"`, with no test
    on the characters — and `urlsplit` keeps a semicolon and a space
    inside a network location. The result went straight into the
    `Content-Security-Policy`, where a semicolon starts a new directive
    and a browser honours a directive's **first** occurrence. So a
    crafted `MAP_TILE_URL` put its own `script-src` in front of ours.

    `sonoran/embed/sanitise.py` already had the right check for
    `frame-ancestors`, and its docstring claimed the rest of the
    headers used it too. They did not. Now they do, and this is the
    only place the four sources are built from.

    A refusal is reported, because in the browser it is silent: a tile
    host missing from `img-src` draws nothing and logs nothing the
    operator sees, which is the trap in `AGENTS.md` 9.9.
    """
    origin = safe_origin(url)
    if origin is None and url.strip():
        logger.warning(
            "%s is not a usable origin and was left out of the "
            "Content-Security-Policy: %r. The browser will block it with no "
            "visible error. Give a plain scheme and host, such as "
            "https://example.net:8080.",
            setting or "a configured URL",
            url,
        )
    return origin


def _frame_source(graph_url: str) -> str:
    """Return a safe CSP source for the configured graph service."""
    return _origin(graph_url, setting="MESH_GRAPH_BASE_URL") or "'self'"


def _image_sources(tile_url: str, graph_url: str) -> str:
    """Return the CSP image sources.

    The map needs the tile host. The traceroute inspector embeds the
    drawing that mesh-graph renders, so that origin is an image source
    too.
    """
    sources = ["'self'", "data:"]
    for candidate, setting in ((tile_url, "MAP_TILE_URL"), (graph_url, "MESH_GRAPH_BASE_URL")):
        origin = _origin(candidate, setting=setting)
        if origin is not None and origin not in sources:
            sources.append(origin)
    return " ".join(sources)


# The config check page asks GitHub which firmware release is current.
# That is the only outbound request the dashboard makes, and it carries
# no user data. See web/static/vendor/config-checker/PROVENANCE.md.
FIRMWARE_RELEASES_ORIGIN = "https://api.github.com"

# What the dashboard is allowed to use.
#
# The browser denies everything named here whatever a page asks for, so
# a feature added later cannot quietly reach the camera or the location
# of whoever is looking at the mesh.
#
# `serial` is the exception, and it is the reason this header exists.
# The config checker reads a node over USB and writes settings back to
# it, which needs Web Serial. Granting it to this origin alone keeps it
# out of any frame from anywhere else.
PERMISSIONS_POLICY = ", ".join(
    (
        "serial=(self)",
        "accelerometer=()",
        "ambient-light-sensor=()",
        "autoplay=()",
        "bluetooth=()",
        "camera=()",
        "display-capture=()",
        "geolocation=()",
        "gyroscope=()",
        "hid=()",
        "idle-detection=()",
        "magnetometer=()",
        "microphone=()",
        "midi=()",
        "payment=()",
        "usb=()",
        "xr-spatial-tracking=()",
    )
)


# What the embed is allowed to use: nothing.
#
# The dashboard grants `serial=(self)` so the config checker can read a
# node over USB. An embed sits on somebody else's page and must never
# carry that.
EMBED_PERMISSIONS_POLICY = ", ".join(
    ["serial=()"] + [item for item in PERMISSIONS_POLICY.split(", ") if item != "serial=(self)"]
)


def _connect_sources(api_base_url: str) -> str:
    """Return the CSP connect sources.

    The page reads the API with fetch. When the API runs on a different
    origin, that origin must be a connect source. If it is not, the
    browser blocks every request and the page stays empty.

    The firmware release host is always present. Without it the config
    checker cannot say whether a node is up to date, and it fails with
    nothing the user can see.
    """
    sources = ["'self'", FIRMWARE_RELEASES_ORIGIN]
    origin = _origin(api_base_url, setting="WEB_API_BASE_URL")
    if origin is not None and origin not in sources:
        sources.append(origin)
    return " ".join(sources)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to every response."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # The path below the mount, read BEFORE the request is routed.
        #
        # This used to be read after `call_next`, and by then a `Mount`
        # has rewritten `root_path` in the same scope object. So for
        # `/static/app.css` the helper returned `/app.css`, the
        # `startswith("/static")` branch never matched, and **every
        # static asset was served with no Content-Security-Policy**.
        # `/` matched and looked right, which is why it went unnoticed.
        #
        # Read here, `root_path` is only what `WEB_BASE_PATH` set, which
        # is the prefix 9.9.2 wants taken off. See that note: the header
        # decision has to use the routed path, and this is the moment
        # the routed path means what the note says.
        path = get_route_path(request.scope)
        response = await call_next(request)
        # Set by the document handler, which is the only response with
        # inline script in it. Anything else gets a policy that permits
        # no inline script at all, which is what we want.
        nonce = getattr(request.state, "csp_nonce", "")
        response.headers["X-Content-Type-Options"] = "nosniff"
        # Send the origin, not the full URL, on a cross-origin request.
        # `no-referrer` sent nothing, and the OpenStreetMap tile server
        # answers a request with no Referer with a "blocked" placeholder
        # tile instead of the map: its usage policy asks a website to
        # identify itself, and the Referer is how a browser does that.
        # This leaks only the origin, never a path, and the dashboard
        # keeps its state in the URL fragment, which a Referer never
        # carries anyway. The full URL still goes to same-origin requests.
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        settings = request.app.state.settings
        embed = settings.embed_enabled and _is_embed(path)
        if embed:
            # `X-Frame-Options` has no allow list a modern browser reads
            # beyond SAMEORIGIN, so a third party frame needs the header
            # gone and the policy said in `frame-ancestors` instead.
            #
            # The embed is its own document. The dashboard carries
            # `serial=(self)` for the config checker, and framing that
            # would take Web Serial onto somebody else's page.
            response.headers["Permissions-Policy"] = EMBED_PERMISSIONS_POLICY
        else:
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["Permissions-Policy"] = PERMISSIONS_POLICY
        if embed:
            image_sources = _image_sources(settings.map_tile_url, "")
            response.headers["Content-Security-Policy"] = (
                f"default-src 'self'; img-src {image_sources}; "
                "connect-src 'self'; "
                "style-src 'self' 'unsafe-inline'; "
                # The embed's one inline script carries the same nonce
                # the dashboard's two do. This page is the one we let a
                # third party frame, so its policy is the one running
                # inside somebody else's site -- it is the LAST place to
                # keep a blanket allowance for inline script.
                f"script-src 'self' 'nonce-{nonce}'; "
                "worker-src 'none'; "
                "frame-src 'none'; "
                f"frame-ancestors {frame_ancestors(settings.embed_frame_ancestors)}"
            )
        elif path.startswith("/static") or path in ("/", SERVICE_WORKER_PATH):
            frame_source = _frame_source(settings.mesh_graph_base_url)
            image_sources = _image_sources(settings.map_tile_url, settings.mesh_graph_base_url)
            connect_sources = _connect_sources(settings.web_api_base_url)
            response.headers["Content-Security-Policy"] = (
                f"default-src 'self'; img-src {image_sources}; "
                f"connect-src {connect_sources}; "
                "style-src 'self' 'unsafe-inline'; "
                # The coverage planner compiles a WebAssembly module. The
                # browser refuses to do that without wasm-unsafe-eval and
                # reports nothing the user can see. Terrain comes from
                # this origin, so no extra connect source is needed.
                #
                # NO `unsafe-inline`. It used to be here, and it is the
                # reason the stored XSS in #81 executed: a node named
                # `<img src=x onerror=...>` reached an innerHTML sink,
                # and the policy permitted the handler to run. The sink
                # is fixed, but a policy that would allow the next one
                # is a policy doing nothing.
                #
                # Two inline scripts need to run: the theme, which must
                # go before first paint or a light reader sees a dark
                # frame, and the one line that carries the server's
                # config. Both carry this nonce. A browser that
                # understands nonces ignores `unsafe-inline` entirely,
                # so there is no point keeping it as a fallback -- it
                # would only weaken the policy for browsers that honour
                # both.
                f"script-src 'self' 'nonce-{nonce}' 'wasm-unsafe-eval'; "
                # `'self'` also covers the service worker at `/sw.js`
                # (#322), and `manifest-src` the installed app's manifest.
                # Without `manifest-src` a policy falls back to
                # `default-src`, which says the same today; it is named so
                # that a stricter `default-src` cannot remove the install.
                "worker-src 'self' blob:; "
                "manifest-src 'self'; "
                # Nothing may frame the dashboard, not even this origin.
                "frame-ancestors 'none'; "
                f"frame-src 'self' {frame_source}"
            )
        if path.startswith("/static"):
            response.headers["Cache-Control"] = _static_cache_control(request.scope)
        return response


# The service worker's path below the mount (#322). It must be the app
# root, because a worker controls only the pages at or below its path.
SERVICE_WORKER_PATH = "/sw.js"

# How long a versioned asset may be kept. A year, which is the longest
# value the specification gives a meaning to.
_A_YEAR = "public, max-age=31536000, immutable"

# How long an unversioned asset may be kept. Long enough to be worth
# something across one reading of the dashboard, short enough that a
# deployment is not invisible to somebody who reached a file directly.
_A_FEW_MINUTES = "public, max-age=300"


def _static_cache_control(scope: Scope) -> str:
    """Say how long a static file may be kept, from the URL that asked.

    `index.html` asks for every asset with `?v=` and a hash of the
    file's own bytes (see `_asset_version`), so a changed file is a
    changed URL and the old one can be kept for ever. That is the whole
    reason `immutable` is safe here, and it stops the 25 conditional
    requests a warm load spent revalidating assets that had not moved.

    **The version has to be checked, not assumed.** A file reached
    without `?v=` — someone's bookmark, a direct link, a tool — has a
    URL that never changes, so telling a browser to keep it for a year
    would serve a stale asset until the cache was cleared by hand. Those
    get a few minutes instead: still useful, and a deploy reaches them.
    """
    query = scope.get("query_string", b"")
    version = parse_qs(query.decode("latin-1")).get("v", [""])[0]
    return _A_YEAR if version else _A_FEW_MINUTES


# Named one by one, deliberately.
#
# `startswith("/embed/")` was correct for the one document that exists
# and wrong for every one that does not yet. Any page added under
# `/embed/` later would have inherited third-party `frame-ancestors`
# and lost `X-Frame-Options` without anybody choosing that -- the
# failure being silent is the whole problem, because the page would
# work.
#
# Adding an embed route therefore means adding it here. That is the
# point, and `test_embed_policy_is_explicit.py` fails if a registered
# embed route is missing from this set, so the omission cannot be quiet
# either.
_EMBED_PATHS = frozenset(
    {
        "/embed/coverage",
        "/api/embed/coverage",
        "/api/embed/nodes",
    }
)

# The one prefix that survives, because its path carries six parameters
# and cannot be written out. It is a leaf namespace serving PNG tiles,
# not a place documents get added, which is what made the old
# `/embed/` prefix dangerous.
_EMBED_TILE_PREFIX = "/api/embed/tiles/"


def _is_embed(path: str) -> bool:
    """Return true for a path that a third party may frame.

    Only the embed document and the data it reads. Everything else on
    this origin keeps the policy the dashboard has.

    **The path must already have `root_path` taken off it.** The caller
    uses `get_route_path`. Reading `scope["path"]` raw was wrong in both
    directions when `WEB_BASE_PATH` was set and the proxy did not strip
    the prefix:

    - The embed got `X-Frame-Options: DENY` and could not be framed. It
      fails closed, so it was a trap rather than a hole.
    - The dashboard branch also stopped matching, so `/` and `/static`
      were served with **no Content-Security-Policy at all**. That one
      fails open, and it is the reason this is a fix and not a
      tidy-up.

    `tests/unit/test_embed.py` passed throughout, because TestClient's
    scope path excludes `root_path` unless it is told otherwise: a green
    test over a production difference. It now drives a client shaped
    like the proxy that does not strip.
    """
    return path in _EMBED_PATHS or path.startswith(_EMBED_TILE_PREFIX)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application startup and shutdown."""
    logger.info("Sonoran API starting, version=%s", __version__)
    engine = make_engine(app.state.settings.database_url_api)
    app.state.session_factory = make_session_factory(engine)
    try:
        yield
    finally:
        await engine.dispose()
        logger.info("Sonoran API stopping")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create the FastAPI application."""
    if settings is None:
        settings = get_settings()

    app = FastAPI(
        title="Sonoran",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
        root_path=settings.web_base_path.rstrip("/"),
    )
    app.state.settings = settings
    app.state.asset_version = _asset_version()
    # The radio overrides are read once. The file is in the repository
    # and ships with the image, so a change to it arrives with a deploy.
    app.state.radio_overrides = load_overrides(settings.radio_overrides_path)
    # The planner's address search is the one endpoint that carries words
    # a reader typed, and a GET puts them in the request line that
    # uvicorn's access log writes out. Installed here rather than in
    # `configure_logging` because this factory runs AFTER uvicorn has
    # applied its own logging config, which is the ordering that decides
    # whether the filter is still attached when the first request lands.
    redact_access_query("/api/geocode")
    # And the line httpx writes for the outbound half of it, which is
    # at INFO and held the same address. Both mitigations are here so
    # that removing one and leaving the other is a visible edit.
    quieten_http_client()
    # Each caller's request budget (`api/limits.py`). Added before the
    # headers, so it runs inside them and a 429 carries them too.
    if settings.api_rate_limit_enabled:
        app.add_middleware(
            RateLimitMiddleware,
            general=Budget(settings.api_rate_burst, settings.api_rate_per_second),
            tiles=Budget(settings.api_tile_rate_burst, settings.api_tile_rate_per_second),
            user_header=settings.api_rate_user_header,
        )
    # Tag the long-window answers and answer an unchanged one with 304
    # (#371). Before the security headers, so a 304 carries them too, and
    # inside gzip, so the tag is of the uncompressed body.
    app.add_middleware(ConditionalGetMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    # Compress what is worth compressing.
    #
    # Nothing was compressed before this, and a cold load moved 2.41 MB
    # across 25 requests. The text assets are the bulk of it and they
    # compress hard: 2,023,889 bytes of JavaScript and CSS becomes
    # 635,575, and `meshtastic-static.js` alone goes from 407,780 to
    # 27,458 because a protobuf schema is mostly repeated field names.
    #
    # `minimum_size` keeps the small JSON answers alone. Below about a
    # kilobyte the gzip header and the round trip through the compressor
    # cost more than the bytes saved, and this box has one core.
    #
    # Starlette's middleware skips a response that already carries a
    # `Content-Encoding` and nothing else — it does **not** filter by
    # content type, so the PNG routes do get re-compressed. That was
    # measured rather than assumed before being accepted: a real icon
    # from this directory gives back 2.9% for 0.12 ms, which is not
    # worth a content-type subclass to avoid, and the coverage tiles are
    # fetched once per client because they are immutable for a year.
    #
    # Level 6, not the library default of 9. On `app.js` the difference
    # is 77,937 bytes against 77,721 — 0.3% — for 8% more processor
    # time, and there is one core.
    app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=6)
    app.include_router(nodes_router)
    app.include_router(node_page_router)
    app.include_router(chat_router)
    app.include_router(coverage_router)
    app.include_router(embed_router)
    app.include_router(radio_router)
    app.include_router(gaps_router)
    app.include_router(geocode_router)
    app.include_router(graph_router)
    app.include_router(map_router)
    app.include_router(packets_router)
    app.include_router(stats_router)
    app.include_router(leaderboards_router)
    app.include_router(terrain_router)
    app.include_router(climate_router)
    app.include_router(traceroutes_router)
    app.include_router(rf_router)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.get("/api/version")
    async def version() -> dict[str, str]:
        return {"version": __version__, "schema": "none"}

    @app.get("/", include_in_schema=False)
    async def dashboard(request: Request) -> HTMLResponse:
        """Serve the no-build dashboard at the configured base path."""
        html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
        config = {
            "apiBase": settings.web_api_base_url,
            "graphBaseUrl": settings.mesh_graph_base_url.rstrip("/"),
            "timezone": settings.display_timezone,
            "tileUrl": settings.map_tile_url,
            "tileAttribution": settings.map_tile_attribution,
            "mapCenter": [settings.map_default_lat, settings.map_default_lon],
            "mapZoom": settings.map_default_zoom,
            # The region the live map opens on, as Leaflet wants it:
            # [[south, west], [north, east]] (#195). The centre and zoom
            # above stay for the pages that use a plain `setView`.
            "mapHome": [
                [settings.map_home_south, settings.map_home_west],
                [settings.map_home_north, settings.map_home_east],
            ],
            # The preset every picker opens on when it has a choice
            # (#177). Pages fall back to their old behaviour when this
            # one is not in the data they were given.
            "defaultPreset": settings.default_preset,
            # Whether the planner may offer an address search (§6.5).
            #
            # Said here rather than discovered by asking the endpoint,
            # for the reason `.cable-run` is hidden until its catalogue
            # arrives: a control that cannot work is worse than no
            # control, and a probe request would put an empty query in
            # the log of a deployment that has the feature switched off.
            "geocode": {"enabled": bool(settings.geocode_url.strip())},
            # What the coverage page needs to hand somebody an embed
            # snippet, and to tell them the truth about whether it will
            # work. Three things can each stop an embed dead, and all
            # three are invisible from the browser: the feature can be
            # off, the page can be published at an address this
            # deployment does not know, and the list of sites allowed to
            # frame it can be empty, which means nobody.
            "embed": {
                "enabled": settings.embed_enabled,
                "path": "/embed/coverage",
                "frameAncestors": list(settings.embed_frame_ancestors),
            },
        }
        html = html.replace("__SONORAN_CONFIG__", as_script_json(config))
        html = html.replace("__SONORAN_ASSET_VERSION__", app.state.asset_version)
        # A fresh nonce per response, put on the request so the security
        # middleware can name it in the policy. The document is
        # `no-cache`, so a nonce can never be served twice -- which is
        # the one thing that would make it worthless.
        nonce = token_urlsafe(16)
        request.state.csp_nonce = nonce
        html = html.replace("__SONORAN_NONCE__", nonce)
        return HTMLResponse(html, headers={"Cache-Control": "no-cache"})

    @app.get(SERVICE_WORKER_PATH, include_in_schema=False)
    async def service_worker() -> Response:
        """Serve the service worker from the app root (#322).

        A worker controls only the pages at or below its own path, so it
        cannot live under `/static/`. The asset version is written into
        it, so every deploy changes its bytes, and the browser installs
        the new one and the page offers a reload. `no-cache`, so the
        browser asks for it again every time it checks for an update.
        """
        script = (STATIC_DIR / "sw.js").read_text(encoding="utf-8")
        script = script.replace("__SONORAN_ASSET_VERSION__", app.state.asset_version)
        return Response(
            script,
            media_type="text/javascript",
            headers={"Cache-Control": "no-cache"},
        )

    if STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    return app


def run() -> None:
    """Console script entry point."""
    import uvicorn

    settings = get_settings()
    configure_logging(settings.log_level)
    uvicorn.run(
        "sonoran.api.app:create_app",
        factory=True,
        host=settings.web_host,
        port=settings.web_port,
        workers=max(settings.web_workers, 1),
    )
