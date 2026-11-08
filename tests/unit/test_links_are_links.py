"""A link to a page is an `<a href>`, not a button (beta-sonoran#411).

Tyler: "you cannot right click and copy or open in new tab or anything
else that you would do with a link". The node chips, the traceroute
feed, the traceroute hops and the map bubble's "Open node detail" were
buttons that set `location.hash` on click. A browser cannot open a
button in a new tab, copy its address or show it on hover.
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP = (ROOT / "src" / "sonoran" / "web" / "static" / "app.js").read_text(encoding="utf-8")

# A stand-in for the page's `el` helper: it records the tag and the
# attributes, which is all these checks read.
EL = """
function el(tag, attrs, ...children) {
  return { tag, attrs: attrs || {}, children: children.flat() };
}
"""


def _function(name: str) -> str:
    start = APP.index(f"function {name}(")
    return APP[start : APP.index("\n}\n", start) + 2]


def _run(script: str) -> object:
    node = shutil.which("node")
    assert node, "node is not on PATH, so the links went unchecked. A skip looks like a pass."
    done = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_a_node_chip_is_a_link_to_the_node_page() -> None:
    script = (
        EL
        + "".join(_function(n) for n in ("nodeChip", "nodeHref") if f"function {n}(" in APP)
        + "const chip = nodeChip({ node_id: '!a81f4ac3', display_name: 'Dome Light' });"
        + "console.log(JSON.stringify({ tag: chip.tag, href: chip.attrs.href || null }));"
    )
    chip = _run(script)
    assert chip == {"tag": "a", "href": "#node/!a81f4ac3"}, (
        f"a node chip is a {chip['tag']!r} with href {chip['href']!r}, so it cannot be "
        "opened in a new tab or copied"
    )


def test_no_button_navigates_to_a_node_or_a_traceroute() -> None:
    """The plausible regression: a new button that sets the hash on click."""
    offenders = re.findall(
        r"el\('button',\s*\{[^}]*onclick:\s*\(\)\s*=>\s*open(?:Node|Traceroute|Packet)\(",
        APP,
    )
    assert not offenders, f"{len(offenders)} buttons still navigate instead of linking"
