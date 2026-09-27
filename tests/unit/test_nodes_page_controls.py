"""The nodes page controls (§6.2).

Four of Will's items, and one question he asked rather than stated.

* the filter chips move inside the Filters panel as "Filter presets";
* the Filters button carries how many are in force;
* the line above the table stops saying how it is sorted and how many
  filters are on;
* the Search button goes -- "What is the point of the search button if
  it's automatically sorting, filtering and searching?"

That last one had a catch worth keeping: the button was also the Enter
affordance. Enter in the search box is wired separately and must keep
working, or removing the button reads as a regression.
"""

import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "src" / "sonoran" / "web" / "static"


def _html() -> str:
    return (STATIC / "index.html").read_text(encoding="utf-8")


def _app() -> str:
    text = re.sub(r"/\*.*?\*/", "", (STATIC / "app.js").read_text(encoding="utf-8"), flags=re.S)
    return "\n".join(
        line
        for line in text.splitlines()
        if (stripped := line.strip()) and not stripped.startswith("//")
    )


def _panel() -> str:
    html = re.sub(r"<!--.*?-->", "", _html(), flags=re.S)
    start = html.index("data-node-filters")
    return html[start : html.index("</div>", html.index("filter-actions", start))]


def test_the_comment_stripper_works() -> None:
    assert "function describeNodeList" in _app(), "the stripper removed real code"
    assert "Will asked" not in _app(), "comments are leaking through"


def test_the_filter_presets_live_inside_the_panel() -> None:
    """They cost a line of vertical space on every visit, for controls
    most readers use once."""
    panel = _panel()
    for name in ("silent-routers", "no-position", "gateways", "newest", "clear"):
        assert f'data-node-start="{name}"' in panel, f"the {name} preset is not in the panel"
    assert "Filter presets" in panel, "the group is not named as Will asked"


def test_the_presets_are_not_also_left_above_the_table() -> None:
    """Two copies of one control is worse than either place."""
    html = re.sub(r"<!--.*?-->", "", _html(), flags=re.S)
    assert html.count('data-node-start="gateways"') == 1, "the presets are in two places"


def test_the_filters_button_says_how_many_are_in_force() -> None:
    """A control that says what it is holding beats a sentence beside it."""
    assert "data-node-filter-count" in _html(), "the button has no count"
    app = _app()
    body = app[app.index("function describeNodeList") :]
    body = body[: body.index("\n}")]
    assert "data-node-filter-count" in body, "nothing fills the count"
    # A superscript number is invisible to a screen reader, so the name
    # has to carry it too.
    assert "aria-label" in body, "the count is not in the accessible name"
    assert "has-filters" in body, "the button does not show it is holding something"


def test_the_count_is_never_colour_alone() -> None:
    """The number is the second signal, which is why the class is safe."""
    css = (STATIC / "app.css").read_text(encoding="utf-8")
    assert ".filter-count {" in css
    assert ".toggle.has-filters" in css


def test_the_line_above_the_table_keeps_only_what_is_unsaid_elsewhere() -> None:
    """The heading carries the sort; the button carries the filters.

    What stays is the only thing no control could say: how many nodes
    there are and how many are on screen.
    """
    app = _app()
    body = app[app.index("function describeNodeList") :]
    body = body[: body.index("\n}")]
    assert "sorted by" not in body, "the line still names the sort"
    assert "filter${filters" not in body, "the line still counts the filters"
    assert "nodes shown" in body or "nodes`" in body, "the line no longer says how many nodes"


def test_the_sort_is_still_visible_somewhere() -> None:
    """Removing the sentence is only safe because the heading says it.

    `aria-sort` on the heading, bold text, and an orange arrow -- three
    signals, none of them the removed sentence.
    """
    app = _app()
    assert "'aria-sort'" in app, "nothing announces the sort"
    css = (STATIC / "app.css").read_text(encoding="utf-8")
    assert "th.sorted" in css, "the sorted column is not marked"


def test_the_search_button_is_gone() -> None:
    assert "data-node-apply" not in _html(), "the Search button is back"
    assert "data-node-apply" not in _app(), (
        "a handler still reaches for the Search button, which would throw"
    )


def test_enter_still_runs_the_search() -> None:
    """The button was the Enter affordance as well as a button.

    Without this, removing it would look like the search stopped working
    for anybody who types and presses Enter.
    """
    app = _app()
    body = app[app.index("data-node-search") :]
    body = body[: body.index("data-graph-search")]
    assert "'keydown'" in body, "Enter is no longer handled in the search box"
    assert "Enter" in body
    assert "NODE_SEARCH_PAUSE_MS" in app, "the box no longer debounces, so it fires per keystroke"


# --- what the badge counts (#301) --------------------------------------

CASES = ROOT / "tests" / "unit" / "js" / "nodes_filter_count_cases.mjs"


def _run_cases(app_text: str | None = None) -> subprocess.CompletedProcess[str]:
    node = shutil.which("node")
    assert node, "node is not on PATH, so the badge count went unchecked"
    app = STATIC / "app.js"
    original = app.read_text(encoding="utf-8")
    if app_text is not None:
        app.write_text(app_text, encoding="utf-8")
    try:
        return subprocess.run(
            [node, str(CASES)], capture_output=True, text=True, timeout=60, cwd=ROOT
        )
    finally:
        app.write_text(original, encoding="utf-8")


def test_the_badge_counts_only_what_the_reader_changed() -> None:
    """Will (2026-09-27): a first visit shows no badge. The toolbar counts
    when it differs from its default, and the preset never counts."""
    done = _run_cases()
    assert done.returncode == 0, done.stdout + done.stderr
    body = _app()[_app().index("function describeNodeList") :]
    assert "nodeFilterCount(toolbar, defaults, nodeFilters)" in body[: body.index("\n}")]


def test_a_count_of_the_whole_query_would_be_caught() -> None:
    """The control: count every toolbar value, default or not, which is
    the old behaviour, and the cases must fail."""
    source = (STATIC / "app.js").read_text(encoding="utf-8")
    broken = source.replace("if (value !== defaults[key]) changed.add(key);", "changed.add(key);")
    assert broken != source, "the default test has moved; this control checks nothing"
    done = _run_cases(broken)
    assert done.returncode != 0, "the cases pass when the defaults are counted"
    assert "first visit" in done.stderr, done.stderr
