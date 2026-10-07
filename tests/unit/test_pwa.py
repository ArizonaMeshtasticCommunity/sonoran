"""The installed app: manifest, service worker and notices (#322).

Three things here fail without a sign in the browser, and each has a
test:

- The manifest behind a login. A browser fetches it without cookies
  unless the link says `use-credentials`, and the login proxy then
  answers with its login page. Nothing installs, and nothing says why.
- The service worker's path. A worker controls only the pages at or
  below its own path, so one served from `/static/` controls nothing.
- What the worker keeps. Sonoran shows live data behind a login. A
  cached API answer reads as the mesh's real state, and a cached login
  page reads as the app.
"""

import json
import re
import struct
from pathlib import Path
from urllib.parse import urljoin

from fastapi.testclient import TestClient

from sonoran.api.app import STATIC_DIR, create_app
from sonoran.config import Settings

MANIFEST = json.loads((STATIC_DIR / "manifest.webmanifest").read_text(encoding="utf-8"))
SW = (STATIC_DIR / "sw.js").read_text(encoding="utf-8")
PWA = (STATIC_DIR / "pwa.js").read_text(encoding="utf-8")


def _client() -> TestClient:
    return TestClient(create_app(Settings(_env_file=None)))


def _proxied(base: str) -> TestClient:
    """A client that does not strip the mount prefix, as a proxy may not."""
    app = create_app(Settings(_env_file=None, web_base_path=base))
    return TestClient(app, root_path=base)


def _png_size(path: Path) -> tuple[int, int]:
    """Width and height from the PNG header, which is all a browser checks."""
    head = path.read_bytes()[:24]
    assert head[:8] == b"\x89PNG\r\n\x1a\n", path
    width, height = struct.unpack(">II", head[16:24])
    return width, height


def _manifest_link(html: str) -> str:
    match = re.search(r'<link rel="manifest"[^>]*>', html)
    assert match, "the dashboard links no manifest"
    return match.group(0)


# ---- The manifest ----------------------------------------------------


def test_the_manifest_is_fetched_with_the_login_cookie() -> None:
    """Without this the login proxy answers the manifest with its login
    page, because a browser sends no cookie for a manifest by default.
    """
    assert 'crossorigin="use-credentials"' in _manifest_link(_client().get("/").text)


def test_the_app_resolves_to_the_dashboard_from_any_manifest_url() -> None:
    """`start_url`, `scope` and `id` resolve against the manifest's own
    URL, never the page's. The page links it with `?v=` and a hash, and a
    query does not move a relative path. So an install from a deep link
    or a new deploy is the same app at the same root, under any base path.
    """
    for base in ("", "/mesh"):
        manifest_url = f"https://example.org{base}/static/manifest.webmanifest?v=abc123"
        start = urljoin(manifest_url, MANIFEST["start_url"])
        assert start == f"https://example.org{base}/"
        assert urljoin(manifest_url, MANIFEST["scope"]) == start
        # `id` resolves against `start_url`, and stays the old computed
        # id (the start URL), so an existing install keeps its identity.
        assert urljoin(start, MANIFEST["id"]) == start
        for shortcut in MANIFEST["shortcuts"]:
            assert urljoin(manifest_url, shortcut["url"]).startswith(start), shortcut


def test_the_manifest_has_the_icons_chrome_asks_for() -> None:
    """Chrome wants a 192 px and a 512 px icon with purpose `any`. Each
    icon must exist and be the size it claims: a wrong size is skipped.
    """
    declared = set()
    for icon in MANIFEST["icons"]:
        path = STATIC_DIR / icon["src"]
        assert path.is_file(), icon["src"]
        width, height = _png_size(path)
        assert icon["sizes"] == f"{width}x{height}", icon
        declared.add((icon["sizes"], icon.get("purpose", "any")))
    assert ("192x192", "any") in declared
    assert ("512x512", "any") in declared
    assert ("512x512", "maskable") in declared
    assert MANIFEST["display"] == "standalone"


def test_the_shortcuts_open_pages_that_exist() -> None:
    app = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    for shortcut in MANIFEST["shortcuts"]:
        page = shortcut["url"].split("#", 1)[1]
        assert f"PAGES.{page} = " in app, shortcut


def test_the_policy_allows_the_manifest_and_the_worker() -> None:
    csp = _client().get("/").headers["Content-Security-Policy"]
    assert "manifest-src 'self'" in csp
    assert re.search(r"worker-src 'self'", csp)


# ---- The service worker ----------------------------------------------


def test_the_worker_is_served_from_the_app_root() -> None:
    """Its scope can never be wider than its path. From `/static/` it
    would control no page of the dashboard.
    """
    client = _client()
    response = client.get("/sw.js")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/javascript")
    # The browser must ask again on every update check.
    assert response.headers["Cache-Control"] == "no-cache"
    assert "Content-Security-Policy" in response.headers
    assert "register('sw.js', { scope: './' })" in PWA


