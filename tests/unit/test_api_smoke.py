"""Smoke tests for the API application."""

import re

from fastapi.testclient import TestClient

from sonoran.api.app import STATIC_DIR, create_app
from sonoran.api.routes import chat, graph, nodes, packets, stats, traceroutes
from sonoran.api.routes import map as map_routes
from sonoran.api.routes.packets import _parse_portnum
from sonoran.config import Settings


def _client() -> TestClient:
    app = create_app(Settings(_env_file=None))
    return TestClient(app)


def test_health() -> None:
    response = _client().get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_version() -> None:
    response = _client().get("/api/version")
    assert response.status_code == 200
    assert "version" in response.json()


def test_security_headers() -> None:
    response = _client().get("/health")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    # The origin, not nothing, so the OpenStreetMap tile server sees a
    # Referer and serves the map instead of its "blocked" tile. Only the
    # origin travels cross-origin, never a path. See AGENTS.md 9.9.1.
    assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"


def test_dashboard_csp_allows_only_the_configured_graph_frame() -> None:
    """The graph embed source comes from application configuration."""
    app = create_app(Settings(_env_file=None, mesh_graph_base_url="https://graph.example/mesh"))
    response = TestClient(app).get("/")
    assert "frame-src 'self' https://graph.example" in response.headers["Content-Security-Policy"]


def test_dashboard_has_every_page() -> None:
    """The dashboard serves each documented page section."""
    response = _client().get("/")
    assert response.status_code == 200
    assert "Content-Security-Policy" in response.headers
    for page in (
        "dashboard",
        "map",
        "planner",
        "graph",
        "nodes",
        "node",
        "chat",
        "meshnet",
        "firehose",
        "stats",
        "traceroutes",
        "packet",
        "traceroute",
        "link",
    ):
        assert f'data-page="{page}"' in response.text


def test_dashboard_scripts_and_styles_are_local() -> None:
    """Every script and stylesheet comes from the local static directory."""
    text = _client().get("/").text
    assets = re.findall(r'<(?:script[^>]*\ssrc|link[^>]*\shref|img[^>]*\ssrc)="([^"]+)"', text)
    assert assets, "the page must reference its local assets"
    for asset in assets:
        assert asset.startswith("static/"), asset


def test_brand_mark_is_optional() -> None:
    """The page keeps a text wordmark when no logo file is present.

    The mark is revealed by script only after the image loads, so a
    missing file never shows a broken image.
    """
    text = _client().get("/").text
    assert 'src="static/logo.png"' in text
    assert "data-brand-text" in text
    script = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    assert "data-brand-mark" in script


def test_dashboard_injects_the_client_configuration() -> None:
    """The page carries the map settings, and the CSP allows the tile host."""
    app = create_app(Settings(_env_file=None, map_tile_url="https://tiles.example/{z}/{x}/{y}.png"))
    response = TestClient(app).get("/")
    assert "__SONORAN_CONFIG__" not in response.text
    assert '"tileUrl": "https://tiles.example/{z}/{x}/{y}.png"' in response.text
    csp = response.headers["Content-Security-Policy"]
    assert "img-src 'self' data: https://tiles.example" in csp


def _connect_src(csp: str) -> str:
    """Return the connect-src directive out of a policy."""
    for directive in csp.split(";"):
        if directive.strip().startswith("connect-src"):
            return directive.strip()
    raise AssertionError(f"no connect-src in {csp}")


def test_csp_allows_a_remote_api_origin() -> None:
    """A cross-origin API base must be a connect source.

    Without this the browser blocks every fetch and the page is empty.
    """
    app = create_app(Settings(_env_file=None, web_api_base_url="http://192.0.2.125:8000"))
    directive = _connect_src(TestClient(app).get("/").headers["Content-Security-Policy"])
    assert "http://192.0.2.125:8000" in directive


def test_csp_connect_source_defaults_to_self() -> None:
    """A same-origin deployment adds no origin of its own.

    The firmware release host is always there, for the config checker.
    Nothing else may be.
    """
    directive = _connect_src(_client().get("/").headers["Content-Security-Policy"])
    assert directive == "connect-src 'self' https://api.github.com"


