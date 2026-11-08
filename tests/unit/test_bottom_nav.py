"""A bottom navigation bar on phones (#282).

Will chose the set on 2026-10-08 (option A): Map, Nodes, Chat and
Dashboard, then More, which opens the menu that already exists.

The review measured why (`docs/design/2026-09-27-mobile-review.md`
section 2.5 and item 17): every page link was behind one button at the
top of the screen. The compact sticky bar (#271) keeps that button on
the screen, but it is still at the top, and hidden navigation is used
less than visible navigation (NN/g: 89 percent of sessions against 44
to 56).

What these cases hold:

- There is one list of pages. The bar's four links are copied from
  `#site-nav` when the page starts, so a renamed page or a new icon
  reaches both. The markup holds the names of the four and nothing else.
- The trigger is a phone: narrow AND a finger. The CSS and the script
  ask the same question in the same words.
- Nothing sits under the bar: the page, the open menu, the chat column,
  the node sheet, the app notices, and the focus all keep clear of it.
- The bar uses the bottom safe area, for the home indicator.

`tests/unit/js/tab_bar_cases.mjs` runs the script itself for the
"closest tab" rule. `tools/dev/e2e.js` measures the bar in a browser.
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "src" / "sonoran" / "web" / "static"
HTML = (STATIC / "index.html").read_text(encoding="utf-8")
CSS = (STATIC / "app.css").read_text(encoding="utf-8")
APP = (STATIC / "app.js").read_text(encoding="utf-8")
CASES = ROOT / "tests" / "unit" / "js" / "tab_bar_cases.mjs"

QUERY = "(max-width: 40rem) and (orientation: portrait) and (pointer: coarse)"


def _tab_bar_js() -> str:
    return (STATIC / "tab-bar.js").read_text(encoding="utf-8")


def _markup() -> str:
    """The bar's markup, comments removed."""
    html = re.sub(r"<!--.*?-->", "", HTML, flags=re.S)
    start = html.index("data-tab-bar")
    start = html.rindex("<nav", 0, start)
    return html[start : html.index("</nav>", start)]


def _block() -> str:
    """The CSS block that draws the bar on a phone."""
    start = CSS.index(f"@media {QUERY} {{")
    return CSS[start : CSS.index("\n}\n", start)]


def test_the_bar_is_a_named_nav_hidden_until_the_script_builds_it() -> None:
    bar = _markup()
    opening = bar[: bar.index(">")]
    assert 'aria-label="' in opening, "the bar is a nav with no name, beside one that has a name"
    assert "hidden" in opening, (
        "the bar is visible before the script builds it, so a browser "
        "without the script shows a More button that cannot open anything"
    )


def test_the_four_pages_are_the_ones_will_chose() -> None:
    """Will, 2026-10-08, option A. In his order."""
    match = re.search(r'data-tabs="([^"]+)"', _markup())
    assert match, "the bar does not say which pages it holds"
    assert match.group(1).split() == ["map", "nodes", "chat", "dashboard"]


def test_every_tab_is_a_page_in_the_one_list() -> None:
    """A tab is copied from `#site-nav`. A name that is not there is a hole."""
    nav = HTML[HTML.index('<nav id="site-nav"') : HTML.index("</nav>")]
    names = re.search(r'data-tabs="([^"]+)"', _markup()).group(1).split()
    for name in names:
        assert f'data-nav="{name}"' in nav, f"{name} is not in the page list"


def test_the_bar_writes_no_page_link_of_its_own() -> None:
    """A second hand-kept list is the drift this project keeps paying for."""
    bar = _markup()
    assert "<a " not in bar, "the bar has page links in the markup; it must copy them"
    assert 'href="#i-more"' in bar, "the More icon is gone, so this case reads nothing"
    assert "data-nav=" not in bar, (
        "a bar entry carries data-nav, so the router and markNavHere would "
        "treat it as a second menu entry"
    )


def test_more_opens_the_existing_menu() -> None:
    bar = _markup()
    start = bar.index("data-tab-more")
    button = bar[bar.rindex("<button", 0, start) : bar.index("</button>", start)]
    assert 'type="button"' in button
    assert 'aria-controls="site-menu"' in button, "More does not open the one menu"
    assert 'aria-expanded="false"' in button
    assert ">More<" in button, "More has no visible word"


def test_the_css_and_the_script_ask_the_same_question() -> None:
    assert f"@media {QUERY} {{" in CSS
    assert f"const QUERY = '{QUERY}';" in _tab_bar_js(), (
        "the script decides when the bar is on with different words from the CSS"
    )


def test_the_script_loads_before_the_router() -> None:
    """app.js runs `route()` as its last act, and the route marks the bar."""
    script = HTML.index('src="static/tab-bar.js')
    assert script < HTML.index('src="static/app.js'), "tab-bar.js loads after app.js"


def test_the_router_marks_the_bar() -> None:
    body = APP[APP.index("async function route()") :]
    body = body[: body.index("\n}\n")]
    assert "SonoranTabBar.mark(known)" in body, "the router does not mark the current tab"


def test_the_bar_takes_the_home_indicator() -> None:
    block = _block()
    assert "var(--safe-bottom)" in block, "the bar does not clear the home indicator"
    assert "--tabbar-h: calc(" in block


def test_nothing_sits_under_the_bar() -> None:
    block = _block()
    assert re.search(r"\.content \{[^}]*padding-bottom: calc\([^;]*var\(--tabbar-h\)", block), (
        "the page is not padded, so its last row sits under the bar"
    )
    assert "scroll-padding-bottom: var(--tabbar-h)" in block, (
        "a focused control can be scrolled to a place under the bar (WCAG 2.4.11)"
    )
    assert re.search(r"\.sidebar\[data-menu-open\] \{[^}]*100svh - var\(--tabbar-h\)", block), (
        "the open menu runs under the bar, so Settings can be under it"
    )
    assert re.search(r"chat-full \{[^}]*var\(--tabbar-h\)", block), (
        "the chat column is a screen tall and its newest message is under the bar"
    )


def test_the_other_bottom_layers_stand_on_the_bar() -> None:
    sheet = CSS[CSS.index(".node-sheet {") :]
    assert "bottom: var(--tabbar-h)" in sheet[: sheet.index("}")], "the node sheet is under the bar"
    notices = CSS[CSS.index(".app-notices {") :]
    assert "var(--tabbar-h)" in notices[: notices.index("}")], (
        "the offline notice sits on top of the bar"
    )


def test_the_bar_has_no_height_where_it_is_not_drawn() -> None:
    """The default is zero, ahead of the phone block, so a desktop is untouched."""
    default = CSS.index("--tabbar-h: 0px;")
    assert default < CSS.index(f"@media {QUERY} {{")


def test_watch_mode_has_no_bar() -> None:
    assert re.search(r"body\.watch-mode \.tab-bar \{[^}]*display: none", CSS)
    assert re.search(r"body\.watch-mode \{[^}]*--tabbar-h: 0px", CSS)


def test_the_tab_cases_pass_under_node() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    result = subprocess.run([node, str(CASES)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
