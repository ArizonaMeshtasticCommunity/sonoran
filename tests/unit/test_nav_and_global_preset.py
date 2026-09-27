"""The navigation, the menu footer, and one preset for the whole site.

Will's brief, 2026-09-26: reorder the navigation; move the theme control
to the bottom of the menu and make it readable; put a global Medium
Fast / Long Fast selector above it and take the per-page pickers away;
tidy the connection line; and review the rest of the site for anything
that change touches.

The part worth guarding is the last one. SIX places asked which preset to
show -- the map's link layer, coverage, gaps, the graph's tab strip, the
leaderboards and the chat channel list -- and the two that were easiest to
miss were built in JavaScript rather than sitting in the markup. A seventh
appearing later is the way this regresses, so these cases name them.
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "src" / "sonoran" / "web" / "static"
CASES = ROOT / "tests" / "unit" / "js" / "preset_store_cases.mjs"

REQUESTED_ORDER = [
    "Dashboard",
    "Nodes",
    "Chat",
    "Traceroutes",
    "Map",
    "Graph",
    "Coverage",
    "Planner",
    "Gaps",
    "Config check",
    "Weekly check-in",
    "Firehose",
    "RF",
    "Statistics",
    # Settings is deliberately NOT here. It had an entry at the bottom of
    # this list for part of 2026-09-26, alongside the link in the menu
    # footer, and Will saw the pair: "there is a duplicate settings button
    # on the bottom". The footer link is the one that survives -- he asked
    # for it there, under the preset switch -- and this list is exactly the
    # fourteen pages he named, so an entry added back here fails
    # `test_the_navigation_is_in_the_order_that_was_asked_for` instead of
    # quietly reappearing on the screen.
]


def _html() -> str:
    return (STATIC / "index.html").read_text(encoding="utf-8")


def _code(name: str) -> str:
    """A static file with comments removed.

    This change moved a lot of prose into comments, and several of those
    comments name the very selectors these cases assert are gone.
    Searching the raw source would find the explanation of a removal and
    read it as the thing still being there.
    """
    text = re.sub(r"/\*.*?\*/", "", (STATIC / name).read_text(encoding="utf-8"), flags=re.S)
    return "\n".join(
        line
        for line in text.splitlines()
        if (stripped := line.strip()) and not stripped.startswith("//")
    )


def test_the_comment_stripper_works() -> None:
    """Positive control for `_code`."""
    code = _code("app.js")
    assert "function wirePresetSwitch" in code, "the stripper removed real code"
    assert "Will asked for" not in code, "comment text is leaking through"


# --- the navigation -------------------------------------------------


def test_the_navigation_is_in_the_order_that_was_asked_for() -> None:
    nav = _html()
    nav = nav[nav.index('<nav id="site-nav"') : nav.index("</nav>")]
    assert re.findall(r"</svg>([^<]+)</a>", nav) == REQUESTED_ORDER


def test_every_nav_entry_points_at_a_page_that_exists() -> None:
    """A link to a missing page is a dead entry that looks alive."""
    html = _html()
    nav = html[html.index('<nav id="site-nav"') : html.index("</nav>")]
    for fragment in re.findall(r'data-nav="([a-z]+)"', nav):
        assert f'data-page="{fragment}"' in html, f"#{fragment} has no page"


def test_every_nav_icon_exists() -> None:
    """A `<use>` pointing at a missing symbol renders NOTHING, silently.

    Three separate bugs in this repository have been exactly that, so the
    reorder is checked against the sprite rather than assumed.
    """
    html = _html()
    nav = html[html.index('<nav id="site-nav"') : html.index("</nav>")]
    for icon in re.findall(r'<use href="#(i-[a-z-]+)"/>', nav):
        assert f'id="{icon}"' in html, f"{icon} is not in the sprite"


# --- the menu footer ------------------------------------------------


def test_the_footer_reads_status_then_preset_then_settings() -> None:
    """The order somebody asks: connected, which mesh, then everything else.

    The theme control used to be the third row; it moved to the settings
    page on 2026-09-26 and the footer holds a link in its place. One
    control per value -- a cycle button here AND a chooser on the page
    would be two ways to set one thing.
    """
    html = _html()
    menu = html[html.index('<div class="site-menu"') : html.index("</aside>")]
    assert menu.index("site-nav") < menu.index("menu-foot"), "the nav is below the footer"
    status = menu.index("data-status-text")
    preset = menu.index("data-preset-switch")
    # `menu-settings-link` rather than `href="#settings"`. It is now the
    # only link with that href, so either would match -- but matching the
    # class is what keeps this case honest if a second one is ever added
    # above the status line, which is the arrangement the href match
    # silently accepted before the nav entry was removed.
    settings = menu.index("menu-settings-link")
    assert status < preset < settings, f"status={status}, preset={preset}, settings={settings}"
    assert "data-theme-choice" not in menu, (
        "the theme cycle button is back in the menu, so there are two controls for one value"
    )


def test_there_is_exactly_one_route_to_the_settings_page() -> None:
    """Will: "there is a duplicate settings button on the bottom".

    There were two: an entry at the end of the nav list and the link in
    the menu footer, both `href="#settings"`, both visible at once on a
    desktop. Counted against the rendered markup with comments stripped,
    because the comments around both of them say `#settings` while
    explaining which one went.
    """
    html = re.sub(r"<!--.*?-->", "", _html(), flags=re.S)
    routes = re.findall(r'href="#settings"', html)
    assert len(routes) == 1, f"{len(routes)} links point at #settings; there should be one"
    # And it is the footer one, not a nav entry that survived by itself.
    nav = html[html.index('<nav id="site-nav"') : html.index("</nav>")]
    assert "#settings" not in nav, "the nav list has a Settings entry again"


def test_the_one_route_is_marked_current_like_a_nav_entry() -> None:
    """The half of the removal that was invisible.

    Two things in app.js work off `data-nav`, and neither of them knows
    the footer link exists otherwise: `route()` sets `.current` and
    `aria-current="page"` on `[data-nav]`, and `markNavHere` looks up
    `[data-nav="<page>"]` to tell the closed menu button which page you
    are on. Delete the nav entry without moving the attribute and a
    reader on the settings page has nothing marked as current and a menu
    button that names no page -- with nothing thrown and nothing logged.
    """
    html = _html()
    start = html.index('class="menu-settings-link"')
    link = html[start : html.index("</a>", start)]
    assert 'data-nav="settings"' in link, (
        "the only settings link carries no data-nav, so the router cannot mark it current "
        "and the menu button cannot name the page"
    )
    code = _code("app.js")
    assert "for (const link of $$('[data-nav]'))" in code, (
        "the router no longer marks [data-nav] links, so the attribute above does nothing"
    )
    assert "markNavHere" in code and '$(`[data-nav="${known}"]`)' in code, (
        "markNavHere no longer reads the attribute the footer link carries"
    )
    # A link outside `<nav>` gets none of `.sidebar nav a.current`, so it
    # needs its own rule or "current" is a class that styles nothing.
    css = (STATIC / "app.css").read_text(encoding="utf-8")
    assert ".menu-settings-link.current {" in css, (
        "the current page is not shown on the only link that can show it"
    )
    assert not re.search(r"^#site-nav \.nav-settings", css, re.M), (
        "the removed nav entry's styling is still here, which is how it comes back"
    )


def test_the_menu_closes_on_any_link_in_it_not_just_a_nav_entry() -> None:
    """Measured at 320 px: aria-expanded stayed "true" on the footer link.

    The close handler was bound to `#site-nav`, which covered every route
    out of the menu for as long as every route was a nav entry. Settings
    is a footer link now, so tapping it routed to the page and left the
    menu open on top of it -- the reader was looking at the list they had
    just chosen from, with the page a full screen below.
    """
    code = _code("app.js")
    body = code[code.index("function wireNav()") :]
    body = body[: body.index("\nfunction ")]
    assert "menu.addEventListener('click'" in body, (
        "the menu does not close on a link in its footer"
    )
    assert "nav.addEventListener('click'" not in body, (
        "the close handler is still on the nav alone, so a footer link leaves the menu open"
    )


def test_the_menu_footer_controls_are_readable() -> None:
    """Will: "It's hard to read the dark on dark".

    The theme button was `color: var(--muted)` on `background: none`, so a
    grey word sat on the dark sidebar at roughly 3:1 -- under the 4.5:1
    body text needs. That button is gone; the claim now belongs to the
    link that replaced it, and to the settings options themselves.
    """
    css = re.sub(r"/\*.*?\*/", "", (STATIC / "app.css").read_text(encoding="utf-8"), flags=re.S)
    link = css[css.index(".menu-settings-link {") :]
    link = link[: link.index("}")]
    assert "color: var(--text)" in link, f"the settings link is not body colour: {link!r}"
    assert "background: var(--panel-2)" in link, "the link has no surface to sit on"
    # And the chosen option on the page: white on the accent, because body
    # colour on the orange is the same problem one control along.
    option = css[css.index(".settings-option.active {") :]
    option = option[: option.index("}")]
    assert "color: #fff" in option, "the chosen option is not readable against the accent"


def test_the_settings_link_draws_an_icon_and_not_a_billboard() -> None:
    """Measured in Chromium: 18.39 px square, the same as a nav entry.

    An icon here is an inline `<svg><use>` from the sprite, which has no
    intrinsic size. `.menu-settings-link .icon` set `color` and nothing
    else, so the browser used the replaced-element default of 300x150 and
    drew a gear four rows high -- in black, because `color` paints an SVG
    only when something sets `fill: currentColor`.

    It went unseen because `.sidebar nav a .icon` sized the duplicate nav
    entry beside it, and that is the entry Will asked to be removed. So
    this is the same shape as every other case in this file: what was
    keeping a thing upright was the thing that got deleted.
    """
    css = re.sub(r"/\*.*?\*/", "", (STATIC / "app.css").read_text(encoding="utf-8"), flags=re.S)
    rule = css[css.index(".menu-settings-link .icon {") :]
    rule = rule[: rule.index("}")]
    assert "width" in rule and "height" in rule, (
        f"the gear has no size, so it renders at the SVG default of 300x150: {rule!r}"
    )
    assert "fill: currentColor" in rule, "the gear is not painted, so it draws black on the sidebar"


def test_the_controls_can_be_reached_by_keyboard() -> None:
    """A focus ring is not decoration on a control this small."""
    css = (STATIC / "app.css").read_text(encoding="utf-8")
    for selector in (
        ".preset-choice:focus-visible",
        ".menu-settings-link:focus-visible",
        ".settings-option:focus-visible",
    ):
        assert selector in css, f"{selector} has no focus style"


def test_the_preset_switch_is_a_radio_group() -> None:
    """Two one-word options. A select would cost a tap to open first."""
    html = _html()
    holder = html[html.index("data-preset-switch") - 200 : html.index("data-preset-switch") + 80]
    assert 'role="radiogroup"' in holder, holder
    code = _code("app.js")
    body = code[code.index("function wirePresetSwitch") :]
    body = body[: body.index("\nfunction ")]
    assert "role: 'radio'" in body, "the options are not radios"
    assert "aria-checked" in body, "nothing says which option is chosen"
    # Arrow keys move within a radio group; a row of buttons each taking
    # a tab stop is the usual way this control is got wrong.
    assert "ArrowRight" in body and "tabindex" in body, "arrow keys do not move between options"


# --- one preset for the whole site ----------------------------------


@pytest.mark.parametrize(
    "gone",
    [
        "data-coverage-preset",
        "data-gaps-preset",
        "data-gaps-preset-wrap",
        "data-link-channel",
        "data-link-channel-wrap",
    ],
)
def test_the_per_page_pickers_are_gone_from_the_markup(gone: str) -> None:
    assert gone not in _html(), f"{gone} is still in the page"


@pytest.mark.parametrize("name", ["app.js", "gaps.js", "coverage.js"])
def test_no_javascript_still_reaches_for_a_removed_picker(name: str) -> None:
    """A handler whose element is missing fails silently.

    Worse here than usual: `$('[data-link-channel]').addEventListener` on
    a missing element throws, and it sat in the middle of the startup
    wiring, so everything after it would have stopped being wired at all.
    """
    code = _code(name)
    for gone in ("data-coverage-preset", "data-gaps-preset", "data-link-channel"):
        assert gone not in code, f"{name} still reaches for {gone}"


def test_the_leaderboards_no_longer_build_their_own_picker() -> None:
    """The one that was easiest to miss.

    It was a `<select>` built in JavaScript inside the boards' note, not
    an element in the markup, so searching index.html would not have
    found it.
    """
    code = _code("app.js")
    body = code[code.index("data-leaderboards-note") :]
    body = body[: body.index("replace(target,")]
    assert "onchange" not in body, "the leaderboards still offer their own preset choice"
    assert "SonoranPreset" in body, "the leaderboards do not follow the global preset"


def test_the_shared_helper_consults_the_readers_choice_first() -> None:
    """How the graph and coverage started obeying the menu for free.

    `preferredPreset` is called by the graph's tab strip and by
    coverage.js. Consulting the store inside it means those callers follow
    the menu without being rewritten -- so this is the assertion that
    keeps them following it.
    """
    code = _code("labels.js")
    body = code[code.index("function preferredPreset") :]
    body = body[: body.index("\n  }")]
    assert "SonoranPreset" in body, "the helper ignores the reader's choice"
    # And still falls back, so a document without the store behaves as
    # this function did before the menu existed.
    assert "defaultPreset" in body, "the server default is no longer the fallback"


def test_the_store_loads_before_the_helper_that_reads_it() -> None:
    """Plain scripts, so this is load order and not import order."""
    html = _html()
    assert html.index('src="static/preset.js') < html.index('src="static/labels.js'), (
        "preset.js loads after labels.js, so the helper would see no store"
    )


def test_the_store_cases_pass_under_node() -> None:
    """The rules themselves, exercised rather than read."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    done = subprocess.run([node, str(CASES)], capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stdout + done.stderr


