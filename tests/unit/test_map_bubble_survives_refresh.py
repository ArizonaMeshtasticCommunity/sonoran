"""A node's bubble on the map survives a live refresh (#264).

Reported by StarSkream: with a node's bubble open on the map, the next
Live refresh closed it. `drawMapNodes` began with
`mapState.nodes.clearLayers()` and built every marker again, and a
Leaflet popup belongs to its marker. The Live timer calls
`render('map')` every fifteen seconds, so the bubble lasted at most that
long.

The behaviour is asserted in a real browser by the e2e journey "a node
bubble on the map survives live refreshes", which opens a bubble, waits
through the Live timer and three more refreshes, moves one node, drops
another and zooms. These checks are the cheap half that runs without a
browser: they fail on the shape of the bug itself.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP = (ROOT / "src" / "sonoran" / "web" / "static" / "app.js").read_text(encoding="utf-8")
E2E = (ROOT / "tools" / "dev" / "e2e.js").read_text(encoding="utf-8")


def _body(source: str, signature: str) -> str:
    """The text of one top-level function, up to the closing brace at column 0."""
    start = source.index(signature)
    end = source.index("\n}\n", start)
    return source[start:end]


def test_the_node_layer_is_updated_not_cleared() -> None:
    """Clearing the layer is the bug. Nothing in the redraw may do it."""
    body = _body(APP, "function drawMapNodes(rows) {")
    assert "clearLayers" not in body, (
        "drawMapNodes clears the node layer again, so every live refresh "
        "destroys the open bubble with its marker (#264)"
    )
    assert re.search(r"marks\.get\(row\.node_id\)", body), (
        "drawMapNodes no longer looks up the marker it already holds for a node, "
        "so a refresh cannot keep it"
    )


def test_a_gone_node_is_removed_and_a_moved_one_moves() -> None:
    """Updating in place has two duties that a rebuild did for free."""
    body = _body(APP, "function drawMapNodes(rows) {")
    assert "removeLayer(entry.marker)" in body, "a node that went away would stay drawn"
    assert "setLatLng(" in body, "a node that moved would stay where it was first drawn"


def test_the_bubble_reads_the_current_row() -> None:
    """Built on open from the entry, so a kept marker never shows old data."""
    body = _body(APP, "function drawMapNodes(rows) {")
    assert "bindPopup(() => mapNodePopup(entry.row))" in body, (
        "the map popup is not built on open from the entry's current row"
    )


def test_the_browser_journey_exists() -> None:
    """The real assertion is in the browser. It must not quietly go."""
    assert "a node bubble on the map survives live refreshes" in E2E
    assert "the bubble closed when the Live timer refreshed the map" in E2E