def test_dashboard_without_tiles_keeps_a_sealed_image_policy() -> None:
    """With no tile host and no graph host, no external image is allowed."""
    app = create_app(Settings(_env_file=None, map_tile_url="", mesh_graph_base_url=""))
    response = TestClient(app).get("/")
    assert "img-src 'self' data:;" in response.headers["Content-Security-Policy"]


def test_graph_origin_is_an_image_source() -> None:
    """The traceroute inspector embeds a drawing rendered by mesh-graph.

    That image comes from the graph origin, so the policy must allow it.
    """
    app = create_app(
        Settings(_env_file=None, map_tile_url="", mesh_graph_base_url="https://graphs.example")
    )
    response = TestClient(app).get("/")
    assert (
        "img-src 'self' data: https://graphs.example;"
        in response.headers["Content-Security-Policy"]
    )


def test_dashboard_uses_base_relative_api_paths() -> None:
    """The dashboard can run below a configured path prefix."""
    app = create_app(Settings(_env_file=None, web_base_path="/mesh"))
    assert app.root_path == "/mesh"
    response = TestClient(app).get("/")
    assert response.status_code == 200
    assert 'src="static/app.js"' in response.text
    assert "document.baseURI" in (STATIC_DIR / "app.js").read_text(encoding="utf-8")


def test_planner_scripts_load_before_the_router() -> None:
    """planner.js must come before app.js.

    app.js runs the router as its last act. If the planner has not
    registered itself by then, a reload on #planner falls back to the
    dashboard instead of opening the planner.
    """
    text = _client().get("/").text
    assert text.index("static/planner.js") < text.index("static/app.js")
    assert text.index("static/planner-params.js") < text.index("static/planner.js")


def test_csp_allows_webassembly() -> None:
    """The planner compiles a WebAssembly module.

    Without this the browser refuses, and the page fails with nothing
    the user can see. See AGENTS.md 9.9.
    """
    csp = _client().get("/").headers["Content-Security-Policy"]
    assert "'wasm-unsafe-eval'" in csp
    assert "worker-src 'self'" in csp


def test_write_methods_rejected() -> None:
    client = _client()
    for method in ("post", "put", "patch", "delete"):
        response = getattr(client, method)("/health")
        assert response.status_code == 405


def test_registered_api_routes_are_read_only() -> None:
    """No registered API route accepts a write method."""
    app = create_app(Settings(_env_file=None))
    for route in app.routes:
        methods = getattr(route, "methods", None)
        if methods and getattr(route, "path", "").startswith("/api"):
            assert methods <= {"GET"}


def test_the_radio_route_is_registered() -> None:
    """The coverage work reads a node's radio through the API."""
    paths = {route.path for route in nodes.router.routes}
    assert "/api/nodes/{node_id}/radio" in paths


def test_the_radio_overrides_are_read_once_at_startup() -> None:
    """Reading the file for each request would be waste.

    The file ships with the image, so a change to it arrives with a
    deploy and never during the life of a process.
    """
    app = create_app(Settings(_env_file=None, radio_overrides_path="does-not-exist.yaml"))
    assert app.state.radio_overrides.nodes == {}


def test_core_documented_routes_are_registered() -> None:
    """The primary documented route groups are present."""
    routers = (
        nodes.router,
        packets.router,
        chat.router,
        graph.router,
        map_routes.router,
        stats.router,
        traceroutes.router,
    )
    paths = {route.path for router in routers for route in router.routes}
    assert {
        "/api/nodes",
        "/api/nodes/{node_id}/detail",
        "/api/nodes/{node_id}/signal",
        "/api/packets",
        "/api/chat",
        "/api/chat/overview",
        "/api/chat/tagged",
        "/api/graph",
        "/api/map/nodes",
        "/api/map/traffic",
        "/api/stats",
        "/api/traceroutes",
    } <= paths


def test_packet_portnum_accepts_name_and_number() -> None:
    """Packet filters accept the documented port-number forms."""
    assert _parse_portnum("TEXT_MESSAGE_APP") == _parse_portnum("1")


