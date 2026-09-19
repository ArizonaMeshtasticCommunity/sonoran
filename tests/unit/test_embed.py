"""Tests for the public coverage embed.

Two things must hold at once, and they pull against each other:

- The dashboard must still refuse to be framed by anybody, including
  this origin. It carries `serial=(self)` for the config checker, and a
  frame of it on somebody else's page would take Web Serial along.
- The embed must be framed by exactly the sites the settings name, and
  by nothing else. Never by a wildcard.

The tests in `test_api_smoke.py` that pin the dashboard headers are
still there and still assert `DENY`. A test that changes to let a new
feature through stops protecting the old one.
"""

import inspect
import json
import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sonoran.api.app import STATIC_DIR, create_app
from sonoran.config import Settings
from sonoran.embed.sanitise import PUBLIC_ROLES, coarse, frame_ancestors, is_public_node


def _client(**extra: object) -> TestClient:
    return TestClient(create_app(Settings(_env_file=None, **extra)))


# --- what may be framed ------------------------------------------------


def test_the_dashboard_still_refuses_to_be_framed_when_the_embed_is_on() -> None:
    """Turning the embed on must not open the dashboard."""
    response = _client(embed_enabled=True, embed_frame_ancestors=["https://azmsh.net"]).get("/")
    assert response.headers["X-Frame-Options"] == "DENY"
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
    assert "serial=(self)" in response.headers["Permissions-Policy"]


def test_the_embed_may_be_framed_by_the_sites_the_settings_name() -> None:
    response = _client(
        embed_enabled=True,
        embed_frame_ancestors=["https://azmsh.net", "https://www.azmsh.net"],
    ).get("/embed/coverage")
    assert response.status_code == 200

    policy = response.headers["Content-Security-Policy"]
    assert "frame-ancestors https://azmsh.net https://www.azmsh.net" in policy
    # The header has no allow list a browser reads, so it must be gone.
    assert "X-Frame-Options" not in response.headers


def test_the_embed_never_carries_web_serial() -> None:
    """The dashboard grants it for the config checker. This must not."""
    response = _client(embed_enabled=True, embed_frame_ancestors=["https://azmsh.net"]).get(
        "/embed/coverage"
    )
    policy = response.headers["Permissions-Policy"]
    assert "serial=()" in policy
    assert "serial=(self)" not in policy


def test_an_embed_with_no_named_site_may_be_framed_by_nobody() -> None:
    """The safe value, not a wildcard."""
    response = _client(embed_enabled=True, embed_frame_ancestors=[]).get("/embed/coverage")
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]


@pytest.mark.parametrize(
    "bad",
    [["*"], ["not a url"], ["javascript:alert(1)"], [""], ["ftp://azmsh.net"], ["azmsh.net"]],
)
def test_a_value_that_is_not_an_origin_cannot_widen_the_policy(bad: list[str]) -> None:
    """A typed mistake must close the door, not open it."""
    assert frame_ancestors(bad) == "'none'"


def test_a_repeated_origin_is_named_once() -> None:
    assert frame_ancestors(["https://a.net", "https://a.net/x", "https://b.net"]) == (
        "https://a.net https://b.net"
    )


def test_the_embed_is_off_until_somebody_turns_it_on() -> None:
    """The private value is the safe default, as with text storage."""
    assert Settings(_env_file=None).embed_enabled is False

    client = _client()
    assert client.get("/embed/coverage").status_code == 404
    assert client.get("/api/embed/coverage").status_code == 404
    assert client.get("/api/embed/nodes").status_code == 404


def test_the_embed_routes_are_read_only() -> None:
    """The API rule holds here too. See AGENTS.md 4."""
    app = create_app(Settings(_env_file=None, embed_enabled=True))
    for route in app.routes:
        path = getattr(route, "path", "")
        methods = getattr(route, "methods", None)
        if methods and (path.startswith("/api/embed") or path.startswith("/embed")):
            assert methods <= {"GET"}


