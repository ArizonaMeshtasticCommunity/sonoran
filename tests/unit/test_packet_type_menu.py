"""The packet type menu on the live map (#385).

Will: "Right now it breaks the header by adding another line and it's
not obvious you have to click 'Packet type all ^' to collapse it. Maybe
a drop down menu with checkbox multi select would be better? Make sure
it looks good on mobile."

The behaviour is walked in a browser by three journeys in
`tools/dev/e2e.js` (desktop, watch mode and a phone). These tests hold
the parts a browser run on one machine cannot see.
"""

import re
from pathlib import Path

from fastapi.testclient import TestClient

from sonoran.api.app import create_app
from sonoran.config import Settings

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "src" / "sonoran" / "web" / "static"


def _read(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


def _function(source: str, name: str) -> str:
    body = source[source.index(f"function {name}(") :]
    return body[: body.index("\n}\n")]


def _map_controls() -> str:
    text = TestClient(create_app(Settings(_env_file=None))).get("/").text
    head = text[text.index('data-page="map"') :]
    return head[head.index('<div class="controls">') : head.index('<div class="map-shell"')]


def test_the_filter_is_a_button_and_a_menu_not_a_disclosure() -> None:
    """A `<details>` opens inside the row and pushes the header down."""
    controls = _map_controls()
    assert "data-family-toggle" in controls
    assert 'aria-controls="family-menu"' in controls
    assert 'id="family-menu"' in controls
    filt = controls[controls.index("data-family-filter") :]
    filt = filt[: filt.index("data-show-traces")]
    assert "<details" not in filt
    assert "<summary" not in filt
    assert "data-family-done" in filt
    assert "data-family-all" in filt


def test_each_kind_is_a_labelled_checkbox() -> None:
    body = _function(_read("app.js"), "wireFamilyFilter")
    assert "SonoranLive.FAMILY_ORDER.map((key)" in body
    assert "el('label', { class: 'family-option'" in body
    assert "type: 'checkbox'" in body
    assert "el('span', { text: family.label })" in body


def test_the_menu_opens_in_the_top_layer() -> None:
    """A popover takes no room in the row and is not clipped by the
    watch bar's sideways scroll. The fallback closes on a tap outside."""
    app = _read("app.js")
    body = _function(app, "wireFamilyFilter")
    assert "menu.setAttribute('popover', 'auto');" in body
    assert "wireHint(button, menu, placeMenu);" in body
    assert "function wireHint(button, panel, place = placeHint)" in app
    assert "!event.target.closest('.family-menu, .family-toggle')) closeHint();" in app


def test_the_menu_rule_sets_no_display() -> None:
    """Any `display` on the popover beats the browser's `display: none`
    for a shut popover, and the menu would never close."""
    css = _read("app.css")
    rule = re.search(r"\n\.family-menu \{(.*?)\n\}", css, re.S)
    assert rule, "no .family-menu rule"
    code = re.sub(r"/\*.*?\*/", "", rule.group(1), flags=re.S)
    assert "display" not in code
    assert "position: fixed" in code


def test_the_menu_fits_the_narrowest_screen() -> None:
    """320 CSS px under WCAG 2.2 SC 1.4.10 Reflow."""
    css = _read("app.css")
    rule = re.search(r"\n\.family-menu \{(.*?)\n\}", css, re.S)
    assert rule
    assert "width: min(16rem, calc(100vw - 1rem));" in rule.group(1)
    place = _function(_read("app.js"), "placeMenu")
    assert "wide - panel.offsetWidth - gutter" in place


def test_done_only_closes_the_menu() -> None:
    """Done wears the `.toggle` look. Without `data-no-refresh` the shared
    toggle handler marks it pressed and fetches the whole map again."""
    controls = _map_controls()
    done = controls[controls.index("data-family-done") - 60 :]
    done = done[: done.index(">Done</button>")]
    assert "data-no-refresh" in done


def test_a_tick_during_a_redraw_is_not_dropped() -> None:
    """`render` returns at once while another render is loading.
    `navigateRender` runs the redraw after the one in flight."""
    body = _function(_read("app.js"), "familyFilterChanged")
    assert "navigateRender('map')" in body
    assert "render('map')" not in body.replace("navigateRender('map')", "")
