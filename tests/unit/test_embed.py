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