def test_the_embed_uses_paths_below_the_configured_base() -> None:
    """A deployment below /mesh must not ask the origin root."""
    response = _client(embed_enabled=True, web_base_path="/mesh").get("/embed/coverage")
    assert response.status_code == 200
    assert 'href="../static/vendor/leaflet.css"' in response.text
    assert 'src="../static/vendor/leaflet.js"' in response.text
    assert 'src="../static/embed-coverage.js"' in response.text

    script = (STATIC_DIR / "embed-coverage.js").read_text(encoding="utf-8")
    assert "document.baseURI" in script
    assert "CONFIG.apiBase || DOCUMENT_BASE" in script


# --- what a public viewer may see --------------------------------------


@pytest.mark.parametrize("role", sorted(PUBLIC_ROLES))
def test_infrastructure_may_appear(role: str) -> None:
    """A router is a thing somebody chose to put on a hill."""
    assert is_public_node(role, False)


@pytest.mark.parametrize("role", ["CLIENT", "CLIENT_MUTE", "TRACKER", "SENSOR", "", None])
def test_a_client_node_never_appears(role: str | None) -> None:
    """A client node is usually a person, and often at home."""
    assert not is_public_node(role, False)


def test_a_gateway_is_drawn_as_a_gateway_but_does_not_get_in() -> None:
    """This used to assert the opposite, and the opposite was wrong.

    The reasoning was that running a gateway is a deliberate act of
    infrastructure. It is not: `ingest/handlers/presence.py` sets the
    flag for any node that publishes a packet and never clears it, so
    a client with the MQTT uplink switched on is a gateway for ever.

    `is_gateway` still travels on the answer, because the map draws a
    ring around one. It no longer decides who is on the map.
    """
    assert not is_public_node("CLIENT", True)
    assert is_public_node("REPEATER", True)


def test_a_position_is_snapped_before_it_leaves_the_server() -> None:
    """A rounded coordinate is still a coordinate.

    The grid names a hill, not a building, and the browser never sees
    the exact value to round in the first place.
    """
    exact = 33.448377
    snapped = coarse(exact, 0.01)
    assert snapped != exact
    assert abs(snapped - exact) < 0.01
    # Two nearby places land on the same marker.
    assert coarse(33.4412, 0.01) == coarse(33.4487, 0.01)


def test_a_step_of_zero_gives_the_exact_position() -> None:
    """A deployment may ask for that. It must be a choice."""
    assert coarse(33.448377, 0.0) == 33.448377


def test_the_public_shape_carries_no_long_name_or_hardware() -> None:
    from sonoran.embed.sanitise import public_nodes

    rows = [
        ("MTLM", "Mount Lemmon Router", 32.44, -110.78, "ROUTER", False),
        ("HOME", "Bob's House", 33.44, -112.07, "CLIENT", False),
    ]
    nodes = public_nodes(rows, 0.01)
    assert len(nodes) == 1
    node = nodes[0]
    assert node.short_name == "MTLM"
    assert not hasattr(node, "long_name")
    assert not hasattr(node, "hw_model")
    assert not hasattr(node, "last_heard")
    assert not hasattr(node, "node_id")


def test_a_node_with_no_position_is_left_out() -> None:
    from sonoran.embed.sanitise import public_nodes

    assert public_nodes([("MTLM", "x", None, None, "ROUTER", False)], 0.01) == []


def test_a_very_long_short_name_is_cut() -> None:
    """A short name is four characters. Anything longer is a surprise."""
    from sonoran.embed.sanitise import public_nodes

    rows = [("X" * 200, "y", 33.0, -112.0, "ROUTER", False)]
    assert len(public_nodes(rows, 0.01)[0].short_name) <= 8


def test_the_public_node_list_is_held_for_a_while() -> None:
    """The embed sits on a page anybody may load.

    The tiles are files a browser caches. This is the only part that
    reads the database, so it must not be the endpoint a busy page
    hammers.
    """
    from sonoran.api.routes import embed

    assert embed.NODE_CACHE_SECONDS >= 60.0


# --- what the security review found ------------------------------------


