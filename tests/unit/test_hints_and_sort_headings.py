"""Column hints and sortable headings (Phase A, §3.3).

Two of Will's items, and neither needed a new component: this site already
had one hint pattern -- `data-hint` on a heading, turned by `revealHints`
into a button that opens a panel on a tap as well as a hover. The work was
to use it and to fix the layout bug he reported.

1. **"the tooltip info icon is causing a line break."** `th.sortable` had
   `padding: 0` and `.sort-button` was `display: flex; width: 100%`, so the
   button filled the cell and the inline hint button after it had nowhere
   to sit but the next line.
2. **"I don't like the 'What this cannot know' on each leaderboard ... an
   info icon with a tooltip instead on the title."** Twelve disclosures on
   one page became twelve icons using the existing pattern.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "src" / "sonoran" / "web" / "static"


def _css() -> str:
    return re.sub(r"/\*.*?\*/", "", (STATIC / "app.css").read_text(encoding="utf-8"), flags=re.S)


def _app() -> str:
    text = re.sub(r"/\*.*?\*/", "", (STATIC / "app.js").read_text(encoding="utf-8"), flags=re.S)
    return "\n".join(
        line
        for line in text.splitlines()
        if (stripped := line.strip()) and not stripped.startswith("//")
    )


def test_the_comment_stripper_works() -> None:
    assert "function revealHints" in _app(), "the stripper removed real code"
    assert "Will reported" not in _app(), "comments are leaking through"


# --- the line break -------------------------------------------------


def test_the_sort_button_does_not_fill_the_cell() -> None:
    """The cause of the reported line break.

    A full-width block button leaves no room on the line for the hint
    button that `revealHints` appends after it.
    """
    css = _css()
    rule = css[css.index(".sort-button {") :]
    rule = rule[: rule.index("}")]
    assert "inline-flex" in rule, f"the sort button is not inline: {rule!r}"
    assert "width: 100%" not in rule, "the sort button still fills the cell"


def test_the_heading_stays_a_table_cell() -> None:
    """The tempting fix that breaks column alignment.

    `display: flex` on a `th` stops it being a table-cell; the browser
    wraps it in an anonymous cell and the columns stop lining up. So the
    flexing happens on the button, not the heading.
    """
    css = _css()
    rule = css[css.index("th.sortable {") :]
    rule = rule[: rule.index("}")]
    assert "display: flex" not in rule, "th.sortable is a flex container and no longer a cell"
    assert "display: grid" not in rule


def test_a_numeric_heading_still_reaches_the_columns_edge() -> None:
    """The regression the first fix would have caused.

    `th.num` right-aligns from the cell, and the old rule justified inside
    a button that filled it. Once the button is only as wide as its label,
    justifying inside it does nothing -- the padding has to come off the
    right instead, or the heading drifts away from its numbers.
    """
    css = _css()
    assert "th.num.sortable {" in css, "numeric sortable headings have no alignment rule"
    rule = css[css.index("th.num.sortable {") :]
    rule = rule[: rule.index("}")]
    assert "padding-right: 0" in rule, f"the label will not meet the column edge: {rule!r}"
    assert "td.num, th.num { text-align: right" in css, "numeric cells no longer right-align"


# --- the sortable indicator -----------------------------------------


def test_the_inactive_arrow_is_the_same_family_as_the_active_one() -> None:
    """Will asked for "something more universal".

    One glyph family: the up-down arrow for "this sorts", the single up or
    down for the one in force. A reader learns one shape, and only the
    active one goes orange.
    """
    app = _app()
    assert "\\u2195" in app, "the inactive up-down arrow is gone"
    assert "\\u2191" in app and "\\u2193" in app, "the active arrows are gone"


def test_the_inactive_arrow_is_visible_enough_to_read_as_a_control() -> None:
    """It was at .45 opacity, which is what prompted the complaint."""
    css = _css()
    rule = css[css.index(".sort-arrow {") :]
    rule = rule[: rule.index("}")]
    found = re.search(r"opacity:\s*([\d.]+)", rule)
    assert found, f"no opacity on the arrow: {rule!r}"
    assert float(found.group(1)) >= 0.6, (
        f"the inactive arrow is at {found.group(1)}, too faint to read as sortable"
    )


def test_only_the_column_in_force_is_orange() -> None:
    """Two orange arrows would say two columns are sorting."""
    css = _css()
    assert "th.sorted .sort-arrow { opacity: 1; color: var(--accent); }" in css
    inactive = css[css.index(".sort-arrow {") : css.index("}", css.index(".sort-arrow {"))]
    assert "--accent" not in inactive, "the inactive arrow is accent-coloured too"


def test_the_arrow_is_never_the_only_signal() -> None:
    """A glyph is not reachable by a screen reader; `aria-sort` is."""
    app = _app()
    assert "'aria-sort'" in app, "the sort state is carried only by an arrow"
    assert "aria-hidden': 'true'" in app, "the decorative arrow is announced"


# --- the leaderboards -----------------------------------------------


def test_the_leaderboard_caveat_is_an_icon_on_the_title() -> None:
    app = _app()
    assert "What this cannot know" not in app, "the disclosure is still rendered"
    assert "'data-hint': board.cannot_know" in app, "the caveat is not on the heading"


def test_the_caveat_is_not_dropped() -> None:
    """It is the difference between a leaderboard and a scoreboard.

    A ranking that does not say what it cannot see invites somebody to read
    it as a judgement. The API sends one per board -- verified live: three
    boards, each with 125 to 140 characters of caveat -- so losing it here
    would be losing information the server went to the trouble of writing.
    """
    app = _app()
    assert "board.cannot_know" in app, "the caveat no longer reaches the page at all"
    route = (ROOT / "src" / "sonoran" / "api" / "routes" / "leaderboards.py").read_text(
        encoding="utf-8"
    )
    assert "cannot_know" in route, "the server no longer sends the caveat"


def test_the_hint_button_is_added_after_the_boards_are_drawn() -> None:
    """Without this the caveat is in the markup and no button appears.

    The boards are drawn by their own fetch, which can land after `render`
    has already called `revealHints` for the page. Nothing would look
    broken; the sentence would simply be gone.
    """
    app = _app()
    body = app[app.index("function loadLeaderboards") :]
    body = body[: body.index("\nPAGES.")]
    assert "revealHints(" in body, "the boards never get their hint buttons"


def test_the_button_is_named_by_the_board_not_by_the_heading_text() -> None:
    """`fitHint` builds "What this panel means: <label>".

    The heading holds the window chip too, so without an explicit label the
    accessible name would read "...: Longest reliable link last 24 h".
    """
    app = _app()
    assert "'data-label': board.title" in app, "the hint button will name the window chip too"
