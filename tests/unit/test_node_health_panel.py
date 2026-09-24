"""The node page opens on the node, not on a screen of health cards (#95).

Seven health cards and a "Potential issues" panel -- both built from the
same gaps assessment -- were the first two things on the node page and
between them filled the first screen. Somebody opening the page to check
a battery scrolled past two assessments of the same data to reach it.

Measured in a headless browser at 1440x800, a typical laptop:

    live      identity/device row at y=617, 7 health cards open,
              page 5942 px
    patched   identity/device row at y=102, 0 cards open,
              "3 of 3 checks good · 3 can't tell yet", page 4818 px

and on a node that actually has problems:

    "1 of 3 checks good · 2 needs attention · 3 can't tell yet"
    groups after View all: Needs fixing, Good, Can't tell yet
    6 dots in the summary row, 2 beside the named problems

Clicking "View all checks" shows all 7 cards and the evidence panel, and
flips `aria-expanded`.

Two product calls were made here rather than asked about, and both are
argued in the comment above `healthPanel` in app.js: a count and dots
rather than a score or ring, and expanding in place rather than a modal
or a route.
"""

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[2] / "src" / "sonoran" / "web" / "static"
APP = (STATIC / "app.js").read_text(encoding="utf-8")
CSS = (STATIC / "app.css").read_text(encoding="utf-8")


def _panel() -> str:
    start = APP.index("function healthPanel(")
    return APP[start : APP.index("\n/** Say an evidence key", start)]


def test_the_identity_row_is_drawn_before_health() -> None:
    """The whole point: what somebody came for is above the fold.

    #193.3 put health inside the summary row, stacked under Device, so
    it no longer appears in the `replace(body, ...)` call. The window
    here starts at the row's construction instead, and the claim is
    unchanged: identity is built before health.

    A 200-character window was also part of why this broke. Sized to the
    construct rather than to a character count.
    """
    start = APP.index("  const summary = el('div', { class: 'grid summary-row' }")
    assert start > 0, (
        "the node page no longer builds a summary row; the health cards "
        "may be back at the top filling the first screen"
    )
    body = APP[start : APP.index("const id = encodeURIComponent(nodeId);", start)]
    assert body.index("identityPanel(node)") < body.index("health"), (
        "health is drawn before identity again"
    )
    assert body.index("health") < body.index("nodeMapPanel(detail)"), (
        "the map is built before health, which puts health below the fold"
    )


def test_checks_are_data_so_two_views_can_read_them() -> None:
    """A summary that counted rendered cards would parse words back out."""
    assert "function healthChecks(gaps, detail)" in APP, (
        "healthChecks is gone; if it went back to returning DOM, the "
        "summary cannot count anything without reading the page"
    )


def test_unknown_never_counts_against_the_node() -> None:
    """Required by #95, and the same mistake as #87.

    A check we cannot judge must not be scored as a failure, and must
    not silently inflate the denominator either.
    """
    body = _panel()
    assert "state === 'unknown'" in body, "unknown is no longer separated out"
    assert "judged.length - cannotTell.length" in body, (
        "the denominator counts unknown checks, so a node nothing could judge reads as failing them"
    )


def test_the_settings_entry_is_in_no_count() -> None:
    """It is guidance, not a check; there is nothing to pass or fail."""
    body = _panel()
    assert "check.state !== 'none'" in body, "the Settings entry is being counted as a check"


def test_only_the_problems_are_named_in_the_summary() -> None:
    """Listing the good ones is what made this two screens tall."""
    body = _panel()
    attention = body.index("health-attention")
    source = body[:attention]
    assert "attention.map" in body or "attention.length" in source, (
        "the summary no longer distinguishes what needs attention"
    )
    assert "good.map" not in body, "the summary lists the passing checks again"


def test_the_disclosure_reports_its_state() -> None:
    """A button that opens something must say whether it is open."""
    body = _panel()
    assert "'aria-expanded'" in body, "the View all button has no aria-expanded"
    assert "aria-expanded', String(open)" in body, "aria-expanded is set once and never updated"


def test_the_dot_row_is_labelled_rather_than_read_as_shapes() -> None:
    """Six unlabelled spans are noise to a screen reader."""
    body = _panel()
    assert "role: 'img'" in body and "'aria-label': sentence" in body, (
        "the dot row carries no accessible name, so the summary is "
        "available only to people who can see colour"
    )


def test_the_dots_do_not_rely_on_colour_alone() -> None:
    """WCAG 1.4.1. The ring width differs per state."""
    block = CSS[CSS.index(".health-dot {") : CSS.index(".health-attention")]
    widths = set(re.findall(r"inset 0 0 0 (\d+)px", block))
    assert len(widths) >= 3, (
        f"the state dots differ only by colour (ring widths seen: {sorted(widths)})"
    )


def test_potential_issues_still_exists_and_is_reachable() -> None:
    """#95 keeps everything, it just stops showing it twice at once.

    `showIssues` scrolls to `#node-issues`, and the buttons that call it
    live inside the expanded list, so the target must still be built.
    """
    assert "function issuesPanel(gaps)" in APP, "the evidence panel was deleted, not merged"
    assert "id: 'node-issues'" in APP, "the scroll target showIssues looks for is gone"
    assert "healthPanel(gaps, detail, issuesPanel(gaps))" in APP, (
        "the evidence panel is no longer handed to the health panel, so it "
        "is either orphaned or back to being a second panel on the page"
    )
