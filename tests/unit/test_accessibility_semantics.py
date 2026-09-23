"""Semantics: the page works, but it told assistive technology wrong.

Five defects from an audit, each verified against the deployed
instance before and after. The measurements are in the commit; these
tests hold the shapes so they cannot come back quietly.
"""

from pathlib import Path

STATIC = Path(__file__).resolve().parents[2] / "src" / "sonoran" / "web" / "static"
APP = (STATIC / "app.js").read_text(encoding="utf-8")
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")


def test_the_current_page_says_so_and_not_only_in_colour() -> None:
    """WCAG 1.3.1. Measured: 0 `[aria-current]` on every page.

    The active link carried a `.current` class and nothing else, so the
    only signal that you were on one of fifteen pages was a colour.
    """
    assert "aria-current" in APP, "nothing marks the current page for a screen reader"
    start = APP.index("classList.toggle('current'")
    window = APP[start - 200 : start + 500]
    assert "setAttribute('aria-current', 'page')" in window, (
        "the class and the attribute are set in different places, so they will drift"
    )
    assert "removeAttribute('aria-current')" in window, (
        "the attribute is never removed, so every page visited stays marked as current"
    )


def test_a_chart_is_not_an_unlabelled_canvas() -> None:
    """WCAG 1.1.1, Level A. Measured: 0 of 4 charts labelled.

    Every `.chart` had no role, no label and empty text, and ECharts
    defaults `aria.enabled` to false, so not even its own generated
    description existed.
    """
    assert "aria: { enabled: true }" in APP, (
        "ECharts is not generating a description of what it drew"
    )
    start = APP.index("function chart(target, option)")
    body = APP[start : start + 1800]
    assert "'role', 'img'" in body, "a chart canvas has no role"
    assert "aria-label" in body, "a chart canvas has no label"


def test_the_gaps_row_is_not_a_button_containing_buttons() -> None:
    """Measured: 39 `tr[role=button]`, each with 2 interactive children.

    `role="button"` on a `<tr>` destroys the row and cell semantics
    inside it, and interactive content nested in a button role is
    invalid ARIA. The `.gap-open` button already did the work and
    already worked by keyboard.
    """
    for name in ("gaps.js", "siting.js"):
        source = (STATIC / name).read_text(encoding="utf-8")
        assert "setAttribute('role', 'button')" not in source, (
            f"{name} still makes a table row a button"
        )
        assert "tr.tabIndex = 0" not in source, (
            f"{name} still puts a table row in the tab order, where the button inside it already is"
        )


def test_there_is_exactly_one_live_region_and_it_is_polite() -> None:
    """WCAG 4.1.3, and the trap in fixing it.

    There were none, while five pages replace whole tables every 15 s.
    Marking those live would read a table aloud four times a minute,
    which is worse than silence. One short polite summary is the right
    shape.
    """
    # The attribute, not the word -- the comment above it explains why
    # there is only one, and says "aria-live" while doing so.
    assert INDEX.count('aria-live="') == 1, (
        "there is more than one live region; a replaced table announced "
        "in full is worse than no announcement at all"
    )
    start = INDEX.index('aria-live="')
    assert 'aria-live="polite"' in INDEX[start - 20 : start + 30], (
        "the live region is not polite, so it interrupts"
    )
    assert 'role="status"' in INDEX[start - 200 : start + 60]
