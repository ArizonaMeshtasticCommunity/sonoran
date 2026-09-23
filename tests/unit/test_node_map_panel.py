"""The node page shows where the node is (#103).

The position was two numbers in the Identity panel — the one fact on
that page a map answers better than text.

Measured in a headless browser, with `app.js`/`app.css` served from this
tree:

    1440x900   map present, below the summary row, 342 px, 15 tiles,
               1 marker, note "Rounded to a coarser position by its
               owner…"
    3320x1797  480 px (the clamp's ceiling)
    iPhone 13  252 px, L.Browser.mobile true, dragging off, no
               horizontal scroll
    no position  panel present, no empty box, note reads
                 "This node does not share a position. That is optional."

After clicking through five nodes, exactly one `.leaflet-container`
remained, so the panels are not stacking.

**Not built: lines to neighbours and to the nodes that hear it.** The
issue offers it as "optional, and useful", from "data the page already
loads". The page does not load it — measured against
`/api/nodes/{id}/detail`, neither collection carries a position:

    neighbors  node_id, display_name, snr, last_rx_time,
               broadcast_interval_secs, time
    heard_by   node_id, display_name, count, direct_count,
               relayed_count, last_heard, avg_snr, best_snr, avg_rssi

That needs the endpoint to carry positions, which is an API change.
"""

from pathlib import Path

STATIC = Path(__file__).resolve().parents[2] / "src" / "sonoran" / "web" / "static"
APP = (STATIC / "app.js").read_text(encoding="utf-8")
CSS = (STATIC / "app.css").read_text(encoding="utf-8")


def _panel() -> str:
    start = APP.index("function nodeMapPanel(")
    return APP[start : APP.index("function drawNodeMap(", start)]


def _draw() -> str:
    start = APP.index("function drawNodeMap(")
    return APP[start : APP.index("\n/*\n * The node's health", start)]


def test_the_map_sits_below_the_first_row_of_panels() -> None:
    """Where the issue asked for it, and after what people came for."""
    start = APP.index("replace(body, summary")
    body = APP[start : start + 160]
    assert "nodeMapPanel(detail)" in body, "the node page does not draw a map"
    assert body.index("summary") < body.index("nodeMapPanel"), (
        "the map is drawn before the identity and device panels"
    )


def test_a_node_with_no_position_gets_a_sentence_and_no_empty_box() -> None:
    """Sharing a position is optional, and #96 established that treating
    a withheld one as a fault tells a careful owner they got it wrong."""
    body = _panel()
    assert "does not share a position" in body, "there is no neutral note"
    early = body.index("does not share a position")
    assert early < body.index("data-node-map"), (
        "the map container is built before the no-position case returns, "
        "so a node without a position gets an empty box"
    )


def test_a_rounded_position_is_not_drawn_as_a_radius() -> None:
    """The detail payload carries the confidence but not the rounding
    distance, so a circle would claim a precision we were not given."""
    draw = _draw()
    assert "L.circle(" not in draw, (
        "an accuracy circle is drawn to a radius the payload does not contain"
    )
    assert "coarse" in draw, "a rounded position is drawn exactly like an exact one"


def test_the_map_does_not_take_the_page_scroll() -> None:
    """A map that grabs the wheel traps a reader scrolling past it."""
    draw = _draw()
    assert "scrollWheelZoom: false" in draw, "the map grabs the scroll wheel"
    assert "L.Browser.mobile" in draw, "the map grabs the drag on a touch screen"
    assert "map.on('click'" in draw, (
        "nothing gives the map back its own gestures, so it can never be panned or zoomed"
    )


def test_old_maps_are_released() -> None:
    """`replace()` builds a new container each load, so keying on the
    element alone would leave a live Leaflet instance per visit."""
    draw = _draw()
    assert "isConnected" in draw and "nodeMaps.delete(" in draw, (
        "detached maps are never released, so clicking through nodes "
        "leaks a map, its tile layer and its listeners each time"
    )


def test_it_is_short_on_a_phone_and_taller_where_there_is_room() -> None:
    block = CSS[CSS.index(".node-map {") : CSS.index(".node-map-note")]
    assert "clamp(" in block, (
        f"the node map height is not bounded at both ends: {block.strip()[:60]!r}"
    )
