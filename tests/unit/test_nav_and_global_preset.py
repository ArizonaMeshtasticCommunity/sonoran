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


def test_the_footer_reads_status_then_preset_then_theme() -> None:
    """The order somebody asks: connected, which mesh, then too bright."""
    html = _html()
    menu = html[html.index('<div class="site-menu"') : html.index("</aside>")]
    assert menu.index("site-nav") < menu.index("menu-foot"), "the nav is below the footer"
    status = menu.index("data-status-text")
    preset = menu.index("data-preset-switch")
    theme = menu.index("data-theme-choice")
    assert status < preset < theme, f"status={status}, preset={preset}, theme={theme}"


def test_the_theme_control_is_readable() -> None:
    """Will: "It's hard to read the dark on dark".

    It was `color: var(--muted)` on `background: none`, so a grey word sat
    on the dark sidebar at roughly 3:1 -- under the 4.5:1 body text needs.
    """
    css = re.sub(r"/\*.*?\*/", "", (STATIC / "app.css").read_text(encoding="utf-8"), flags=re.S)
    rule = css[css.index(".menu-foot .theme-switch {") :]
    rule = rule[: rule.index("}")]
    assert "color: var(--text)" in rule, f"still not body colour: {rule!r}"
    assert "background: var(--panel-2)" in rule, "the control has no surface to sit on"


def test_the_controls_can_be_reached_by_keyboard() -> None:
    """A focus ring is not decoration on a control this small."""
    css = (STATIC / "app.css").read_text(encoding="utf-8")
    for selector in (".preset-choice:focus-visible", ".menu-foot .theme-switch:focus-visible"):
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