def test_a_gateway_alone_does_not_reach_a_public_map() -> None:
    """A gateway is not evidence of infrastructure.

    `ingest/handlers/presence.py` sets `is_mqtt_gateway` for any node
    that publishes a packet and never clears it, so a person who turns
    the MQTT uplink on in the radio on their kitchen table is marked a
    gateway for ever. This rule used to put that kitchen on a public
    map, at a kilometre, with no way to come off it.
    """
    assert not is_public_node("CLIENT", True)
    assert not is_public_node(None, True)
    assert not is_public_node("CLIENT_BASE", True)
    # A gateway that really is infrastructure still appears.
    assert is_public_node("ROUTER", True)


@pytest.mark.parametrize(
    "bad",
    [
        ["https://*"],
        ["https://a.com;script-src *"],
        ["https://a.com 'unsafe-inline'"],
        ["https://a.com,b.com"],
    ],
)
def test_a_framing_origin_cannot_inject_another_directive(bad: list[str]) -> None:
    """`frame-ancestors` is the last directive in the header, so a
    semicolon in the value starts a new one.

    `urlsplit` is not a validator: it keeps a space or a semicolon
    inside the network location. A value like
    `https://azmsh.net;script-src *` would have replaced the script
    policy of the embed with a wildcard.
    """
    assert frame_ancestors(bad) == "'none'"


def test_a_real_origin_still_passes() -> None:
    """The check must not be so tight that it refuses a port."""
    assert frame_ancestors(["https://azmsh.net", "http://localhost:8080"]) == (
        "https://azmsh.net http://localhost:8080"
    )


def test_a_page_config_cannot_close_its_own_script_element() -> None:
    """A configured value holding `</script>` would end the element and
    everything after it would be markup."""
    import json

    from sonoran.api.html import as_script_json

    written = as_script_json({"tileAttribution": "</script><img src=x onerror=alert(1)>"})
    assert "</script>" not in written
    assert "<" not in written
    # And it is still the same value once the browser parses it.
    assert json.loads(written)["tileAttribution"] == "</script><img src=x onerror=alert(1)>"


def test_the_public_map_never_writes_a_node_name_as_markup() -> None:
    """Leaflet writes a string tooltip with innerHTML, and a short name
    is whatever the node's owner typed into their radio."""
    from pathlib import Path

    static = Path("src/sonoran/web/static")
    for name in ("embed-coverage.js", "app.js"):
        text = (static / name).read_text(encoding="utf-8")
        for line in text.splitlines():
            if "bindTooltip(" not in line:
                continue
            assert "createTextNode" in line or line.rstrip().endswith("bindTooltip("), (
                f"{name}: {line.strip()}"
            )


def test_a_tab_inside_an_origin_collapses_rather_than_splitting() -> None:
    """`urlsplit` removes a tab, so it cannot separate two hosts.

    Recorded because it looks like it should be refused and is not. The
    answer is one hostname that resolves to nothing, which frames
    nothing. It is not a way to name a second origin.
    """
    assert frame_ancestors(["https://a.com\tb.com"]) == "https://a.comb.com"


# --- the diagnostic run must never look like a coverage map ------------


