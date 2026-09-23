"""Map popups are built when somebody opens one, not when the map draws.

Every node on the planner and coverage maps used to get a full popup --
its DOM and its button listeners -- whether or not anybody ever clicked
it. Leaflet accepts a FUNCTION as popup content and calls it on open, so
the cost becomes proportional to clicks instead of to nodes.

Measured in a headless browser, counting every `document.createElement`
from before any page script ran, then opening a popup to prove it still
works:

    planner   1264 markers   7687 -> 103 elements drawn   (-98.7%)
    coverage    33 markers    780 -> 615 elements drawn   (-165, = 33 x 5)

In both arms the popup opened with identical text and the same button
count, so this buys the saving without changing what a reader sees.

The vendored Leaflet is 1.9.4 and its `_updateContent` reads
`"function" == typeof this._content ? this._content(...) : this._content`,
then appends the result as a NODE when it is not a string -- so the
DOM-construction that keeps these popups XSS-safe still holds.
"""

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[2] / "src" / "sonoran" / "web" / "static"
PLANNER = (STATIC / "planner.js").read_text(encoding="utf-8")
COVERAGE = (STATIC / "coverage.js").read_text(encoding="utf-8")
LEAFLET = (STATIC / "vendor" / "leaflet.js").read_text(encoding="utf-8")


def test_every_bindpopup_is_given_a_function() -> None:
    """A built node as the argument is the eager version, by definition."""
    for name, source in (("planner.js", PLANNER), ("coverage.js", COVERAGE)):
        for call in re.finditer(r"\.?bindPopup\(\s*(.{0,20})", source, flags=re.S):
            head = call.group(1).lstrip()
            assert head.startswith("()") or head.startswith("function"), (
                f"{name} passes built content to bindPopup ({head!r}); that "
                f"builds a popup for every node whether or not it is opened"
            )


def test_the_planner_builds_its_lines_inside_the_closure() -> None:
    """Otherwise the closure saves only the wrapper.

    The rows, the reached/not-reached line and both buttons are the
    expensive part. A first draft wrapped `el('div', {}, ...lines)` in a
    function while `lines` was still built eagerly above it, which
    measured as no saving at all.
    """
    start = PLANNER.index("marker.bindPopup(")
    body = PLANNER[start : start + 1800]
    assert "const lines = [" in body, (
        "the planner popup's content is still built outside the closure, "
        "so binding a function saves only the wrapping div"
    )


def test_the_vendored_leaflet_actually_resolves_functions() -> None:
    """This whole change rests on a property of the bundled library.

    If a vendor bump ever drops it, the popups silently become empty,
    which no test of our own source would catch.
    """
    assert re.search(r'"function"\s*==\s*typeof\s+this\._content', LEAFLET), (
        "the vendored Leaflet no longer evaluates function popup content; "
        "every bindPopup(() => ...) on the maps would open blank"
    )