# --- the copy -------------------------------------------------------


def test_no_page_still_promises_a_picker_it_does_not_have() -> None:
    """Copy is part of the change: a page that says "one modem preset at
    a time" beside no control leaves the reader hunting for it."""
    html = _html()
    assert "One modem preset at a time" not in html, (
        "the gaps page still describes a per-page preset choice"
    )


def test_the_chat_subtitle_says_the_same_thing_in_both_places() -> None:
    """It is written in the markup AND set again from JavaScript.

    Two copies of one sentence drift. They are checked together because
    the JS one overwrites the markup one the moment the page renders, so a
    reader would only ever see the stale one for an instant -- which is
    the hardest kind of mismatch to notice.
    """
    phrase = "on the preset chosen in the menu"
    assert phrase in _html(), "the markup subtitle was not updated"
    assert phrase in (STATIC / "app.js").read_text(encoding="utf-8"), (
        "the JavaScript subtitle was not updated"
    )


# --- the planner is the deliberate exception ------------------------


def test_the_planner_opens_on_the_global_preset() -> None:
    """Will's call: default from the menu, still editable.

    The planner is the one page where a preset is not a view of what
    happened -- it is an input to a prediction and sets the receiver
    sensitivity the model uses. So it keeps its own box, and merely opens
    on whatever the menu says.
    """
    code = _code("planner.js")
    body = code[code.index("const defaults = {") :]
    body = body[: body.index("fillForm(defaults);")]
    assert "SonoranPreset.current()" in body, "the planner ignores the menu"
    assert "defaults.sensitivity" in body, (
        "the sensitivity does not move with the preset, so the form would open on "
        "one preset with another's sensitivity and predict a reach nobody has"
    )