def test_every_deploy_changes_the_worker() -> None:
    """The browser installs a new worker only when its bytes change. The
    asset version is a hash of every static file, so a deploy that
    changes any file changes the worker, and the page offers a reload.
    """
    app = create_app(Settings(_env_file=None))
    body = TestClient(app).get("/sw.js").text
    assert "__SONORAN_ASSET_VERSION__" not in body
    assert f"'{app.state.asset_version}'" in body


def test_the_worker_is_found_below_a_base_path() -> None:
    """`WEB_BASE_PATH` with a proxy that does not strip it (AGENTS.md
    9.9.2): the worker is at the base, and has the dashboard's policy.
    """
    response = _proxied("/mesh").get("/mesh/sw.js")
    assert response.status_code == 200
    assert "manifest-src 'self'" in response.headers["Content-Security-Policy"]


def test_the_worker_keeps_nothing() -> None:
    """No cache, so no old API answer and no login page can be served as
    the app. A future change that adds one must remove this test on
    purpose, and read the reasons in sw.js first.
    """
    code = re.sub(r"/\*.*?\*/", "", SW, flags=re.S)
    for word in ("caches.open", "cache.put", "cache.add", ".addAll("):
        assert word not in code, word


def test_the_worker_handles_page_loads_only() -> None:
    """Every request that is not a page load, `/api/` and the map tiles
    included, must go to the network as if no worker existed. Returning
    from the handler without `respondWith` is how a worker says that.
    """
    handler = SW[SW.index("addEventListener('fetch'") :]
    handler = handler[: handler.index("});") + 3]
    assert "if (event.request.mode !== 'navigate') return;" in handler
    assert handler.index("return;") < handler.index("respondWith")


def test_a_new_worker_waits_for_the_reader() -> None:
    """No silent swap in the middle of a session. The worker activates
    only on the message pwa.js sends when the reader chooses to reload.
    """
    install = SW[SW.index("addEventListener('install'") :].split("});", 1)[0]
    assert "skipWaiting()" not in install
    assert "if (event.data === 'sonoran:activate') self.skipWaiting();" in SW
    assert "postMessage('sonoran:activate')" in PWA


def test_the_page_loads_the_worker_script_after_app_js() -> None:
    """pwa.js reads `clock` and `setStatus` from app.js when the page goes offline."""
    text = _client().get("/").text
    assert text.index("static/app.js") < text.index("static/pwa.js")


def test_the_icons_tool_makes_the_icons_in_the_manifest() -> None:
    tool = (Path(__file__).resolve().parents[2] / "tools" / "make_app_icons.py").read_text()
    for size in (192, 512):
        assert any(icon["src"] == f"icon-{size}.png" for icon in MANIFEST["icons"])
    assert "for size in (192, 512)" in tool


# ---- An installed app has no browser back ---------------------------


def test_every_detail_page_has_a_way_back_in_an_installed_app() -> None:
    """Each page that Back is given to exists, has a head to put it in,
    and has a list to go to when the app has no earlier page.
    """
    match = re.search(r"const PARENT = \{([^}]*)\}", PWA)
    assert match, "pwa.js names no detail pages"
    pairs = re.findall(r"(\w+): '(\w+)'", match.group(1))
    assert {name for name, _ in pairs} == {"node", "link", "traceroute", "packet"}
    html = _client().get("/").text
    app = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    for name, parent in pairs:
        section = re.search(rf'data-page="{name}">\s*<div class="page-head', html)
        assert section, f"#{name} has no page head for Back"
        assert f"PAGES.{parent} = " in app, parent


def test_back_is_for_the_installed_app_only() -> None:
    """A browser tab has its own back button. Two would be one too many."""
    assert "matchMedia('(display-mode: standalone)')" in PWA
    assert "if (standalone) {" in PWA


def test_offline_turns_the_status_line_red() -> None:
    """The green "Updated" dot in the menu and the phone bar must not
    stay green while nothing updates.
    """
    went = PWA[PWA.index("function wentOffline") :].split("\n  }\n", 1)[0]
    assert "setStatus('down'" in went
    assert "data-offline" in went


# ---- A request never strands the app ---------------------------------


def test_every_api_request_can_be_ended() -> None:
    """Airplane mode on and off left the installed app loading nothing
    until it was closed: one request never answered, and `render` draws
    one page at a time. Every API request goes through `apiFetch`, which
    a network change or a minute without an answer ends.
    """
    app = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    assert "function apiFetch(url)" in app
    assert "const REQUEST_TIMEOUT_MS = 60000;" in app
    assert "function abortRequests()" in app
    for name in ("app.js", "gaps.js", "siting.js", "rf.js", "planner.js", "coverage.js"):
        source = (STATIC_DIR / name).read_text(encoding="utf-8")
        assert not re.search(r"await fetch\(\s*(api|timelineQuery)\(", source), name


def test_a_network_change_ends_requests_and_draws_again() -> None:
    went = PWA[PWA.index("function wentOffline") :].split("\n  }\n", 1)[0]
    came = PWA[PWA.index("function cameOnline") :].split("\n  }\n", 1)[0]
    assert "abortRequests();" in went
    assert "abortRequests();" in came
    assert came.index("abortRequests();") < came.index("route();")
