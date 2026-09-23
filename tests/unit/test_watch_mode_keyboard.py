"""Watch mode answers the keyboard, and gives focus back when it ends.

Two defects from #147, both measured in a headless browser against the
dev instance before and after.

**Space did nothing.** The control was `<a href="#" role="button">`. An
element carrying that role must respond to Space as well as Enter (WCAG
4.1.2), and a native anchor never does:

    live      control = A[role=button]
              Space : false -> false   (NOTHING HAPPENED)
              Enter : false -> true    (toggled)

    patched   control = BUTTON
              Space : false -> true    (toggled)
              Enter : true  -> false   (toggled)

**Focus was stranded on exit.** Leaving watch mode put focus on the map
container, which is not interactive, so a keyboard user who pressed F
ended up somewhere they could not act from (WCAG 2.4.3):

    live      focus after leaving = DIV/leaflet-container leaflet-touch
    patched   focus after leaving = BUTTON

A real `<button>` fixes the first for free and cannot drift back. The
second is an explicit `.focus()` after `undress()` has put the moved
elements back.

Item 2 of #147 -- single-key shortcuts with no off switch, WCAG 2.1.4 --
is a product decision and is deliberately NOT in this change.
"""

from pathlib import Path

STATIC = Path(__file__).resolve().parents[2] / "src" / "sonoran" / "web" / "static"
WATCH = (STATIC / "map-watch.js").read_text(encoding="utf-8")
CSS = (STATIC / "app.css").read_text(encoding="utf-8")


def _control_block() -> str:
    start = WATCH.index("const wrap = L.DomUtil.create('div', 'leaflet-bar watch-control')")
    return WATCH[start : start + 1400]


def test_the_control_is_a_real_button() -> None:
    block = _control_block()
    assert "L.DomUtil.create('button'" in block, (
        "the watch control is not a <button>; if it is an anchor wearing "
        "role=button again, Space stops working and nothing says so"
    )
    assert "L.DomUtil.create('a'" not in block, "the anchor is back"


def test_it_does_not_carry_a_role_it_no_longer_needs() -> None:
    """`role="button"` on a <button> is redundant, and it is the thing
    that made the old markup look correct while Space was broken."""
    block = _control_block()
    assert "button.role = 'button'" not in block
    assert "button.href" not in block, "a button with an href is an anchor again"


def test_focus_returns_to_the_control_when_watch_mode_ends() -> None:
    start = WATCH.index("async function leave()")
    body = WATCH[start : WATCH.index("\n  }\n", start)]
    assert ".focus()" in body, (
        "leave() no longer restores focus, so exiting strands a keyboard user on the map container"
    )
    assert body.index("undress()") < body.index(".focus()"), (
        "focus is restored before undress() puts the elements back, so it "
        "may land on a node that is about to move"
    )


def test_the_button_is_still_styled_like_a_leaflet_control() -> None:
    """A <button> inherits none of what `.leaflet-bar a` gives an anchor.

    Getting the semantics right and shipping an unstyled grey box in the
    corner of the map is not a win.
    """
    assert ".watch-control button {" in CSS, "the button has no styling at all"
    block = CSS[CSS.index(".watch-control button {") :][:400]
    for prop in ("background:", "color:", "border:", "width:", "height:"):
        assert prop in block, f"the control's {prop} is not set, so it will not match"