def test_the_planner_still_has_its_own_control() -> None:
    """Editable is the other half of the decision.

    Modelling a LongFast repeater while browsing MediumFast is a real
    thing to want, so the box stays.
    """
    assert 'data-planner="preset"' in _html(), "the planner lost its preset control"


def test_a_shared_plan_link_still_decides_its_own_preset() -> None:
    """This matters more than the default.

    A shared plan predicts what it said it would. `applyShare` does its
    own fill and returns early when the address carries no query, so the
    global default cannot reach into a link.
    """
    code = _code("planner.js")
    share = code[code.index("const read = SonoranPlannerParams.fromShareQuery(search);") :]
    share = share[: share.index("const said = [];")]
    assert "filled.preset" in share, "a shared link no longer sets its own preset"
    assert "SonoranPreset" not in share, (
        "the global preset reaches into the share path, so a shared plan would "
        "predict something other than what was shared"
    )


# --- the three pages that were missing it ---------------------------
#
# Will asked "is the firehose getting filtered... did we miss anything?".
# Three were: the firehose, the dashboard's message feed and the node
# list. All three endpoints already took `channel` and none of the pages
# sent one. Verified against the live instance before wiring them, because
# a parameter existing is not proof that it filters:
#
#   api/packets  unfiltered -> both presets; channel=LongFast -> LongFast
#   api/chat     unfiltered -> MediumFast, Traffic, Weather; filtered -> LongFast
#   api/nodes    2,557 nodes total; 836 on LongFast, 1,276 on MediumFast
#
# The node count is why that page is the one to watch: filtering HIDES
# nodes, and it is where somebody goes to find a specific one.


