"""The shape of the pages, and getting around them without a mouse.

Same reason as `test_ui_readability.py`: there is no JavaScript test runner
here, so a rule that a later edit drops leaves nothing broken at a glance.
Every item below was found in a rendered screenshot or in a keyboard pass,
not in the markup.
"""

import re

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
    hold forty rows and grow while you watch.

    Since #296 the dashboard list is not a `.feed`, so the cap cannot
    reach it; `.messages` has none.
    """
    css = _read("app.css")
    assert "max-height: 26rem" in css
    messages = css[css.index(".messages { list-style: none;") :]
    assert "max-height" not in messages[: messages.index("}")]


def test_the_dashboard_messages_use_the_message_styling() -> None:
    """#296: as a `.feed` the list got none of the `.messages` rules.

    The name was a bordered button, the channel ran into the time, and the
    time was an underlined link in the browser's own blue. Five rows, and
    a way to all of them at the foot of the panel.
    """
    text = _client().get("/").text
    dashboard = text[text.index('data-page="dashboard"') : text.index('data-page="map"')]
    tag = dashboard[: dashboard.index("data-recent-chat>")]
    tag = tag[tag.rindex("<ul") :]
    assert 'class="messages' in tag, f"the dashboard list is not `.messages`: {tag}"
    foot = dashboard[dashboard.index("data-recent-chat>") :]
    foot = foot[: foot.index("</div>")]
    assert '<a class="more" href="#chat">View all messages</a>' in foot, (
        "the View all messages link is missing, or does not open the chat overview"
    )
    app = _read("app.js")
    assert "const DASHBOARD_MESSAGES = 5;" in app
    assert "api/chat?limit=${DASHBOARD_MESSAGES}" in app
    assert "showChannel: true" not in app[app.index("PAGES.dashboard = ") :][:4000], (
        "the dashboard repeats the channel on every row again"
    )


def test_a_finger_gets_a_target_it_can_hit() -> None:
    """The base control is about 34 px tall.

    That clears WCAG 2.2 SC 2.5.8 Target Size (Minimum) at 24x24 CSS px
    and sits under both vendor recommendations — Apple's 44x44 pt
    default control size and Material Design 3's 48x48 dp — so the
    narrow breakpoint raises it to 2.75 rem, which is 44 px.

    Read from the whole media block rather than its first 600
    characters: the citation above is longer than that window was.

    The block is keyed on the pointer as well as the width (#267): an
    iPad in landscape is wider than 60 rem and touched with a finger.
    """
    css = _read("app.css")
    start = css.index("@media (max-width: 60rem), (pointer: coarse) {")
    narrow = css[start:].split("\n}\n", 1)[0]
    assert "min-height: 2.75rem;" in narrow
    # The rule has to reach the controls and the nav links, not just one
    # of the two: the nav is thirteen of the targets on the page.
    assert "input, select, button, .sidebar nav a" in narrow


# --------------------------------------------------------------- mobile
#
# The named criteria each of these holds the page to. They are asserted
# against the source because there is no JavaScript test runner here and
# a rule that a later edit drops leaves nothing broken at a glance. The
# browser-side half lives in `tools/dev/e2e.js`, which measures the same
# things in a real phone viewport.


def test_the_viewport_never_locks_the_zoom() -> None:
    """W3C ACT rule b4f0c3 "Meta viewport allows for zoom", for WCAG 2.2
    SC 1.4.4 Resize text (Level AA): `user-scalable` must not be `no`,
    and `maximum-scale` must not be below 2.

    Both are the tempting way to stop iOS zooming a focused input, and
    both take the page's zoom away from everybody who needs it. The
    conformant answer is a 16 px control, asserted below.
    https://www.w3.org/WAI/standards-guidelines/act/rules/b4f0c3/
    """
    import re

    for text in (_client().get("/").text, _read("embed-coverage.html")):
        tags = re.findall(r'<meta name="viewport" content="([^"]*)"', text)
        assert tags, "no viewport declaration"
        for content in tags:
            assert "user-scalable" not in content, content
            assert "maximum-scale" not in content, content
            assert "width=device-width" in content, content


def test_the_dashboard_fills_the_display_and_pads_the_safe_area() -> None:
    """`env(safe-area-inset-*)` reports 0 on every side until the
    viewport carries `viewport-fit=cover`, so the two belong together or
    neither does anything. The manifest asks for a standalone install,
    which is the case where the page really does own the screen edges.
    https://webkit.org/blog/7929/designing-websites-for-iphone-x/
    """
    assert "viewport-fit=cover" in _client().get("/").text
    css = _read("app.css")
    # Each one carries the `0px` fallback: a missing fallback is the
    # usual way this pattern ships broken, because `calc()` over an
    # unresolved `env()` throws the whole declaration away.
    for side in ("top", "right", "bottom", "left"):
        assert f"env(safe-area-inset-{side}, 0px)" in css, side
    # And watch mode uses them. It is the one mode that is `position:
    # fixed; inset: 0`, so it is the one that reaches the notch.
    watch = css[css.index(".watch-bar {") :].split("\n}", 1)[0]
    assert "var(--safe-top)" in watch


def test_no_grid_track_is_wider_than_a_narrow_screen() -> None:
    """WCAG 2.2 SC 1.4.10 Reflow (Level AA): no two-dimensional scrolling
    at 320 CSS px.

    `minmax(24rem, 1fr)` is a hard 384 px floor, so the dashboard, the
    map feeds, the config check and the statistics page all laid out
    384 px wide inside a 320 px window. `min(24rem, 100%)` keeps the
    wrapping threshold and collapses below it.
    https://www.w3.org/TR/WCAG22/#reflow
    """
    import re

    css = _read("app.css")
    # How much width a grid can actually have at a 320 px viewport: the
    # narrow `.content` takes 1 rem of padding on each side, and a grid
    # inside a `.panel` loses another 1 rem on each side. 320 px less
    # four 16 px gutters is 256 px, which is 16 rem. A bare floor at or
    # under that fits wherever it is put; above it, the track cannot
    # shrink and the document scrolls sideways.
    fits = 16.0
    for declaration in re.findall(r"grid-template-columns:\s*repeat\([^;]+;", css):
        for floor in re.findall(r"minmax\(\s*(\d[\d.]*)rem\s*,", declaration):
            assert float(floor) <= fits, (
                f"{floor}rem track floor cannot shrink below 320 px; "
                f"wrap it in min({floor}rem, 100%): {declaration.strip()}"
            )
    # And the two that are over the line do wrap, rather than having been
    # shrunk to fit — the threshold itself is unchanged on a desktop.
    assert "minmax(min(24rem, 100%), 1fr)" in css
    assert "minmax(min(26rem, 100%), 1fr)" in css


def test_a_touch_control_is_never_under_sixteen_pixels() -> None:
    """Safari on iOS zooms the page in when a form control under 16 px
    takes focus, and does not zoom back out.

    The base font here is 15 px and the planner's fields inherit a
    0.76 rem label, so every control on the site did it. `hover: none`
    rather than a width query, because an iPad in landscape is 1024 px
    wide and zooms exactly like a phone.
    https://css-tricks.com/16px-or-larger-text-prevents-ios-form-zoom/
    """
    css = _read("app.css")
    touch = css[css.index("@media (hover: none) {") :].split("\n}", 1)[0]
    assert "input, select, textarea" in touch
    assert "16px" in touch
    # The embed is its own document and its own stylesheet, and it is
    # the worse case: it is framed on somebody else's page, so the page
    # that gets zoomed is theirs.
    assert "font-size: 16px" in _read("embed-coverage.html")


def test_element_heights_use_the_small_viewport() -> None:
    """Per CSS Values and Units Level 4, `vh` is the LARGE viewport: the
    viewport with the browser's retractable chrome retracted. On a phone
    showing the address bar, `100vh` is taller than the screen.

    `svh` rather than `dvh`: `dvh` resizes while the page is scrolled,
    which would make Leaflet re-measure on every frame.
    https://www.w3.org/TR/css-values-4/#large-viewport-size
    """
    import re

    css = _read("app.css")
    # A `vh` that is not part of `svh`, `lvh` or `dvh`, outside comments.
    without_comments = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    stray = re.findall(r"(?<![sld])\b\d+vh\b", without_comments)
    assert not stray, f"plain vh left: {stray}"
    assert "max(20rem, 70svh)" in css


def test_no_hint_lives_only_in_a_tooltip() -> None:
    """The HTML Living Standard: relying on `title` "excludes
    keyboard-only users and touch-only users, such as anyone with a
    modern phone or tablet".

    Every place the dashboard put an explanation in `title` carries it
    in `data-hint` instead, and `revealHints` turns each one into a
    button on the heading or the tile label it explains. See
    `test_column_hints.py` for the control itself.
    https://html.spec.whatwg.org/multipage/dom.html#the-title-attribute
    """
    script = _read("app.js")
    # Both `th` paths — the plain heading and the sortable one — and the
    # summary tile.
    assert script.count("'data-hint': column.hint || null,") == 2
    assert "'data-hint': hint || null," in script
    # The exact protocol values, which had no copy outside `title` at all.
    assert "'data-exact': role," in script
    assert "'data-exact': String(portnum)," in script
    assert "function revealHints(" in script
    # And it is called after every render, not only on first paint.
    assert "revealHints(page);" in script


# ------------------------------------------------------ one-row heads (#299)


def _page_head(html: str, page: str) -> str:
    """From the page's head to its Options panel, which follows the head."""
    start = html.index("page-head", html.index(f'data-page="{page}"'))
    return html[start : html.index(f'id="{page}-options"', start)]


def test_the_graph_head_keeps_four_controls_and_options_holds_the_rest() -> None:
    """Will approved: Layout, the two link toggles and Reset layout go behind
    an Options button, so the rest fits on the title row."""
    html = re.sub(r"<!--.*?-->", "", _read("index.html"), flags=re.S)
    head = _page_head(html, "graph")
    for kept in ("data-graph-hours", "data-graph-search", "data-graph-view", "data-options-open"):
        assert kept in head, f"{kept} left the graph head"
    panel = html[html.index('id="graph-options"') :]
    panel = panel[: panel.index("</div>")]
    for moved in (
        "data-graph-layout",
        "data-graph-unconfirmed",
        "data-graph-weak",
        "data-graph-reset",
    ):
        assert moved not in head, f"{moved} is still in the graph head"
        assert moved in panel, f"{moved} is not in the Options panel"


def test_the_coverage_layer_is_one_drop_down_in_the_head() -> None:
    """Will approved: the three layer pills become one drop-down."""
    html = re.sub(r"<!--.*?-->", "", _read("index.html"), flags=re.S)
    head = _page_head(html, "coverage")
    assert re.search(r"<select data-coverage-layers\b", head), (
        "the layer is not a select in the head"
    )
    assert "data-options-open" in head
    panel = html[html.index('id="coverage-options"') :]
    assert "data-coverage-views" in panel[: panel.index("</label>")]
    assert "data-coverage-opacity" in panel[: panel.index("</label>")]


# ------------------------------------------------- phones fold the head (#275)


def test_the_phone_fold_keeps_live_and_one_control_in_the_head() -> None:
    """Below 40rem the `data-fold` controls move into the page's panel.

    Each folded control needs a panel in its page to land in, or it stays
    in the head and the phone header is as tall as before. RF has no
    Options of its own, so it carries a phone-only Filters button.
    """
    html = re.sub(r"<!--.*?-->", "", _read("index.html"), flags=re.S)
    for page, folded in {
        "graph": ("data-graph-hours", "data-graph-view"),
        "rf": ("data-rf-layers", "data-rf-minutes"),
    }.items():
        head = _page_head(html, page)
        # Each folded element, whole: a label with its select inside, or
        # the RF span that rf.js fills with toggles.
        chunks = "".join(
            match.group(0)
            for match in re.finditer(
                r"<(label|span)\b[^>]*\bdata-fold\b[^>]*>.*?</\1>", head, flags=re.S
            )
        )
        for name in folded:
            assert name in chunks, f"{page}: {name} does not fold on a phone"
        assert "data-options-open" in head, f"{page} has no button to fold into"
    rf = _page_head(html, "rf")
    assert "data-fold-only" in rf and "data-live" in rf


# ------------------------------------------------- text size on touch (#283)


def _touch_block(css: str) -> str:
    """Return the body of the `@media (pointer: coarse)` block that sets the
    text size. It is found by its custom property, not by its position."""
    for match in re.finditer(r"@media \(pointer: coarse\) \{\n", css):
        body = css[match.end() :].split("\n}\n", 1)[0]
        if "--font-size:" in body:
            return body
    raise AssertionError("no (pointer: coarse) block sets --font-size")


def test_body_text_is_sixteen_pixels_on_a_touch_screen() -> None:
    """The body is 15 px with a mouse and 16 px with a finger (#283).

    Keyed on the pointer and not on the width, as the touch targets are
    (#267): an iPad in landscape is desktop-wide and held at a phone's
    distance, and a narrow desktop window is not. A `max-width` in the
    same query would give the change to a narrow mouse window too.

    The size is its own custom property, so the touch rule changes one
    number and the font family is written once. Leaflet's popups use
    the same `--font`, so they follow.
    """
    css = _read("app.css")
    root = css[css.index(":root {") :].split("\n}\n", 1)[0]
    assert "--font-size: 15px;" in root
    assert "--font: var(--font-size)/1.5 " in root
    assert re.search(r"body \{[^}]*font: var\(--font\);", css)
    touch = _touch_block(css)
    assert re.search(r":root \{[^}]*--font-size: 16px;", touch)
    # The form-control rule still holds every field at 16 px or more, so
    # iOS does not zoom a focused field (see the test above).
    assert "input, select, textarea { font-size: max(16px, 1em); }" in css


def test_no_small_text_escapes_the_touch_floor() -> None:
    """On a touch screen no text in the stylesheet is under 12.5 px (#283).

    The mobile review measured tags at 11.5 px and the filter count at
    11.2 px. Each small size goes through `max(<size>, var(--text-floor))`.
    The floor is 0 with a mouse, so a desktop keeps every size it had,
    and .78 rem (12.48 px) with a finger.

    The check reads every declaration, so a new small size that does not
    take the floor fails here. A list of selectors would keep a deleted
    one and miss a new one.
    """
    css = _read("app.css")
    root = css[css.index(":root {") :].split("\n}\n", 1)[0]
    assert "--text-floor: 0px;" in root
    assert re.search(r":root \{[^}]*--text-floor: \.78rem;", _touch_block(css))

    floor = 0.78
    # Every stylesheet the dashboard loads, not only app.css. gaps.css
    # was missed once, and the Gaps page kept 11.2 px text on a phone.
    # The vendored Leaflet sheet is not ours to edit.
    index = _read("index.html")
    sheets = re.findall(r'href="static/([a-z-]+\.css)', index)
    assert "app.css" in sheets and "gaps.css" in sheets, sheets
    for sheet in sheets:
        bare = [
            f"{size}rem"
            for size in re.findall(r"font-size: *(\d*\.\d+|\d+)rem *[;}]", _read(sheet))
            if float(size) < floor
        ]
        assert not bare, f"{sheet}: small sizes without the touch floor: {bare}"
    floored = re.findall(r"font-size: max\((\d*\.\d+)rem, var\(--text-floor\)\)", css)
    assert floored, "no size takes the floor, so this test reads nothing"
    assert all(float(size) < floor for size in floored)

    # Inline styles in the scripts are text too.
    for name in sorted(p.name for p in STATIC_DIR.glob("*.js")):
        sizes = re.findall(r"font-size: *(\d*\.\d+)rem", _read(name))
        small = [size for size in sizes if float(size) < floor]
        assert not small, f"{name} sets {small} rem inline"
