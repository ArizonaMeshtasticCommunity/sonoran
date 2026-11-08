"""mesh-graph's trace drawing, recoloured for the dark site (issue #51).

The SVG below has the shape Graphviz gives mesh-graph's traces: a white
page polygon, filled nodes with unfilled black text, an unfilled node,
black edges with arrowheads and a label, and a graph label. It is made
up, so no real node name is in the repository.
"""

import xml.etree.ElementTree as ET

import pytest

from sonoran.api.trace_drawing import (
    LIGHT_LINE,
    LIGHT_TEXT,
    MAX_BYTES,
    NODE_PLAIN,
    node_boxes,
    recolour,
)

SAMPLE = b"""<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN"
 "http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd">
<svg width="200pt" height="200pt" viewBox="0 0 200 200"
 xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">
<g id="graph0" class="graph" transform="translate(4 196)">
<polygon fill="white" stroke="transparent" points="-4,4 -4,-196 196,-196 196,4 -4,4"/>
<text x="10" y="-180">Trace 42</text>
<g id="node1" class="node"><title>!00000001</title>
<g id="a_node1"><a xlink:href="/nodes/!00000001" xlink:title="first">
<ellipse fill="#ffa9a9" stroke="#6adb40" cx="50" cy="-150" rx="40" ry="20"/>
<text x="50" y="-150">Alpha</text>
</a></g></g>
<g id="node2" class="node"><title>!00000002</title>
<ellipse fill="none" stroke="black" cx="50" cy="-50" rx="40" ry="20"/>
<text x="50" y="-50">Bravo</text>
</g>
<g id="node3" class="node"><title>!00000003</title>
<polygon fill="#ffffff" stroke="black" points="0,0 10,0 10,10"/>
<text x="5" y="5">Charlie</text>
</g>
<g id="edge1" class="edge"><title>a-&gt;b</title>
<path fill="none" stroke="black" d="M50,-130C50,-110 50,-90 50,-70"/>
<polygon fill="black" stroke="black" points="53,-72 50,-62 47,-72 53,-72"/>
<text x="60" y="-100">-4.5dB</text>
</g>
<g id="edge2" class="edge"><title>b-&gt;a</title>
<path fill="none" stroke="#00cc44" d="M40,-70C40,-90 40,-110 40,-130"/>
</g>
</g>
</svg>
"""

NS = {"s": "http://www.w3.org/2000/svg"}


def _tree() -> ET.Element:
    return ET.fromstring(recolour(SAMPLE))


def _group(root: ET.Element, gid: str) -> ET.Element:
    found = root.find(f".//s:g[@id='{gid}']", NS)
    assert found is not None, gid
    return found


def test_the_white_page_becomes_transparent() -> None:
    page = _tree().find("s:g/s:polygon", NS)
    assert page is not None
    assert page.get("fill") == "none"


def test_edges_arrowheads_and_edge_labels_become_light() -> None:
    edge = _group(_tree(), "edge1")
    path = edge.find("s:path", NS)
    head = edge.find("s:polygon", NS)
    label = edge.find("s:text", NS)
    assert path is not None and head is not None and label is not None
    assert path.get("stroke") == LIGHT_LINE
    assert head.get("fill") == LIGHT_LINE
    assert head.get("stroke") == LIGHT_LINE
    assert label.get("fill") == LIGHT_TEXT


def test_a_coloured_edge_keeps_its_colour() -> None:
    """mesh-graph's own colours mean something, so only black is changed."""
    path = _group(_tree(), "edge2").find("s:path", NS)
    assert path is not None
    assert path.get("stroke") == "#00cc44"


def test_text_on_a_filled_node_stays_dark() -> None:
    """It sits on a pastel fill, where light text would not read."""
    node = _group(_tree(), "node1")
    ellipse = node.find(".//s:ellipse", NS)
    text = node.find(".//s:text", NS)
    assert ellipse is not None and text is not None
    assert ellipse.get("fill") == "#ffa9a9"
    assert text.get("fill") is None


def test_text_on_an_unfilled_node_becomes_light() -> None:
    text = _group(_tree(), "node2").find("s:text", NS)
    assert text is not None
    assert text.get("fill") == LIGHT_TEXT


def test_a_graph_label_becomes_light() -> None:
    label = _tree().find("s:g/s:text", NS)
    assert label is not None
    assert label.get("fill") == LIGHT_TEXT


def test_the_output_is_still_a_plain_svg_document() -> None:
    body = recolour(SAMPLE)
    assert body.startswith(b"<?xml")
    assert b"<svg" in body
    assert b"ns0:" not in body, "the default namespace must stay unprefixed"


@pytest.mark.parametrize(
    "junk",
    [b"not xml at all", b"<html><body>error</body></html>", b"x" * (MAX_BYTES + 1)],
)
def test_anything_that_is_not_an_svg_is_refused(junk: bytes) -> None:
    with pytest.raises(ValueError):
        recolour(junk)


def test_a_plain_white_node_is_toned_down_and_keeps_dark_text() -> None:
    """Pure white is the glare. A meaningful fill is left alone."""
    node = _group(_tree(), "node3")
    shape = node.find("s:polygon", NS)
    text = node.find("s:text", NS)
    assert shape is not None and text is not None
    assert shape.get("fill") == NODE_PLAIN
    assert text.get("fill") is None
    pastel = _group(_tree(), "node1").find(".//s:ellipse", NS)
    assert pastel is not None and pastel.get("fill") == "#ffa9a9"


# beta-sonoran#405: each node of the drawing links to its node page. The
# drawing stays in an `<img>`, inert, and the page lays a link over each
# node's box. The boxes are fractions of the picture, so they scale with
# it. In SAMPLE the graph group is `translate(4 196)` in a 200 x 200 view.


def _boxes() -> dict[str, tuple[float, float, float, float]]:
    return {b["node_id"]: (b["x"], b["y"], b["w"], b["h"]) for b in node_boxes(SAMPLE)}


def test_each_node_has_a_box_in_picture_fractions() -> None:
    boxes = _boxes()
    assert set(boxes) == {"!00000001", "!00000002", "!00000003"}
    # Ellipse cx 50 cy -150 rx 40 ry 20, moved by (4, 196): x 14-94, y 26-66.
    assert boxes["!00000001"] == pytest.approx((0.07, 0.13, 0.40, 0.20))
    # Polygon 0-10 on both axes: x 4-14, y 196-206.
    assert boxes["!00000003"] == pytest.approx((0.02, 0.98, 0.05, 0.05))


def test_the_scale_of_the_graph_group_is_applied() -> None:
    scaled = SAMPLE.replace(
        b'transform="translate(4 196)"', b'transform="scale(0.5 0.5) rotate(0) translate(4 196)"'
    )
    box = {b["node_id"]: b for b in node_boxes(scaled)}["!00000001"]
    assert (box["x"], box["y"], box["w"], box["h"]) == pytest.approx((0.035, 0.065, 0.20, 0.10))


def test_a_title_that_is_not_a_node_id_gets_no_link() -> None:
    """The title is third-party text and becomes part of an href."""
    hostile = SAMPLE.replace(b"<title>!00000002</title>", b"<title>javascript:alert(1)</title>")
    assert "javascript:alert(1)" not in {b["node_id"] for b in node_boxes(hostile)}
    assert len(node_boxes(hostile)) == 2


def test_a_rotated_drawing_gets_no_links_rather_than_wrong_ones() -> None:
    rotated = SAMPLE.replace(
        b'transform="translate(4 196)"', b'transform="rotate(90) translate(4 196)"'
    )
    assert node_boxes(rotated) == []
