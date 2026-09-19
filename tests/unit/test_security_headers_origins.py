"""Origins from configuration reach a security header. They are checked.

Two findings, and they share a cause: a value out of settings was put
into a response header without being tested for shape.

1. `api/app.py` built `img-src`, `connect-src` and `frame-src` from its
   own `_origin`, which returned `f"{scheme}://{netloc}"` and checked
   nothing. `urlsplit` keeps a semicolon inside a network location, and
   a semicolon in a `Content-Security-Policy` starts a new directive.
   `embed/sanitise.py` **did** check, for `frame-ancestors`, and its
   docstring claimed the rest of the headers used the same check. They
   did not.

2. The middleware read `scope["path"]`, which carries the mount prefix
   when `WEB_BASE_PATH` is set and the proxy does not strip it.
"""

import pytest
from fastapi.testclient import TestClient

from sonoran.api.app import create_app
from sonoran.config import Settings
from sonoran.embed.sanitise import safe_origin


def _policy(client: TestClient, path: str = "/") -> str:
    return client.get(path).headers.get("Content-Security-Policy", "")


def _directives(policy: str) -> list[str]:
    return [part.strip() for part in policy.split(";") if part.strip()]


def _names(policy: str) -> list[str]:
    return [item.split()[0] for item in _directives(policy) if item.split()]


# --- the one origin check ----------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "https://tiles.example.com",
        "http://localhost:8080",
        "https://example.net:443",
        "https://a-b.c.example",
    ],
)
def test_a_plain_origin_is_accepted(url: str) -> None:
    """The ordinary values a deployment configures."""
    assert safe_origin(url) == url


@pytest.mark.parametrize(
    "url",
    [
        # The finding: a semicolon starts a new CSP directive.
        "https://tiles.example.com;script-src 'unsafe-inline' *",
        # A space separates sources, so this smuggles a second one.
        "https://tiles.example.com *",
        # A wildcard host lets anything match.
        "https://*",
        "https://*.example.com",
        # Not a web origin at all.
        "javascript:alert(1)",
        "data:text/html,x",
        "file:///etc/passwd",
        "//example.com",
        "not a url",
        "",
        # Credentials in the authority are not an origin.
        "https://user:pass@example.com",
    ],
)
def test_anything_that_is_not_an_origin_is_refused(url: str) -> None:
    """Refused, not repaired. There is no safe reading of these."""
    assert safe_origin(url) is None


def test_the_path_and_query_are_dropped() -> None:
    """A tile URL carries a path template. Only the origin is wanted."""
    assert safe_origin("https://tile.example.org/{z}/{x}/{y}.png?k=v") == "https://tile.example.org"


# --- the policy the browser actually gets ------------------------------


HOSTILE_TILE_URL = "https://tiles.example.com;script-src 'unsafe-inline' *;x/{z}/{x}/{y}.png"


def test_a_crafted_tile_url_cannot_add_a_directive() -> None:
    """The finding, end to end.

    Before the fix this policy held two `script-src` directives, and the
    injected one came first:

        img-src 'self' data: https://tiles.example.com
        script-src 'unsafe-inline' *          <-- injected, position 2
        ...
        script-src 'self' 'unsafe-inline' 'wasm-unsafe-eval'

    A browser honours the first occurrence of a directive, so the
    dashboard's script policy became a wildcard with `'unsafe-inline'`.
    """
    with TestClient(create_app(Settings(_env_file=None, map_tile_url=HOSTILE_TILE_URL))) as client:
        policy = _policy(client)

    names = _names(policy)
    assert names.count("script-src") == 1, f"a directive was injected: {policy}"
    # And the one that is there is ours.
    script = next(item for item in _directives(policy) if item.startswith("script-src"))
    assert script == "script-src 'self' 'unsafe-inline' 'wasm-unsafe-eval'"
    # The hostile value contributed nothing at all.
    assert "unsafe-inline' *" not in policy
    assert "tiles.example.com" not in policy


def test_every_directive_appears_once() -> None:
    """A repeated directive is the shape an injection takes.

    Checked for the whole header rather than for `script-src` alone, so
    a future source built from settings is covered by this test without
    anybody remembering to extend it.
    """
    settings = Settings(
        _env_file=None,
        map_tile_url=HOSTILE_TILE_URL,
        mesh_graph_base_url="http://graph.example;frame-ancestors *",
        web_api_base_url="https://api.example;default-src *",
    )
    with TestClient(create_app(settings)) as client:
        policy = _policy(client)

    names = _names(policy)
    assert len(names) == len(set(names)), f"a directive repeats: {policy}"


def test_a_good_tile_host_still_reaches_the_image_sources() -> None:
    """The check must not break the feature it protects.

    `AGENTS.md` 9.9: a tile host missing from `img-src` is blocked by
    the browser with no visible error.
    """
    settings = Settings(
        _env_file=None,
        map_tile_url="https://tile.openstreetmap.org/{z}/{x}/{y}.png",
        mesh_graph_base_url="http://localhost:8080",
        web_api_base_url="https://api.azmsh.net",
    )
    with TestClient(create_app(settings)) as client:
        policy = _policy(client)

    assert "https://tile.openstreetmap.org" in policy
    assert "http://localhost:8080" in policy
    assert "https://api.azmsh.net" in policy


def test_a_refused_origin_is_reported(caplog: pytest.LogCaptureFixture) -> None:
    """Silence is the trap. The browser gives no error, so we must.

    A tile host that is dropped from `img-src` draws nothing and says
    nothing. Without this line an operator has a blank map and no
    thread to pull.
    """
    settings = Settings(_env_file=None, map_tile_url=HOSTILE_TILE_URL)
    with caplog.at_level("WARNING"):
        with TestClient(create_app(settings)) as client:
            _policy(client)

    assert any("MAP_TILE_URL" in record.message for record in caplog.records), caplog.text


def test_an_empty_setting_is_not_reported(caplog: pytest.LogCaptureFixture) -> None:
    """Empty is how a deployment turns a feature off, not a mistake.

    `MAP_TILE_URL=` hides the basemap on purpose. Warning about it
    every request would train an operator to ignore the warning that
    matters.
    """
    settings = Settings(_env_file=None, map_tile_url="", web_api_base_url="")
    with caplog.at_level("WARNING"):
        with TestClient(create_app(settings)) as client:
            _policy(client)

    assert not any("MAP_TILE_URL" in record.message for record in caplog.records)


def test_the_embed_policy_is_built_from_the_same_check() -> None:
    """The embed's own `img-src` takes the tile host too."""
    settings = Settings(
        _env_file=None,
        embed_enabled=True,
        map_tile_url=HOSTILE_TILE_URL,
        embed_frame_ancestors=["https://azmsh.net"],
    )
    with TestClient(create_app(settings)) as client:
        policy = _policy(client, "/embed/coverage")

    names = _names(policy)
    assert len(names) == len(set(names)), f"a directive repeats: {policy}"
    assert "frame-ancestors https://azmsh.net" in policy
