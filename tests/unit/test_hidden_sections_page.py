"""The page side of HIDDEN_SECTIONS.

The server tells the page what is hidden (`test_hidden_sections.py`).
These cases hold what the page does with the list:

- The list of sections is one list. The menu's `data-nav` ids, apart
  from the two pages that cannot be hidden, are exactly the page
  sections in `api/sections.py`. A page added to the menu must be added
  there too, or an operator could not hide it.
- `sections.js` runs before the phone bar is built, so a hidden page is
  never copied into the bar or the More menu.
- A hidden page's address lands on a page that says, in plain words,
  "This part of Sonoran isn't available yet", with a link home.
- What the dashboard and the Statistics page show of a hidden part is
  marked, and their requests for it are not made.

`tests/unit/js/hidden_sections_cases.mjs` runs the script's rules, and
`tools/dev/e2e.js` (with `SONORAN_HIDDEN_SECTIONS`) walks it in a browser.
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from sonoran.api import sections

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "src" / "sonoran" / "web" / "static"
HTML = (STATIC / "index.html").read_text(encoding="utf-8")
VISIBLE = re.sub(r"<!--.*?-->", "", HTML, flags=re.S)
APP = (STATIC / "app.js").read_text(encoding="utf-8")
CASES = ROOT / "tests" / "unit" / "js" / "hidden_sections_cases.mjs"


def _nav_ids() -> list[str]:
    start = VISIBLE.index('<nav id="site-nav"')
    nav = VISIBLE[start : VISIBLE.index("</nav>", start)]
    return re.findall(r'data-nav="([a-z]+)"', nav)


def _script_index(name: str) -> int:
    return VISIBLE.index(f'src="static/{name}?v=')


def _page(name: str) -> str:
    start = VISIBLE.index(f'<section class="page" data-page="{name}">')
    return VISIBLE[start : VISIBLE.index("</section>", start)]


def _function(source: str, head: str) -> str:
    start = source.index(head)
    end = source.find("\n};\n", start)
    end2 = source.find("\n}\n", start)
    ends = [index for index in (end, end2) if index != -1]
    return source[start : min(ends)]


def test_the_menu_and_the_sections_are_one_list() -> None:
    pages = {name for name, section in sections.SECTIONS.items() if section.parent is None}
    menu = set(_nav_ids()) - set(sections.NOT_HIDDEN)
    assert menu == pages


def test_every_part_names_a_real_page() -> None:
    for name, section in sections.SECTIONS.items():
        if section.parent is not None:
            assert section.parent in sections.SECTIONS, name


def test_the_script_runs_before_the_bar_is_built() -> None:
    assert _script_index("sections.js") < _script_index("tab-bar.js")
    assert _script_index("sections.js") < _script_index("app.js")
    # After the config it reads.
    assert VISIBLE.index("window.SONORAN = __SONORAN_CONFIG__") < _script_index("sections.js")


def test_a_hidden_page_has_a_page_that_says_so() -> None:
    page = _page("unavailable")
    assert "This part of Sonoran isn't available yet" in page
    assert re.search(r'<a [^>]*href="#dashboard"', page), "the page has no link home"


def test_the_router_sends_a_hidden_page_there() -> None:
    route = _function(APP, "async function route() {")
    assert "SonoranSections.pageFor(" in route
    assert "PAGES.unavailable = " in APP


def test_the_dashboard_messages_go_with_chat() -> None:
    dashboard = _page("dashboard")
    card = dashboard[: dashboard.index("data-recent-chat>")]
    card = card[card.rindex('<div class="panel"') :]
    assert 'data-section="chat"' in card
    body = _function(APP, "PAGES.dashboard = async (page) => {")
    assert re.search(r"SonoranSections\.isHidden\('chat'\)\s*\?\s*null", body), (
        "the dashboard still asks for messages when chat is hidden"
    )


def test_the_packet_chart_does_not_open_a_hidden_firehose() -> None:
    body = _function(APP, "PAGES.dashboard = async (page) => {")
    assert "SonoranSections.isHidden('firehose')" in body


def test_the_leaderboards_are_marked_and_not_fetched() -> None:
    stats = VISIBLE[VISIBLE.index('<section class="page" data-page="stats">') :]
    assert re.search(r'<div class="leaderboards-wrap" data-section="leaderboards">', stats)
    loader = _function(APP, "async function loadLeaderboards(")
    assert "SonoranSections.isHidden('leaderboards')" in loader


def test_the_statistics_sentence_has_no_hidden_leaderboards() -> None:
    head = _page("stats")[:2000]
    assert re.search(r'<span data-section="leaderboards">[^<]*leaderboards', head)
    assert re.search(r'<span data-section-absent="leaderboards" hidden>', head)


def test_the_cases_pass_under_node() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    result = subprocess.run([node, str(CASES)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
