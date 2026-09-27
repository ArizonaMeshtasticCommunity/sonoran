"""The words the dashboard shows, and the panels that must not stay blank.

There is no JavaScript test runner in this project, so these tests pin the
things that fail quietly in a browser: a table that prints a protocol enum,
a second copy of a label table that drifts from the first, a chart drawn
inside a guard with no else, and a heading that names a number the page is
not holding.

Each one is here because it was found in a rendered screenshot, not in the
markup. See AGENTS.md 9.5.1 and 9.22.
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


def test_the_label_tables_load_before_every_file_that_reads_them() -> None:
    """labels.js must come first.

    app.js destructures `window.SonoranLabels` at the top level, so a later
    load throws before the router ever runs and the whole page is blank.
    gaps.js reads the same helpers inside its draw functions.
    """
    text = _client().get("/").text
    first = text.index("static/labels.js")
    for name in ("planner.js", "coverage.js", "gaps.js", "map-live.js", "app.js"):
        assert first < text.index(f"static/{name}"), name


def test_the_role_table_exists_once() -> None:
    """One table, in labels.js.

    app.js carried a role table that gaps.js could not reach, so gaps.js
    printed `CLIENT_BASE` on a page whose sibling printed "Client base".
    A second copy is how that happened, so a second copy is the thing to
    keep out.
    """
    labels = _read("labels.js")
    assert "{ key: 'CLIENT_MUTE', label: 'Client mute' }," in labels
    for name in ("app.js", "gaps.js", "coverage.js", "planner.js"):
        assert "label: 'Client mute'" not in _read(name), name


def test_the_port_number_table_exists_once() -> None:
    """`portnumLabel` and `familyLabel` were the same function, written twice.

    They also disagreed about nothing and agreed about everything, which is
    the state a duplicate is in right up to the edit that changes one.
    """
    # American, since #240. The point of this line is that the spelled
    # out port label lives in labels.js and nowhere else; the spelling
    # itself is pinned by test_neighbours_are_named.py.
    assert "'Neighbor info'" in _read("labels.js")
    app = _read("app.js")
    assert "familyLabel" not in app
    assert app.count("function portnumLabel") == 0


def test_no_table_column_prints_a_raw_role_or_port_number() -> None:
    """A cell shows the label; `title` keeps the wire value.

    `CLIENT_MUTE` was cut to `CLIENT_` in a narrow column, which is not a
    role and reads exactly like one. The fix is `roleCell` and
    `portnumCell`, and the way it regresses is a new column that calls
    neither.
    """
    for name in ("app.js", "gaps.js"):
        text = _read(name)
        assert "cell: (row) => row.role" not in text, name
        assert "cell: (row) => row.portnum" not in text, name


def test_the_gaps_table_uses_the_same_role_cell_as_the_nodes_table() -> None:
    assert "roleCell(row.role)" in _read("gaps.js")


def test_the_firehose_does_not_call_its_upload_count_a_gateway_count() -> None:
    """AGENTS.md 9.5.1: `seen_count` counts uploads, not gateways.

    One gateway uploads the same packet several times. The column has
    always shown `seen_count` and the heading said "Gateways", so the page
    named a number it was not holding. The number is unchanged.
    """
    app = _read("app.js")
    firehose = app[app.index("PAGES.firehose") : app.index("PAGES.traceroutes")]
    assert "label: 'Uploads'" in firehose
    assert "label: 'Gateways'" not in firehose
    assert "count(row.seen_count)" in firehose


def test_the_summary_tiles_do_not_call_uploads_observations() -> None:
    """The same word, on the tile and in the table."""
    app = _read("app.js")
    assert "statTile('Uploads', count(stats.observation_count)" in app
    assert "statTile('Observations'" not in app


def test_every_chart_says_why_it_is_blank() -> None:
    """A titled panel holding nothing reads as a measured zero.

    Four charts were drawn inside `if (rows && rows.length)` with no else.
    The daily activity chart is the plain case: the jobs service writes
    that table, so a dashboard whose jobs have never run showed an empty
    box where a month of history belongs.
    """
    app = _read("app.js")
    assert "function chartEmpty(" in app
    # The four targets that could answer with an empty list.
    for guard in (
        "chartEmpty(portnumChart",
        "chartEmpty(dailyChart",
        "chartEmpty(hardwareChart",
    ):
        assert guard in app, guard
    # And the activity chart, which draws into a local named `target`.
    activity = app[app.index("function drawActivityChart") :]
    assert "chartEmpty(target" in activity


def test_the_coverage_page_fills_every_panel_when_there_is_no_run() -> None:
    """The no-run branch used to return before two panels were drawn.

    Both already had an empty state written for them. Neither was ever
    reached, so "Measured against predicted" and "Sites in this run" kept
    their headings and held nothing at all.
    """
    text = _read("coverage.js")
    start = text.index("No coverage map has been made yet")
    branch = text[start : text.index("notice(page, '');", start)]
    for call in ("drawSites(page);", "drawCalibration(page);", "setControlsHidden(page, true);"):
        assert call in branch, call


def test_hidden_means_hidden() -> None:
    """`display: flex` outranks the browser rule for `[hidden]`.

    The config check ships its export buttons with `hidden` on them, and
    `.controls { display: flex }` showed them anyway: "Download corrected
    config" was offered, as the primary button on the page, before any
    config had been loaded. Three rules in app.css already restated the
    browser's rule one class at a time; this is the reset.
    """
    assert "[hidden] { display: none !important; }" in _read("app.css")


def test_the_nav_does_not_lead_three_entries_with_the_same_word() -> None:
    """The coverage map is "Coverage" and the planner is "Planner".

    "Coverage gaps" put the word back. The nav is a column of short nouns;
    the heading keeps the full phrase. The fragment never changes.
    """
    text = _client().get("/").text
    assert 'href="#gaps"' in text
    nav = text[text.index("<nav") : text.index("</nav>")]
    assert ">Gaps</a>" in nav
    assert "Coverage gaps" not in nav
    assert "<h2>Coverage gaps</h2>" in text


def test_every_control_has_a_name_that_is_not_a_placeholder() -> None:
    """A placeholder is not an accessible name, and it goes when you type.

    Several selects had no label of any kind, and the three search boxes
    had only a placeholder.
    """
    # HTML COMMENTS STRIPPED FIRST.
    #
    # This scans raw markup with a regex, so a comment that mentions a
    # control reads as that control. It happened: a comment explaining
    # why the preset switch is "a radio group and not a `<select>`" was
    # reported as an unnamed <select>, and the page was correct.
    #
    # Stripped here rather than reworded in the page, because the next
    # comment to mention an element would fail the same way, and a test
    # that forbids naming HTML in a comment is a test that shapes prose.
    text = re.sub(r"<!--.*?-->", "", _client().get("/").text, flags=re.S)
    depth = 0
    for tag in re.findall(r"<(/?)(label|input|select)\b([^>]*)>", text):
        closing, name, rest = tag
        if name == "label":
            depth += -1 if closing else 1
            continue
        if closing or "hidden" in rest:
            continue
        # A control is named by `aria-label`, or by the <label> around it.
        named = "aria-label=" in rest or "aria-labelledby=" in rest
        assert named or depth > 0, f"<{name}{rest}>"


def test_the_two_search_boxes_behave_the_same_way() -> None:
    """Same affordance, same behaviour.

    The graph box filtered as it was typed; the nodes box waited for Enter
    or for the button beside it, with nothing to tell the two apart. The
    nodes list runs to thousands of rows on production, so its box waits
    for a pause in the typing rather than firing per keystroke, and a
    token stops a slow answer from landing after a newer one.
    """
    app = _read("app.js")
    assert "NODE_SEARCH_PAUSE_MS" in app
    assert "nodeSearchTimer = setTimeout(() => render('nodes')" in app
    assert "if (token !== nodeSearchToken) return;" in app