def test_one_helper_decides_the_preset_for_all_three() -> None:
    """Three call sites, one rule, so they cannot drift apart."""
    code = _code("app.js")
    assert "function presetChannel()" in code
    assert code.count("presetChannel()") >= 3, (
        "not every page that gained the filter is using the shared helper"
    )


def test_the_firehose_asks_for_one_preset() -> None:
    code = _code("app.js")
    body = code[code.index("limit: '150', summary: 'true'") :]
    body = body[: body.index("api/packets?")]
    assert "params.set('channel'" in body, "the firehose still shows every preset"


def test_the_dashboard_feed_asks_for_one_preset() -> None:
    code = _code("app.js")
    assert "chatFeedChannel()" in code, "the dashboard feed still mixes presets"


def test_the_node_list_asks_for_one_preset() -> None:
    code = _code("app.js")
    body = code[code.index("function nodeQuery(") :]
    body = body[: body.index("api/nodes?")]
    assert "presetChannel()" in body, "the node list still shows every preset"


def test_a_filter_chosen_in_the_panel_still_beats_the_menu() -> None:
    """The existing precedence rule, kept.

    The panel wins where both can say the same thing, because the panel is
    the one that SHOWS what it chose. So the menu's channel has to be set
    before the panel loop overwrites it -- set after, a reader picking a
    channel in the panel would watch it be ignored.
    """
    code = _code("app.js")
    body = code[code.index("function nodeQuery(") :]
    body = body[: body.index("api/nodes?")]
    assert body.index("presetChannel()") < body.index("for (const [key, chosen] of nodeFilters)"), (
        "the menu's preset is applied after the panel, so the panel no longer wins"
    )


