"""Which paths a third party may frame is a list, not a prefix.

`_is_embed` decided with `path.startswith("/embed/")`. That is correct
for the one embed document that exists and wrong for every one that does
not exist yet: a page added under `/embed/` later would inherit
third-party `frame-ancestors` and lose `X-Frame-Options` without anybody
choosing it, and would work, so nothing would say so.

The list is now explicit. These tests are the other half -- they read
the application's real routing table, so an embed route added without a
matching entry fails here instead of quietly picking up the policy.

See also AGENTS.md 9.9.2: the header decision must use the routed path.
That part is unchanged and still covered by `test_embed.py`; this file
is only about WHICH paths the decision applies to.
"""

from sonoran.api.app import _EMBED_PATHS, _EMBED_TILE_PREFIX, _is_embed, create_app


def _all_routes() -> set[str]:
    """Every registered path, including inside included routers.

    This FastAPI wraps `include_router` in `_IncludedRouter` objects
    rather than flattening them into `app.routes`, and those expose
    their children on `original_router`, not `routes`. Walking only
    `app.routes` finds FOUR paths out of 67 and no embed routes at all
    -- which would have made the "every embed route is named" test pass
    by enumerating nothing.
    """
    app = create_app()

    def walk(routes: object) -> "list[str]":
        out: list[str] = []
        for route in routes or []:  # type: ignore[union-attr]
            path = getattr(route, "path", None)
            if path:
                out.append(path)
            inner = getattr(route, "original_router", None)
            if inner is not None:
                out.extend(walk(getattr(inner, "routes", [])))
            out.extend(walk(getattr(route, "routes", [])))
        return out

    return set(walk(app.routes))


def test_the_route_walk_actually_finds_routes() -> None:
    """The control for the two tests below.

    Both of them are satisfied by an empty list. The first version of
    this file walked `app.routes` only, found nothing, and would have
    reported the allowlist as complete forever.
    """
    routes = _all_routes()
    assert len(routes) > 50, f"the route walk found only {len(routes)} paths"
    assert any("embed" in path for path in routes), (
        "the route walk found no embed routes at all, so the tests below "
        "would pass no matter what the allowlist said"
    )


def _embed_routes() -> list[str]:
    """Every registered route living in the embed namespaces."""
    return sorted(
        path
        for path in _all_routes()
        if path.startswith("/embed/") or path.startswith("/api/embed/")
    )


def test_every_registered_embed_route_is_named() -> None:
    """Adding an embed route must be a decision, and a visible one."""
    for path in _embed_routes():
        covered = path in _EMBED_PATHS or path.startswith(_EMBED_TILE_PREFIX)
        assert covered, (
            f"{path} is registered under an embed namespace but is not in "
            f"_EMBED_PATHS, so it would be served with the dashboard's policy "
            f"-- or, if the prefix match ever comes back, would silently "
            f"inherit the embed's instead. Add it deliberately."
        )


def test_nothing_is_named_that_is_not_a_route() -> None:
    """A stale entry hands embed policy to a path that may be re-used."""
    registered = set(_embed_routes())
    for path in _EMBED_PATHS:
        assert path in registered, (
            f"{path} is in _EMBED_PATHS but is not a registered route; a "
            f"later route reusing that path would inherit embed policy"
        )


def test_an_unregistered_page_under_embed_is_not_framed() -> None:
    """The actual defect, stated directly.

    Under the old prefix match every one of these returned True.
    """
    for path in (
        "/embed/admin",
        "/embed/coverage/secret",
        "/embed/",
        "/api/embed/internal",
    ):
        assert not _is_embed(path), (
            f"{path} is not a real embed route, but the framing policy treats it as one"
        )


def test_the_real_embed_paths_still_are() -> None:
    """The fix must not close the hole by closing the door."""
    assert _is_embed("/embed/coverage")
    assert _is_embed("/api/embed/coverage")
    assert _is_embed("/api/embed/nodes")
    assert _is_embed("/api/embed/tiles/abc123/LongFast/rx/10/200/400.png")


def test_the_dashboard_is_untouched() -> None:
    for path in ("/", "/static/app.js", "/api/nodes", "/api/graph"):
        assert not _is_embed(path)
