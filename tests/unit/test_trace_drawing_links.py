"""Each node of a traceroute drawing links to its node page (beta-sonoran#405).

The drawing stays in an `<img>`, where a third-party SVG runs no script
and follows no link. The page lays an `<a href="#node/...">` over each
node's box, from `/api/traceroutes/{id}/drawing-nodes`.
"""

import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "src" / "sonoran" / "web" / "static"
APP = (STATIC / "app.js").read_text(encoding="utf-8")
CSS = (STATIC / "app.css").read_text(encoding="utf-8")

EL = """
function el(tag, attrs, ...children) {
  return { tag, attrs: attrs || {}, children: children.flat().filter(Boolean) };
}
"""


def _function(name: str) -> str:
    start = APP.index(f"function {name}(")
    return APP[start : APP.index("\n}\n", start) + 2]


def test_a_box_becomes_a_link_placed_over_the_node() -> None:
    node = shutil.which("node")
    assert node, "node is not on PATH, so the links went unchecked. A skip looks like a pass."
    script = (
        EL
        + _function("nodeHref")
        + _function("traceNodeLinks")
        + "const links = traceNodeLinks("
        + "[{ node_id: '!52dc069b', x: 0.304, y: 0.002, w: 0.034, h: 0.028 }]);"
        + "console.log(JSON.stringify(links.map((a) => ({ tag: a.tag, ...a.attrs }))));"
    )
    done = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr
    (link,) = json.loads(done.stdout)
    assert link["tag"] == "a"
    assert link["href"] == "#node/!52dc069b"
    assert link["style"] == "left:30.4%;top:0.2%;width:3.4%;height:2.8%"
    assert "!52dc069b" in link["aria-label"]


def test_the_drawing_panel_asks_for_the_boxes_and_keeps_the_img() -> None:
    body = _function("meshGraphTrace")
    assert "drawing_nodes_url" in body, "the drawing panel never asks where the nodes are"
    assert "traceNodeLinks(" in body
    assert "el('img'" in body, "the drawing must stay in an <img>, where it is inert"
    assert ".trace-drawing-wrap" in CSS and "position: relative" in CSS