def test_the_facet_counts_follow_the_same_filters_as_the_rows() -> None:
    """Counts that describe a larger set than the rows are a lie.

    `nodeFacetQuery` derives its query from `nodeQuery`, so the channel
    reaches both. Held because the two could easily be built separately.
    """
    code = _code("app.js")
    body = code[code.index("function nodeFacetQuery(") :]
    body = body[: body.index("api/nodes/facets?")]
    assert "nodeQuery(page)" in body, "the facet counts no longer follow the row filters"


def test_the_filtering_is_silent() -> None:
    """Will's choice: no per-page notice.

    The menu says which preset is selected. A line on each page repeating
    it is the wordiness he had just asked to be taken out of the nav --
    which is also why the preset hint is gone.
    """
    html = _html()
    assert "data-preset-hint" not in html, "the nav hint is back"
    assert "Radios on one preset cannot hear" not in re.sub(r"<!--.*?-->", "", html, flags=re.S), (
        "the sentence Will disliked is still rendered"
    )


def test_the_graph_has_no_channel_tabs_of_its_own() -> None:
    """Will: "Graph page probably needs the filter as well."

    It did. The graph defaulted to the menu's preset through
    `preferredPreset`, which is why it looked done -- but it also drew a
    clickable tab per channel, INCLUDING the topic ones, so a reader could
    end up on a Weather graph while every other page showed MediumFast.

    Removed rather than left empty: a `role="tablist"` holding no tabs is a
    promise to a screen reader that there is something to choose.
    """
    html = _html()
    bare = re.sub(r"<!--.*?-->", "", html, flags=re.S)
    assert "data-graph-tabs" not in bare, "the graph still has a channel tab strip"
    code = _code("app.js")
    body = code[code.index("function graphTabs(") :]
    body = body[: body.index("\n}")]
    assert "role: 'tab'" not in body, "the graph still builds clickable channel tabs"
    assert "SonoranLabels.preferredPreset" in body, "the graph no longer follows the menu"