def test_a_diagnostic_run_is_withheld_from_the_public_page(tmp_path: Path) -> None:
    """Not labelled. Withheld.

    `COVERAGE_SITE_ROLES=ALL` predicts from every client node, and a
    client node is usually somebody's house. Each one draws a footprint
    centred on it. `public_nodes` already keeps the markers back, but a
    footprint has a centre, and a stranger reading the tiles can find
    it. A warning banner does not fix that; not serving it does.
    """
    import asyncio
    import json

    from sonoran.api.routes import embed

    run = tmp_path / "runs" / "20260101T000000Z"
    run.mkdir(parents=True)
    manifest = {"stamp": "20260101T000000Z", "is_diagnostic": True, "presets": [{"preset": "X"}]}
    (run / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (tmp_path / "index.json").write_text(
        json.dumps({"current": "20260101T000000Z"}), encoding="utf-8"
    )

    settings = Settings(coverage_cache_dir=str(tmp_path), embed_enabled=True)
    embed._summary_cache = None
    try:
        answer = asyncio.run(embed.embed_summary(settings))
    finally:
        embed._summary_cache = None

    assert answer["available"] is False
    assert answer["presets"] == []
    assert answer["reason"] == "diagnostic"
    # And nothing about the run leaks through the refusal.
    assert "bounds" not in answer
    assert "stamp" not in answer


def test_the_public_page_says_which_kind_of_empty_it_is() -> None:
    """ "No map yet" sent an operator looking for a failed job once."""
    script = Path("src/sonoran/web/static/embed-coverage.js").read_text(encoding="utf-8")
    assert "reason === 'diagnostic'" in script
    assert "No coverage map has been made yet." in script


# --- the public tiles --------------------------------------------------
#
# The audit finding these pin: `embed/sanitise.py` is documented as the
# one place that decides what a public viewer sees, and that was true
# of the JSON and false of the pixels. The embed drew its tiles from
# `/api/coverage/tiles`, which is the dashboard's route and carries no
# embed switch and no diagnostic test, so turning the embed on meant
# opening that path at the proxy. One path segment then fetched the
# client map of the same run. See `AGENTS.md` 9.25 and 9.27.
#
# Every test here builds its URL from `embed-coverage.js` rather than
# from a constant, because the question is not "is this route safe" but
# "is the path the public embed actually exposes safe". A fix that
# added a gated route and left the page pointing at the old one would
# pass a test written against a constant.

# One run, and the two maps it can publish. The bytes differ so a test
# can say which map answered, rather than only that something did.
INFRASTRUCTURE_PNG = b"\x89PNG\r\n\x1a\ninfrastructure"
EXTENDED_PNG = b"\x89PNG\r\n\x1a\nextended"

TILE_STAMP = "20260101T000000Z"
TILE_PRESET = "LongFast"
TILE_COORDS = (7, 20, 50)


def _tile_template() -> str:
    """Return the tile URL the embed page builds, with its placeholders.

    Read from the script, not written here. This is the path an
    operator has to open at the reverse proxy for the embed to draw
    anything, which is the surface the finding is about.
    """
    source = (STATIC_DIR / "embed-coverage.js").read_text(encoding="utf-8")
    matches = re.findall(r"`(/[^`]*/tiles/[^`]*)`", source)
    assert len(matches) == 1, f"expected one tile URL in the embed script, found {matches}"
    return matches[0]


def _public_tile_url(**names: str) -> str:
    """Return the embed's own tile URL, with the placeholders filled."""
    url = _tile_template()
    for name, value in names.items():
        url = url.replace("${" + name + "}", value)
    assert "${" not in url, f"a placeholder was left in {url}"
    zoom, x, y = TILE_COORDS
    return f"{url}{zoom}/{x}/{y}.png"


def _embed_tile_url() -> str:
    """The URL the public page asks for, exactly as the page builds it.

    `SITE_SET` is filled too, although the page no longer names one.
    The version before this fix named it in the path, and a helper that
    could not fill it would fail these tests on a missing placeholder
    instead of on the leak they are about. A guard is only verified
    once it has been seen to refuse the thing it exists to refuse.
    """
    return _public_tile_url(
        **{
            "summary.stamp": TILE_STAMP,
            "state.preset": TILE_PRESET,
            "LAYER": "usable",
            "SITE_SET": "infrastructure",
        }
    )


def _public_tile_prefix() -> str:
    """Return the part of the tile URL before the first placeholder."""
    return _tile_template().split("${")[0]


def _write_run(
    root: Path,
    *,
    is_diagnostic: bool,
    site_sets: dict[str, bytes],
    stamp: str = TILE_STAMP,
) -> None:
    """Publish one coverage run on disk, with the tiles it wrote."""
    run = root / "runs" / stamp
    zoom, x, y = TILE_COORDS
    for site_set, png in site_sets.items():
        tile = run / TILE_PRESET / site_set / "usable" / str(zoom) / str(x) / f"{y}.png"
        tile.parent.mkdir(parents=True, exist_ok=True)
        tile.write_bytes(png)
    (run / "manifest.json").write_text(
        json.dumps(
            {
                "stamp": stamp,
                "is_diagnostic": is_diagnostic,
                "bounds": [33.0, -113.0, 34.0, -112.0],
                "min_zoom": 6,
                "max_zoom": 11,
                "presets": [{"preset": TILE_PRESET, "sensitivity_dbm": -130.0}],
            }
        ),
        encoding="utf-8",
    )
    (root / "index.json").write_text(json.dumps({"current": stamp}), encoding="utf-8")


@pytest.fixture(autouse=True)
def _forget_the_tile_gate() -> Iterator[None]:
    """Let each test publish its own run.

    The gate keeps its answer for one stamp of one cache directory, and
    every test here uses the same stamp in a different `tmp_path`.
    """
    from sonoran.api.routes import embed

    embed._publishable = None
    yield
    embed._publishable = None


def test_the_public_tiles_cannot_be_asked_for_the_client_map(tmp_path: Path) -> None:
    """The finding, path A. `COVERAGE_INCLUDE_CLIENTS` is on live.

    A run publishes the infrastructure map and the wider one that
    includes the nodes which repeat, into the same run directory. The
    wider map draws a footprint around every client node it was given,
    and a client node is usually somebody's house.

    Before this was fixed the embed drew from the dashboard's tile
    route, so substituting one path segment of the embed's own URL
    returned those footprints. The site set is not in the public URL at
    all now: there is nowhere to write it.
    """
    _write_run(
        tmp_path,
        is_diagnostic=False,
        site_sets={"infrastructure": INFRASTRUCTURE_PNG, "extended": EXTENDED_PNG},
    )
    client = _client(embed_enabled=True, coverage_cache_dir=str(tmp_path))

    # The page itself still draws.
    allowed = client.get(_embed_tile_url())
    assert allowed.status_code == 200
    assert allowed.content == INFRASTRUCTURE_PNG

    # And nothing under the public prefix answers with the client map.
    zoom, x, y = TILE_COORDS
    prefix = _public_tile_prefix()
    for candidate in (
        f"{prefix}{TILE_STAMP}/{TILE_PRESET}/extended/usable/{zoom}/{x}/{y}.png",
        f"{prefix}{TILE_STAMP}/{TILE_PRESET}/extended/{zoom}/{x}/{y}.png",
        f"{prefix}{TILE_STAMP}/{TILE_PRESET}/usable/extended/{zoom}/{x}/{y}.png",
    ):
        response = client.get(candidate)
        assert response.status_code >= 400, candidate
        assert response.content != EXTENDED_PNG, candidate

    # The dashboard still has it. That is what the dashboard is for,
    # and this change must not have taken it away.
    zoom, x, y = TILE_COORDS
    dashboard = client.get(
        f"/api/coverage/tiles/{TILE_STAMP}/{TILE_PRESET}/extended/usable/{zoom}/{x}/{y}.png"
    )
    assert dashboard.status_code == 200
    assert dashboard.content == EXTENDED_PNG


def test_a_diagnostic_run_is_not_reachable_through_the_public_tiles(tmp_path: Path) -> None:
    """The finding, path B, and the worse one.

    `COVERAGE_SITE_ROLES=ALL` predicts from every node. The job used to
    write that run's tiles under a directory named `infrastructure`
    regardless, so the path said "routers and repeaters" and held a
    footprint around every client in region. `/api/embed/coverage`
    refused the run and the tiles were served anyway, behind nothing
    but a stamp on a six-hour cadence.

    The tiles here are written the way the old job wrote them, because
    a run made before this fix is still on disk on a live deployment.
    """
    _write_run(tmp_path, is_diagnostic=True, site_sets={"infrastructure": EXTENDED_PNG})
    client = _client(embed_enabled=True, coverage_cache_dir=str(tmp_path))

    response = client.get(_embed_tile_url())
    assert response.status_code == 404
    assert response.content != EXTENDED_PNG

    # The summary refuses it too, as it always has.
    summary = client.get("/api/embed/coverage").json()
    assert summary["available"] is False
    assert summary["reason"] == "diagnostic"

    # And the dashboard keeps it, which is the point of the feature.
    zoom, x, y = TILE_COORDS
    dashboard = client.get(
        f"/api/coverage/tiles/{TILE_STAMP}/{TILE_PRESET}/infrastructure/usable/{zoom}/{x}/{y}.png"
    )
    assert dashboard.status_code == 200


def test_the_public_tiles_serve_the_published_run_only(tmp_path: Path) -> None:
    """A stamp is a cache key here, not a lookup.

    `KEEP_RUNS` is two, so the run before the current one is still on
    disk. The public route answers for the published run and refuses
    the rest, which is also what stops a stamp being worth guessing.
    """
    older = "20251231T180000Z"
    _write_run(tmp_path, is_diagnostic=False, site_sets={"infrastructure": INFRASTRUCTURE_PNG})
    run = tmp_path / "runs" / older
    zoom, x, y = TILE_COORDS
    tile = run / TILE_PRESET / "infrastructure" / "usable" / str(zoom) / str(x) / f"{y}.png"
    tile.parent.mkdir(parents=True, exist_ok=True)
    tile.write_bytes(EXTENDED_PNG)

    client = _client(embed_enabled=True, coverage_cache_dir=str(tmp_path))
    prefix = _public_tile_prefix()
    stale = client.get(f"{prefix}{older}/{TILE_PRESET}/usable/{zoom}/{x}/{y}.png")
    assert stale.status_code == 404
    assert stale.content != EXTENDED_PNG


def test_every_public_tile_path_is_gone_while_the_embed_is_off(tmp_path: Path) -> None:
    """And it answers without opening a database session.

    `AGENTS.md` 9.16.3: a handler body runs after every parameter is
    resolved, so a check there has already asked the database for a
    request that must never have reached it. The tile route is on the
    embed router for that reason and not only for tidiness.
    """
    _write_run(tmp_path, is_diagnostic=False, site_sets={"infrastructure": INFRASTRUCTURE_PNG})

    def never(*args: object, **kwargs: object) -> object:
        raise AssertionError("the embed opened a database session while it was off")

    app = create_app(Settings(_env_file=None, coverage_cache_dir=str(tmp_path)))
    app.state.session_factory = never
    client = TestClient(app)

    zoom, x, y = TILE_COORDS
    prefix = _public_tile_prefix()
    for path in (
        _embed_tile_url(),
        f"{prefix}{TILE_STAMP}/{TILE_PRESET}/usable/{zoom}/{x}/{y}.png",
        f"{prefix}{TILE_STAMP}/{TILE_PRESET}/infrastructure/usable/{zoom}/{x}/{y}.png",
        "/embed/coverage",
        "/api/embed/coverage",
        "/api/embed/nodes",
    ):
        assert client.get(path).status_code == 404, path


def test_the_dashboard_tile_route_still_serves_the_dashboard(tmp_path: Path) -> None:
    """The fix must not be a removal.

    The dashboard reads every site set a run published, by name, from
    its own route. Narrowing that route would take the diagnostic away
    from the only audience it is for.
    """
    _write_run(
        tmp_path,
        is_diagnostic=False,
        site_sets={"infrastructure": INFRASTRUCTURE_PNG, "extended": EXTENDED_PNG},
    )
    client = _client(embed_enabled=False, coverage_cache_dir=str(tmp_path))
    zoom, x, y = TILE_COORDS
    for site_set, png in (("infrastructure", INFRASTRUCTURE_PNG), ("extended", EXTENDED_PNG)):
        response = client.get(
            f"/api/coverage/tiles/{TILE_STAMP}/{TILE_PRESET}/{site_set}/usable/{zoom}/{x}/{y}.png"
        )
        assert response.status_code == 200
        assert response.content == png
        assert "immutable" in response.headers.get("Cache-Control", "")


def _flatten(routes: object) -> Iterator[object]:
    """Yield every route, through the routers an include left in place.

    FastAPI keeps an included router as one `_IncludedRouter` entry
    rather than copying its routes up, and that entry has no path. So
    walking a router for a path finds nothing inside an included one,
    and a test that enumerates a surface that way enumerates an empty
    set and passes. `original_router` is the way in.

    A future version that copies the routes up still works here. One
    that wraps them some third way yields an entry with no path, and
    the test that compares the paths says so rather than passing.
    """
    for route in routes:  # type: ignore[attr-defined]
        nested = getattr(route, "original_router", None)
        if nested is not None:
            yield from _flatten(nested.routes)
            continue
        yield route


def test_the_embed_router_carries_exactly_these_routes() -> None:
    """The public surface, written down where a change has to edit it.

    A route added to this router is public the moment `EMBED_ENABLED`
    is true. Anything new here has to be a deliberate line in this
    list, and `docs/API.md` 3B has to say the same.
    """
    from sonoran.api.routes import embed

    seen = {
        (getattr(route, "path", ""), frozenset(getattr(route, "methods", set()) or set()))
        for route in _flatten(embed.router.routes)
    }
    assert seen == {
        ("/embed/coverage", frozenset({"GET"})),
        ("/api/embed/coverage", frozenset({"GET"})),
        ("/api/embed/nodes", frozenset({"GET"})),
        ("/api/embed/tiles/{stamp}/{preset}/{layer}/{zoom}/{x}/{y}.png", frozenset({"GET"})),
    }


def test_every_public_route_refuses_before_a_handler_runs() -> None:
    """`AGENTS.md` 9.16.3, for each route on the router.

    Not a check in a body. A dependency, so the refusal happens while
    the parameters are still being resolved.
    """
    from sonoran.api.routes import embed

    for route in _flatten(embed.router.routes):
        dependant = getattr(route, "dependant", None)
        assert dependant is not None, route
        calls = {item.call for item in dependant.dependencies}
        assert embed._require_enabled in calls, getattr(route, "path", "")
        if "/tiles/" in getattr(route, "path", ""):
            assert embed._require_published_map in calls


def test_the_public_tile_route_takes_no_site_set() -> None:
    """The lock that cannot be picked: there is nowhere to name one.

    This replaces the constant that used to sit in the browser. That
    constant was the "second lock" of `AGENTS.md` 9.27, and it only
    ever constrained a browser that meant no harm, because the route it
    fed took the set from the path.
    """
    from sonoran.api.routes import embed

    path = "/api/embed/tiles/{stamp}/{preset}/{layer}/{zoom}/{x}/{y}.png"
    assert "{site_set}" not in path
    source = inspect.getsource(embed.embed_tile)
    assert "SITE_SET_INFRASTRUCTURE" in source
    # It must not take the set from anywhere a request can reach.
    assert "site_set" not in source

    script = (STATIC_DIR / "embed-coverage.js").read_text(encoding="utf-8")
    assert "/api/embed/tiles/" in script
    assert "/api/coverage/tiles/" not in script
    # And it still must not read a set from the summary it was handed.
    assert "summary.site_sets" not in script
    assert "state.siteSet" not in script


# --- the dashboard tells the operator whether an embed will work -------


def _dashboard_config(**overrides: object) -> dict:
    """Return the config block the dashboard page is served with."""
    import json
    import re

    from fastapi.testclient import TestClient

    from sonoran.api.app import create_app
    from sonoran.config import Settings

    app = create_app(Settings(_env_file=None, **overrides))  # type: ignore[arg-type]
    with TestClient(app) as client:
        body = client.get("/").text
    found = re.search(r"window\.SONORAN = (\{.*?\});", body, re.S)
    assert found, "the dashboard did not carry a config block"
    return json.loads(found.group(1))


def test_the_dashboard_says_when_the_embed_is_off() -> None:
    """The snippet is useless without this, and nothing else reveals it."""
    config = _dashboard_config(embed_enabled=False)
    assert config["embed"]["enabled"] is False


def test_the_dashboard_says_when_the_embed_is_on() -> None:
    config = _dashboard_config(embed_enabled=True)
    assert config["embed"]["enabled"] is True


def test_the_dashboard_reports_who_may_frame_the_embed() -> None:
    """An empty list means nobody, which is the opposite of what it looks like."""
    config = _dashboard_config(embed_enabled=True, embed_frame_ancestors=["https://azmsh.net"])
    assert config["embed"]["frameAncestors"] == ["https://azmsh.net"]

    empty = _dashboard_config(embed_enabled=True)
    assert empty["embed"]["frameAncestors"] == []


def test_the_dashboard_config_carries_no_secret() -> None:
    """It is served to every visitor of the dashboard."""
    config = _dashboard_config(embed_enabled=True)
    flat = str(config).lower()
    for word in ("password", "secret", "key", "token", "dsn"):
        assert word not in flat, word
