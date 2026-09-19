"""The shape of the pages, and getting around them without a mouse.

Same reason as `test_ui_readability.py`: there is no JavaScript test runner
here, so a rule that a later edit drops leaves nothing broken at a glance.
Every item below was found in a rendered screenshot or in a keyboard pass,
not in the markup.
"""

from fastapi.testclient import TestClient

from sonoran.api.app import STATIC_DIR, create_app
from sonoran.config import Settings


def _client() -> TestClient:
    app = create_app(Settings(_env_file=None))
    return TestClient(app)


def _read(name: str) -> str:
    return (STATIC_DIR / name).read_text(encoding="utf-8")


def test_the_skip_link_comes_first_and_reaches_the_page() -> None:
    """Thirteen nav links stand in front of every page.

    Without this a keyboard or screen-reader user walks all thirteen on
    every visit. The link is off the screen until it takes focus.
    """
    text = _client().get("/").text
    assert 'class="skip-link" href="#main"' in text
    assert 'id="main"' in text
    # It must be the first focusable thing in the document.
    assert text.index("skip-link") < text.index("<nav")
    assert ".skip-link:focus { top: .5rem; }" in _read("app.css")


def test_the_brand_mark_does_not_remove_the_only_heading() -> None:
    """The mark replaced the h1 with an image.

    `reveal` set `hidden` on the wordmark, so every deployment that ships
    a logo served a document with no h1 in it at all. It is off the screen
    now, not out of the accessibility tree, and the image is decorative.
    """
    assert "text.classList.add('sr-only')" in _read("app.js")
    assert ".sr-only {" in _read("app.css")
    assert 'data-brand-mark src="static/logo.png?v=__SONORAN_ASSET_VERSION__" alt=""' in _read(
        "index.html"
    )


def test_every_control_kind_gets_a_focus_ring() -> None:
    """Three rules gave a ring to three buttons.

    Everything else fell back to the browser's own, which on this warm
    dark background is very hard to find.
    """
    css = _read("app.css")
    block = css[css.index("a:focus-visible,") : css.index(".sr-only {")]
    for selector in ("button:focus-visible", "input:focus-visible", "select:focus-visible"):
        assert selector in block, selector
    assert "outline: 2px solid var(--accent)" in block


def test_a_table_that_scrolls_sideways_is_reachable_from_a_keyboard() -> None:
    """`.table-wrap` has always scrolled and nothing said so.

    The coverage gaps table ends at "Best measured link" on a desktop and
    the nodes table ends at the node ID on a phone. A scrolling box with
    no focusable element in it cannot be reached without a pointer, so the
    columns past the edge were not merely hidden, they were unreachable.
    """
    app = _read("app.js")
    assert "function markScrollableTables(" in app
    assert "markScrollableTables(page);" in app
    # Only when it overflows: a tab stop that scrolls nowhere is a stop
    # for nothing.
    assert "wrap.scrollWidth > wrap.clientWidth + 1" in app
    assert "wrap.removeAttribute('tabindex');" in app
    # And a visible cue, with no measurement and no listener.
    assert "no-repeat scroll;" in _read("app.css")


def test_the_dashboard_and_statistics_grids_leave_no_orphan() -> None:
    """`auto-fit` gave three columns and left the fourth panel alone.

    It also squeezed "Recently heard nodes" until the heading read "HE".
    """
    css = _read("app.css")
    assert '.page[data-page="dashboard"] .grid.two,' in css
    assert "grid-template-columns: repeat(2, minmax(0, 1fr));" in css


def test_the_two_long_dashboard_tables_share_a_row() -> None:
    """Ordered the other way the grid put a fifteen-row table beside an
    eight-message feed, and the feed had to stretch to match it."""
    text = _client().get("/").text
    dashboard = text[text.index('data-page="dashboard"') : text.index('data-page="map"')]
    assert dashboard.index("data-top-talkers") < dashboard.index("data-recent-chat")


def test_every_chat_card_is_the_same_width() -> None:
    """`auto-fit` collapses an empty track.

    A group holding one channel stretched that card across the whole page
    while the group above it held two cards at half the width. Five of the
    seven groups on the seeded mesh hold one channel, so the page was a
    ladder of different-sized boxes.
    """
    css = _read("app.css")
    assert ".channel-group .grid.two { grid-template-columns: repeat(auto-fill," in css


def test_the_dashboard_feed_is_not_cut_across_a_message() -> None:
    """`max-height` cut the last message in half, which looks like a
    message that ended there. The live feeds on the map keep the cap: they
    hold forty rows and grow while you watch."""
    css = _read("app.css")
    assert '.page[data-page="dashboard"] .feed { max-height: none;' in css
    assert "max-height: 26rem" in css


def test_a_finger_gets_a_target_it_can_hit() -> None:
    """The base control is about 34 px tall, under the 44 px a touch
    target wants, and the nav becomes a wrapped row of thirteen links."""
    css = _read("app.css")
    narrow = css[css.index("@media (max-width: 60rem) {") :]
    assert "min-height: 2.75rem;" in narrow[:600]