def test_the_graph_still_falls_back_rather_than_drawing_nothing() -> None:
    """An empty graph is worse than the wrong one (#177).

    `preferredPreset` takes the menu's choice where that channel HAS link
    reports and otherwise falls back to the first that does, so a reader
    whose preset is quiet in the window still sees a mesh. The filter on
    `link_report_count` is the other half: the channel list carries
    channels with traffic but no links, and those would open empty.
    """
    code = _code("app.js")
    body = code[code.index("function graphTabs(") :]
    body = body[: body.index("\n}")]
    assert "link_report_count > 0" in body, (
        "channels with no links are back, and they open an empty graph"
    )


def test_the_dead_tab_styling_went_with_the_tabs() -> None:
    """Dead CSS that still looks live is how the next person keeps it.

    `.watch-tabs` on the live map is a different class and keeps its own
    rules; nothing else used `.tabs`.
    """
    css = (STATIC / "app.css").read_text(encoding="utf-8")
    assert not re.search(r"^\.tabs[ {]", css, re.M), ".tabs rules are still here"
    assert ".watch-tabs" in css, "the live map's tab styling was removed by mistake"


# --- the dense page head (§6.4) -------------------------------------


def test_the_map_and_graph_heads_are_dense() -> None:
    """Will: the title, subtitle and controls on one row, to save height.

    `.page-head` was already a flex row that wraps; on those two pages the
    controls overflow it because the title block is two stacked lines. The
    variant makes that block one line so the row has room.
    """
    html = re.sub(r"<!--.*?-->", "", _html(), flags=re.S)
    for page in ("map", "graph"):
        start = html.index(f'data-page="{page}"')
        head = html[start : html.index("</div>", html.index("page-head", start))]
        assert "page-head dense" in head, f"the {page} head is not dense"


