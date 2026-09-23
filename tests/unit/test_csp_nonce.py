"""No `unsafe-inline` in `script-src`.

It used to be there, and it is the reason the stored XSS in #81 could
run: a node named `<img src=x onerror=...>` reached an innerHTML sink,
and the policy permitted the handler. That sink is fixed, but a policy
that would allow the next one is a policy doing nothing.

Driven in a real browser against the real app, injecting the same
shape of payload:

    old policy   injected inline handler executed: true,  0 violations
    new policy   injected inline handler executed: false, 1 violation

and with the page still working either way -- the theme script ran
before paint, the config line ran, and the external scripts ran.

Two inline scripts genuinely need to run, so both carry a nonce: the
theme, which must go before first paint or a light reader sees a dark
frame, and the one line carrying the server's config.
"""

import re

from fastapi.testclient import TestClient

from sonoran.api.app import create_app
from sonoran.config import Settings


def _client() -> TestClient:
    return TestClient(create_app(Settings(_env_file=None)))


def _script_src(csp: str) -> str:
    return next(d.strip() for d in csp.split(";") if d.strip().startswith("script-src"))


def test_inline_script_is_not_allowed_wholesale() -> None:
    response = _client().get("/")
    directive = _script_src(response.headers["Content-Security-Policy"])
    assert "'unsafe-inline'" not in directive, (
        f"script-src still allows every inline script: {directive!r}. This is "
        f"the directive that let the #81 payload run."
    )


def test_the_policy_and_the_document_name_the_same_nonce() -> None:
    """A nonce in the header that no tag carries blocks the page.

    This is the failure that would take the whole dashboard down, so
    it is worth its own test rather than being implied by the others.
    """
    response = _client().get("/")
    policy = re.findall(r"nonce-([A-Za-z0-9_-]+)", response.headers["Content-Security-Policy"])
    tags = re.findall(r'<script nonce="([A-Za-z0-9_-]+)"', response.text)
    assert policy, "the policy names no nonce"
    assert tags, "no inline script carries a nonce"
    assert set(tags) == set(policy), (
        f"the policy names {policy} and the document carries {tags}; the "
        f"inline scripts would be blocked"
    )
    assert "__SONORAN_NONCE__" not in response.text, "a placeholder was left unreplaced"


def test_a_nonce_is_never_served_twice() -> None:
    """A reused nonce is worth nothing: an injection could carry it.

    Safe here only because the document is `no-cache`.
    """
    client = _client()
    header = "Content-Security-Policy"
    first = re.findall(r"nonce-([A-Za-z0-9_-]+)", client.get("/").headers[header])
    second = re.findall(r"nonce-([A-Za-z0-9_-]+)", client.get("/").headers[header])
    assert first and second and first != second, "the same nonce was served twice"
    assert client.get("/").headers.get("Cache-Control") == "no-cache", (
        "the document is cacheable, so a nonce could be replayed from a cache"
    )


def test_the_nonce_is_long_enough_to_be_unguessable() -> None:
    """A short nonce is a guessable one."""
    response = _client().get("/")
    nonce = re.findall(r"nonce-([A-Za-z0-9_-]+)", response.headers["Content-Security-Policy"])[0]
    assert len(nonce) >= 16, f"the nonce is only {len(nonce)} characters"


def test_the_embed_allows_no_inline_script_either() -> None:
    """The embed is the LAST place to keep a blanket allowance.

    It is the one document this project deliberately lets a third party
    frame, so its policy is the one running inside somebody else's
    site. The first version of this change nonced the dashboard and
    left the embed branch alone, which is the more exposed of the two.
    """
    app = create_app(
        Settings(_env_file=None, embed_enabled=True, embed_frame_ancestors=["https://azmsh.net"])
    )
    response = TestClient(app).get("/embed/coverage")
    assert response.status_code == 200
    directive = _script_src(response.headers["Content-Security-Policy"])
    assert "'unsafe-inline'" not in directive, (
        f"the embed still allows every inline script: {directive!r}"
    )


def test_the_embed_policy_and_document_name_the_same_nonce() -> None:
    """A mismatch here breaks a page on somebody else's site."""
    app = create_app(
        Settings(_env_file=None, embed_enabled=True, embed_frame_ancestors=["https://azmsh.net"])
    )
    response = TestClient(app).get("/embed/coverage")
    policy = re.findall(r"nonce-([A-Za-z0-9_-]+)", response.headers["Content-Security-Policy"])
    tags = re.findall(r'<script nonce="([A-Za-z0-9_-]+)"', response.text)
    assert policy and tags and set(tags) == set(policy), (
        f"policy names {policy}, document carries {tags}"
    )
    assert "__SONORAN_NONCE__" not in response.text
