"""The phone header is a bar, and the theme control is a button (#91).

Measured on a 390x844 phone, on the dashboard's first load:

    before   brand 44, menu 48, status 19, theme 57
             page heading began at 249 px -- 30% of the viewport
    after    two compact rows, heading at 129 px

The theme control was a 151x44 labelled `<select>` offering a
three-way choice most people make once. It is a 44x44 button now that
cycles system -> light -> dark, verified by clicking through all three
and by Enter.
"""

from pathlib import Path

STATIC = Path(__file__).resolve().parents[2] / "src" / "sonoran" / "web" / "static"
APP = (STATIC / "app.js").read_text(encoding="utf-8")
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
CSS = (STATIC / "app.css").read_text(encoding="utf-8")


def test_the_theme_control_is_a_button_that_names_its_state() -> None:
    """`aria-pressed` would be wrong: this is three states, not on/off.

    So the accessible name carries the state. An icon alone says
    nothing to a screen reader, and an icon whose meaning is "the
    opposite of what you see" says nothing to anybody.
    """
    # The element itself. A wider window catches the nav toggle, which
    # is a real two-state control and correctly carries aria-pressed.
    start = INDEX.index("data-theme-choice")
    opening = INDEX.rindex("<button", 0, start)
    block = INDEX[opening : INDEX.index("</button>", start)]
    assert "<button" in block, "the theme control is not a button"
    assert "aria-label" in block, "the theme button does not name its state"
    assert "aria-pressed" not in block, (
        "aria-pressed claims an on/off state this control does not have"
    )


def test_the_theme_keeps_all_three_states() -> None:
    """Following the system is the default and must stay reachable.

    A two-way toggle would make somebody whose operating system is set
    to light say so again here.
    """
    start = APP.index("const ORDER = [")
    order = APP[start : start + 80]
    for mode in ("system", "light", "dark"):
        assert f"'{mode}'" in order, f"the theme cycle lost {mode}"


def test_the_label_changes_with_the_state() -> None:
    """Three names, one per state, or the button lies in two of them."""
    start = APP.index("const LOOK = {")
    look = APP[start : start + 500]
    for word in ("following the system", "Theme: light", "Theme: dark"):
        assert word in look, f"no accessible name for {word!r}"


def test_the_phone_layout_is_a_bar_not_a_stack() -> None:
    """Four full-width blocks became two compact rows."""
    # Two blocks open with this query. Find ours by the note above it.
    start = CSS.index("One app bar at phone width")
    block = CSS[start : start + 1800]
    assert "flex-direction: row" in block, "the sidebar still stacks at phone width"
    assert ".brand-text { display: none" in block, (
        "the wordmark still takes a row of its own; it is the widest "
        "thing in the bar and the heading below already names the page"
    )


def test_the_theme_button_is_big_enough_for_a_thumb() -> None:
    """WCAG 2.2 SC 2.5.8 is 24x24; the phone rule already gives 44.

    The control must not opt out of that by being sized in the bar
    rule, which is the easy mistake when squeezing a row.
    """
    # Bounded by the end of the media block rather than by a character
    # count. The original took the 1800 characters after the comment,
    # which stopped covering `.theme-switch` the moment the block grew
    # -- and then failed with "substring not found" rather than with
    # anything about thumbs. The rule it guards has not changed.
    start = CSS.index("One app bar at phone width")
    opening = CSS.index("@media", start)
    block = CSS[opening : CSS.index("\n}", opening)]
    assert ".theme-switch" in block, (
        "the phone bar rule no longer mentions the theme button, so this test is measuring nothing"
    )
    theme = block[block.index(".theme-switch") :][:200]
    for forbidden in ("height:", "min-height: 0", "min-height:0"):
        assert forbidden not in theme, (
            f"the bar rule sets {forbidden!r} on the theme button, which "
            f"can take it under the 44 px the phone rule gives every control"
        )