def test_the_dense_head_still_wraps_on_a_phone() -> None:
    """One row at 320 px would overflow the document sideways.

    The e2e forbids that, and so does WCAG 2.2 SC 1.4.10 Reflow. So the
    wrap stays and what changes by width is how much of the title block is
    shown -- the subtitle is dropped under about a tablet rather than
    shrinking to a fragment plus an ellipsis.
    """
    css = re.sub(r"/\*.*?\*/", "", (STATIC / "app.css").read_text(encoding="utf-8"), flags=re.S)
    rule = css[css.index(".page-head.dense {") :]
    rule = rule[: rule.index("}")]
    assert "flex-wrap: wrap" in rule, "the dense head cannot wrap, so it will overflow at 320px"
    assert ".page-head.dense .sub { display: none" in css, (
        "the subtitle is not dropped at narrow widths"
    )


def test_the_heading_outranks_the_subtitle_when_the_row_is_tight() -> None:
    """A clipped heading is worse than no subtitle."""
    css = re.sub(r"/\*.*?\*/", "", (STATIC / "app.css").read_text(encoding="utf-8"), flags=re.S)
    heading = css[css.index(".page-head.dense h2 {") :]
    heading = heading[: heading.index("}")]
    assert "white-space: nowrap" in heading, "the heading can wrap before the subtitle gives way"


def test_the_preset_switch_slides() -> None:
    """The thumb is one element behind both labels (§3.5).

    A fill on the chosen label tells the reader the state changed; a thumb
    that travels tells them which way it went. That is the whole reason
    this is a sliding switch and not a segmented one.

    Measured in a browser after the change: a 207 px track, a 99.3 px
    thumb, and its centre landing on 54 px then 153 px against active
    labels centred on 54 px and 153 px.
    """
    css = re.sub(r"/\*.*?\*/", "", (STATIC / "app.css").read_text(encoding="utf-8"), flags=re.S)
    track = css[css.index(".preset-switch {") :]
    track = track[: track.index("}")]
    assert "position: relative" in track, (
        "the track is not a containing block, so an absolutely positioned thumb "
        "would be placed against the page instead of the switch"
    )
    # Load-bearing: the thumb moves by exactly its own width, so a gap
    # between labels makes it drift further off with each position.
    assert "gap:" not in track, (
        f"the track has a gap again; the thumb steps by its own width and will "
        f"not line up with the later positions: {track!r}"
    )

    thumb = css[css.index(".preset-switch::before {") :]
    thumb = thumb[: thumb.index("}")]
    assert "position: absolute" in thumb, "the thumb is not positioned"
    assert "var(--preset-count" in thumb, (
        "the thumb's width does not read the option count, so it is only right "
        "for whichever number of presets was hardcoded"
    )
    assert "var(--preset-index" in thumb, "the thumb does not move with the choice"
    assert "transform" in thumb, "the thumb is placed, not moved, so it cannot slide"


def test_the_slide_can_be_turned_off() -> None:
    """WCAG 2.3.3: somebody who asked for less movement gets the state."""
    css = (STATIC / "app.css").read_text(encoding="utf-8")
    block = re.search(
        r"@media \(prefers-reduced-motion: reduce\) \{[^}]*\.preset-switch::before[^}]*\}",
        css,
        re.S,
    )
    assert block, "the thumb animates regardless of prefers-reduced-motion"
    assert "transition: none" in block.group(0), (
        f"reduced motion does not stop the transition: {block.group(0)!r}"
    )


def test_the_switch_publishes_what_the_css_cannot_work_out() -> None:
    """CSS cannot count children or ask which one is active.

    Both custom properties have to be set by `wirePresetSwitch`, and the
    index has to be clamped: `indexOf` answers -1 for a preset no longer on
    offer, and -1 parks the thumb a whole position off the left of the
    track -- visible, wrong, and pointing at nothing.
    """
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    start = app.index("function wirePresetSwitch()")
    body = app[start : start + 3000]
    assert "--preset-count" in body, "the option count is never published"
    assert "--preset-index" in body, "the chosen index is never published"
    assert "Math.max(0," in body, (
        "the index is not clamped, so a preset that is no longer offered "
        "(indexOf -> -1) puts the thumb outside the track"
    )
    assert "Math.max(1," in body, (
        "the count is not floored at 1, so an empty option list divides by zero"
    )
