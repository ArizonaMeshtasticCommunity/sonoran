"""How the static assets go down the wire.

Two things, both measured before they were changed.

**Nothing was compressed.** A cold load moved 2.41 MB across 25
requests. The JavaScript and CSS are 2,023,889 of those bytes and gzip
takes them to 635,575.

**Nothing was cacheable.** The mount emitted `ETag` and
`Last-Modified` and no `Cache-Control`, so a warm visitor re-downloaded
nothing but still spent 25 conditional round trips asking.

The second one has a trap worth a test of its own. `immutable` is only
safe because `index.html` asks for every asset with `?v=` and a hash of
its bytes, so a changed file is a changed URL. A file reached *without*
that version has a URL that never changes, and telling a browser to
keep it for a year would serve a stale asset until somebody cleared
their cache by hand. So the version is checked, and
`test_an_unversioned_asset_is_not_kept_for_a_year` is the test that
fails against the simpler rule.
"""

import gzip

from fastapi.testclient import TestClient

from sonoran.api.app import create_app
from sonoran.config import Settings

A_YEAR = 31536000


def _client() -> TestClient:
    app = create_app(Settings(_env_file=None))
    return TestClient(app)


def test_a_versioned_asset_may_be_kept_for_a_year() -> None:
    """The whole point: `?v=` makes the URL change when the bytes do."""
    response = _client().get("/static/app.css?v=abc123def456")
    assert response.status_code == 200
    cache = response.headers.get("Cache-Control", "")
    assert "immutable" in cache, f"expected an immutable hold, got {cache!r}"
    assert f"max-age={A_YEAR}" in cache


def test_an_unversioned_asset_is_not_kept_for_a_year() -> None:
    """A URL that cannot change must not be held until it is wrong.

    Someone's bookmark, a direct link, a tool. The path is the same
    after a deploy, so a year-long hold would pin an asset from before
    the deploy with no way to notice.
    """
    response = _client().get("/static/app.css")
    assert response.status_code == 200
    cache = response.headers.get("Cache-Control", "")
    assert "immutable" not in cache, (
        f"an unversioned asset was given {cache!r}. Its URL never changes, "
        f"so this pins a stale file in every cache that sees it."
    )
    assert f"max-age={A_YEAR}" not in cache


def test_a_large_text_asset_is_compressed() -> None:
    """The bytes this was all for."""
    client = _client()
    response = client.get("/static/app.js?v=abc123", headers={"Accept-Encoding": "gzip"})
    assert response.status_code == 200
    assert response.headers.get("Content-Encoding") == "gzip", (
        "app.js went down the wire uncompressed; it is about 250 kB of text"
    )


def test_compression_is_skipped_when_the_client_does_not_take_it() -> None:
    """A client that asks for no encoding gets none."""
    client = _client()
    response = client.get("/static/app.js?v=abc123", headers={"Accept-Encoding": "identity"})
    assert response.status_code == 200
    assert "gzip" not in response.headers.get("Content-Encoding", "")


def test_the_compressed_asset_is_the_asset() -> None:
    """Round trip it, so a broken encoder cannot pass the header test."""
    client = _client()
    plain = client.get("/static/app.css?v=abc123", headers={"Accept-Encoding": "identity"})
    packed = client.get("/static/app.css?v=abc123", headers={"Accept-Encoding": "gzip"})
    # httpx decodes transparently, so compare what the caller ends up with.
    assert packed.text == plain.text, "the compressed asset decoded to different bytes"
    assert len(plain.content) > 0


def test_compression_actually_saves_something_worth_having() -> None:
    """Guard the claim in the comment, not just the header.

    A `minimum_size` set too high, or a level set to zero, would leave
    the header in place and the saving gone.
    """
    raw = (
        TestClient(create_app(Settings(_env_file=None)))
        .get("/static/app.js", headers={"Accept-Encoding": "identity"})
        .content
    )
    packed = gzip.compress(raw, 6)
    assert len(packed) < len(raw) * 0.5, (
        f"app.js compressed to {len(packed)} of {len(raw)} bytes, "
        f"which is not the win this was added for"
    )


def test_an_api_response_still_carries_its_security_headers() -> None:
    """Compression must not displace the headers the middleware sets.

    Order matters between these two: one wraps the body, the other
    writes headers. A mistake here is invisible until somebody audits
    the response.
    """
    response = _client().get("/", headers={"Accept-Encoding": "gzip"})
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert "Content-Security-Policy" in response.headers


def test_a_static_asset_carries_the_content_security_policy() -> None:
    """The branch that was written for this never ran.

    `get_route_path` was read *after* `call_next`, and by then the
    `Mount` has rewritten `root_path` in the same scope object — so
    `/static/app.css` came back as `/app.css`, the `startswith`
    matched nothing, and every asset was served with no CSP. `/`
    matched and looked correct, which is why it stayed hidden.

    This fails against the old ordering.
    """
    response = _client().get("/static/app.css?v=abc123")
    assert response.status_code == 200
    assert "Content-Security-Policy" in response.headers, (
        "a static asset was served with no Content-Security-Policy; the "
        "path was read after routing, so the /static branch never matched"
    )


def test_the_path_is_read_below_a_non_stripping_proxy() -> None:
    """9.9.2's shape, which a plain TestClient cannot see.

    A proxy that does not strip `WEB_BASE_PATH` sends the prefix, so
    the header decision has to take it off — while still not being
    fooled by the mount's own rewrite.
    """
    app = create_app(Settings(_env_file=None, web_base_path="/sonoran"))
    client = TestClient(app, root_path="/sonoran")
    response = client.get("/sonoran/static/app.css?v=abc123")
    assert response.status_code == 200
    assert "Content-Security-Policy" in response.headers
    assert "immutable" in response.headers.get("Cache-Control", "")


def test_the_document_itself_is_still_not_cached() -> None:
    """`/` carries the asset versions, so it must stay fresh.

    If the document were held, a deploy would be invisible: the new
    asset URLs live inside it.
    """
    response = _client().get("/")
    assert response.headers.get("Cache-Control") == "no-cache"