def test_display_timezone_reaches_the_page() -> None:
    """Every time on the page is shown in the mesh's own zone.

    Arizona keeps MST all year. Without this the browser uses its own
    zone and a viewer elsewhere reads every time shifted.
    """
    text = _client().get("/").text
    assert '"timezone": "America/Phoenix"' in text
    script = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    assert "timeZone: TZ" in script, "the formatters must use the configured zone"


def test_display_timezone_is_configurable() -> None:
    app = create_app(Settings(_env_file=None, display_timezone="UTC"))
    assert '"timezone": "UTC"' in TestClient(app).get("/").text


def test_the_dashboard_refuses_to_be_framed() -> None:
    """Nothing may put the dashboard inside a page of its own.

    The config check page uses the checker's logic directly, so nothing
    is framed and the strictest setting stands.
    """
    response = _client().get("/")
    assert response.headers["X-Frame-Options"] == "DENY"
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]


def test_permissions_policy_grants_serial_and_denies_the_rest() -> None:
    """The config checker reads a node over USB. Nothing else is allowed.

    Without this header the browser permits every feature by default, so
    anything the dashboard serves could reach a camera or a location.
    """
    policy = _client().get("/").headers["Permissions-Policy"]
    assert "serial=(self)" in policy
    for feature in ("camera", "microphone", "geolocation", "usb", "payment", "bluetooth"):
        assert f"{feature}=()" in policy, feature


def test_the_firmware_check_host_is_a_connect_source() -> None:
    """The config checker asks GitHub which firmware release is current.

    It is the only outbound request the dashboard makes and it carries
    no user data. Without the source the check fails silently.
    """
    csp = _client().get("/").headers["Content-Security-Policy"]
    assert "https://api.github.com" in csp


def test_the_config_check_page_has_the_logic_it_imports() -> None:
    """The page imports the checker's modules, so they must be there."""
    page = (STATIC_DIR / "config-check.js").read_text(encoding="utf-8")
    imports = re.findall(r"from '(\./vendor/config-checker/[^']+)'", page)
    assert imports, "the page must import the vendored logic"
    for path in imports:
        assert (STATIC_DIR / path.removeprefix("./")).is_file(), path


def test_the_checker_globals_are_loaded_before_the_module() -> None:
    """The vendored logic reads three globals off `window`.

    Its own page loads them as classic scripts. Without them every parse
    fails with "jsyaml is not defined", and only the build-from-scratch
    path works, which is the one path that parses nothing.
    """
    text = _client().get("/").text
    for name in ("protobuf.min.js", "js-yaml.min.js", "meshtastic-proto.js"):
        assert name in text, name
        assert text.index(name) < text.index("static/config-check.js"), name


def test_the_config_checker_adds_no_endpoint() -> None:
    """Nothing about this feature is processed on the server.

    The checker reads a config in the browser and sends it nowhere. If
    an endpoint ever appears for it, that promise is broken.
    """
    app = create_app(Settings(_env_file=None))
    paths = {getattr(route, "path", "") for route in app.routes}
    assert not [path for path in paths if "config" in path.lower()]


def test_the_dashboard_forbids_run_time_code_compilation() -> None:
    """`unsafe-eval` must never appear in the policy.

    The config check page reads a file the user supplies. Without this
    restriction a crafted config could become running code. It is also
    why an Android .cfg cannot be read here: protobuf.js builds its
    decoders with `new Function`. See AGENTS.md 9.17.
    """
    csp = _client().get("/").headers["Content-Security-Policy"]
    assert "'unsafe-eval'" not in csp.replace("'wasm-unsafe-eval'", "")


def test_the_precompiled_protobuf_never_compiles_code() -> None:
    """Android .cfg support must not need `unsafe-eval`.

    protobuf.js normally builds decoders with `new Function`. The policy
    forbids that, so the schema is compiled ahead of time instead. If a
    regenerated module ever carries a `Function(` call, the point of it
    has been lost. See AGENTS.md 9.17.
    """
    module = (STATIC_DIR / "meshtastic-static.js").read_text(encoding="utf-8")
    assert "new Function" not in module
    assert "Function(" not in module
    # A bare specifier cannot be resolved by a browser.
    assert "protobufjs/minimal" not in module
    assert "./protobuf-runtime.js" in module
