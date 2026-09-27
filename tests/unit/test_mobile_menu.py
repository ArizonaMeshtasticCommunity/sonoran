"""The phone bar is a hamburger and nothing else (#175).

> "On mobile navigation I think the menu button should just simply be a
> hamburger menu. Also the light / dark mode toggle can live inside that
> menu and same with the updated time. So it looks clean."

The bar was two rows — the mark and the menu button on one, the status
and the theme on the second. Both moved into the menu, so it is one
row. Measured on a 390 x 844 phone, the page heading moves from 129 px
to **77 px**; before #91 split it into two rows it was 249 px.

**The trap here is the live region**, and it is why this file exists.

The menu is `hidden` when closed, which takes everything inside it out
of the accessibility tree. The status line is the **only** live region
on this site — the comment beside it says so, deliberately — and it is
what tells a reader whether the page is still following the mesh. Moved
naively into the menu, it would stop announcing the moment a phone user
closed the menu, and nothing would look wrong.

So there are two copies: an `.sr-only` live region that stays in the bar
and is never seen, and the visible line inside the menu with no `role`,
which is why nothing is announced twice.

Verified in a browser:

    phone 390x844   closed: heading@77, toggle 40px, menu hidden,
                    status not visible, LIVE REGION IN TREE
                    open:   status, theme and 14 links all visible
    desktop 1440    toggle hidden, menu always open, status visible
"""

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[2] / "src" / "sonoran" / "web" / "static"
HTML = (STATIC / "index.html").read_text(encoding="utf-8")
CSS = (STATIC / "app.css").read_text(encoding="utf-8")
APP = (STATIC / "app.js").read_text(encoding="utf-8")


def _menu() -> str:
    """The markup inside the collapsible menu."""
    start = HTML.index('<div class="site-menu" id="site-menu">')
    return HTML[start : HTML.index("</aside>", start)]


def test_the_menu_holds_the_nav_the_status_and_a_way_to_the_theme() -> None:
    """#175 asked for the updated time and the theme inside the menu.

    Both are still reachable from it. The theme control itself moved to the
    settings page on 2026-09-26 (Will), so what the menu holds now is the
    LINK to it -- which satisfies #175's intent, that a phone user should
    not have to leave the menu to find either.

    Asserted as "a way to the theme" rather than "the theme toggle",
    because the old assertion would have passed on a control that exists
    and does nothing, and failed on a link that works.
    """
    body = _menu()
    assert 'id="site-nav"' in body, "the nav is not in the menu"
    assert "data-status" in body, "#175 asks for the updated time inside the menu"
    assert 'href="#settings"' in body, (
        "the menu has no way to reach the theme, which #175 asked to be reachable from it"
    )
    # And the page it points at really holds the control.
    assert 'data-setting="theme"' in HTML, "the settings page has no theme control"


def test_the_live_region_is_not_inside_the_menu() -> None:
    """The whole point of this file.

    `hidden` on the menu removes its contents from the accessibility
    tree, so a live region in there announces nothing while a phone
    has the menu closed — which is most of the time.
    """
    assert "data-status-live" in HTML, "the standalone live region is gone"
    assert "data-status-live" not in _menu(), (
        "the live region moved inside the menu, so it stops announcing "
        "whenever a phone user closes it — and nothing looks wrong"
    )


def test_only_one_thing_announces() -> None:
    """Two live regions would read the same sentence twice."""
    announcing = re.findall(r'aria-live="polite"', HTML)
    assert len(announcing) == 1, (
        f"{len(announcing)} live regions in the markup; the visible status "
        f"inside the menu is meant to be plain text with no role"
    )


def test_the_toggle_opens_the_menu_and_not_just_the_links() -> None:
    assert 'aria-controls="site-menu"' in HTML
    assert "menu.hidden = !open;" in APP, (
        "the toggle still hides the nav alone, so the status and the theme "
        "stay in the bar and the bar is still two rows"
    )


def test_the_button_is_an_icon_at_phone_width() -> None:
    """ "just simply be a hamburger menu" — so the word goes."""
    start = CSS.index("@media (max-width: 60rem) {")
    block = CSS[start : CSS.index("\n}", CSS.index(".site-menu", start))]
    assert ".nav-toggle .nav-toggle-label" in block and "display: none" in block, (
        "the menu button still shows its label at phone width"
    )


def test_the_label_survives_for_a_screen_reader() -> None:
    """Hiding the word visually must not leave an unnamed button."""
    start = HTML.index('<button type="button" class="nav-toggle"')
    button = HTML[start : HTML.index("</button>", start)]
    assert 'aria-label="Menu"' in button, (
        "the button's visible label is hidden at phone width and it has no "
        "accessible name, so a screen reader announces an unnamed button"
    )
